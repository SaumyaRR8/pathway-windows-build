# Copyright © 2024 Pathway

"""
Pathway vector search server and client.

The server reads source documents and build a vector index over them, then starts serving
HTTP requests.

The client queries the server and returns matching documents.
"""

import asyncio
import json
import logging
import threading
from collections.abc import Callable, Coroutine
from typing import TYPE_CHECKING, Any

import jmespath
import numpy as np
import requests

import pathway as pw
import pathway.xpacks.llm.parsers
import pathway.xpacks.llm.splitters
from pathway.stdlib.ml import index
from pathway.stdlib.ml.classifiers import _knn_lsh
from pathway.xpacks.llm._utils import _coerce_sync

if TYPE_CHECKING:
    import langchain_core.documents
    import langchain_core.embeddings
    import llama_index.core.schema


def _unwrap_udf(func):
    if isinstance(func, pw.UDF):
        return func.__wrapped__
    return func


class VectorStoreServer:
    """
    Builds a document indexing pipeline and starts an HTTP REST server for nearest neighbors queries.

    Args:
        - docs: pathway tables typically coming out of connectors which contain source documents.
        - embedder: callable that embeds a single document
        - parser: callable that parses file contents into a list of documents
        - splitter: callable that splits long documents
        - doc_post_processors: optional list of callables that modify parsed files and metadata.
            any callable takes two arguments (text: str, metadata: dict) and returns them as a tuple.
    """

    embedder_config: dict[str, Any]

    def __init__(
        self,
        *docs: pw.Table,
        embedder: Callable[[str], list[float] | Coroutine] | pw.UDF,
        parser: Callable[[bytes], list[tuple[str, dict]]] | pw.UDF | None = None,
        splitter: Callable[[str], list[tuple[str, dict]]] | pw.UDF | None = None,
        doc_post_processors: (
            list[Callable[[str, dict], tuple[str, dict]] | pw.UDF] | None
        ) = None,
        index_params: dict | None = None,
    ):
        self.docs = docs

        self.parser: Callable[[bytes], list[tuple[str, dict]]] = _unwrap_udf(
            parser if parser is not None else pathway.xpacks.llm.parsers.ParseUtf8()
        )
        self.doc_post_processors = []

        if doc_post_processors:
            self.doc_post_processors = [
                _unwrap_udf(processor)
                for processor in doc_post_processors
                if processor is not None
            ]

        self.splitter = _unwrap_udf(
            splitter
            if splitter is not None
            else pathway.xpacks.llm.splitters.null_splitter
        )
        self.embedder = _unwrap_udf(embedder)
        if isinstance(embedder, pw.UDF):
            self.embedder_config = embedder._get_config()
        else:
            self.embedder_config = {}

        # detect the dimensionality of the embeddings
        self.embedding_dimension = len(_coerce_sync(self.embedder)("."))
        logging.debug("Embedder has dimension %s", self.embedding_dimension)

        DEFAULT_INDEX_PARAMS = dict(distance_type="cosine")
        if index_params is not None:
            DEFAULT_INDEX_PARAMS.update(index_params)

        self.index_params = DEFAULT_INDEX_PARAMS

        self._graph = self._build_graph()

    @classmethod
    def from_langchain_components(
        cls,
        *docs,
        embedder: "langchain_core.embeddings.Embeddings",
        parser: Callable[[bytes], list[tuple[str, dict]]] | None = None,
        splitter: "langchain_core.documents.BaseDocumentTransformer | None" = None,
        **kwargs,
    ):
        """
        Initializes VectorStoreServer by using LangChain components.

        Args:
            - docs: pathway tables typically coming out of connectors which contain source documents
            - embedder: Langchain component for embedding documents
            - parser: callable that parses file contents into a list of documents
            - splitter: Langchaing component for splitting documents into parts
        """
        try:
            from langchain_core.documents import Document
        except ImportError:
            raise ImportError(
                "Please install langchain_core: `pip install langchain_core`"
            )

        generic_splitter = None
        if splitter:
            generic_splitter = lambda x: [  # noqa
                (doc.page_content, doc.metadata)
                for doc in splitter.transform_documents([Document(page_content=x)])
            ]

        async def generic_embedded(x: str):
            res = await embedder.aembed_documents([x])
            return res[0]

        return cls(
            *docs,
            embedder=generic_embedded,
            parser=parser,
            splitter=generic_splitter,
            **kwargs,
        )

    @classmethod
    def from_llamaindex_components(
        cls,
        *docs,
        transformations: list["llama_index.core.schema.TransformComponent"],
        parser: Callable[[bytes], list[tuple[str, dict]]] | None = None,
        **kwargs,
    ):
        """
        Initializes VectorStoreServer by using LlamaIndex TransformComponents.

        Args:
            - docs: pathway tables typically coming out of connectors which contain source documents
            - transformations: list of LlamaIndex components. The last component in this list
                is required to inherit from LlamaIndex `BaseEmbedding`
            - parser: callable that parses file contents into a list of documents
        """
        try:
            from llama_index.core.base.embeddings.base import BaseEmbedding
            from llama_index.core.ingestion.pipeline import run_transformations
            from llama_index.core.schema import BaseNode, MetadataMode, TextNode
        except ImportError:
            raise ImportError(
                "Please install llama-index-core: `pip install llama-index-core`"
            )
        try:
            from llama_index.legacy.embeddings.base import (
                BaseEmbedding as LegacyBaseEmbedding,
            )

            legacy_llama_index_not_imported = True
        except ImportError:
            legacy_llama_index_not_imported = False

        def node_transformer(x: str) -> list[BaseNode]:
            return [TextNode(text=x)]

        def node_to_pathway(x: list[BaseNode]) -> list[tuple[str, dict]]:
            return [
                (node.get_content(metadata_mode=MetadataMode.NONE), node.extra_info)
                for node in x
            ]

        if transformations is None or not transformations:
            raise ValueError("Transformations list cannot be None or empty.")

        if not isinstance(transformations[-1], BaseEmbedding) and (
            legacy_llama_index_not_imported
            or not isinstance(transformations[-1], LegacyBaseEmbedding)
        ):
            raise ValueError(
                f"Last step of transformations should be an instance of {BaseEmbedding.__name__}, "
                f"found {type(transformations[-1])}."
            )

        embedder: BaseEmbedding = transformations.pop()

        async def embedding_callable(x: str) -> list[float]:
            embedding = await embedder.aget_text_embedding(x)
            return embedding

        def generic_transformer(x: str) -> list[tuple[str, dict]]:
            starting_node = node_transformer(x)
            final_node = run_transformations(starting_node, transformations)
            return node_to_pathway(final_node)

        return VectorStoreServer(
            *docs,
            embedder=embedding_callable,
            parser=parser,
            splitter=generic_transformer,
            **kwargs,
        )

    def _build_graph(self) -> dict:
        """
        Builds the pathway computation graph for indexing documents and serving queries.
        """
        docs_s = self.docs
        if not docs_s:
            raise ValueError(
                """Please provide at least one data source, e.g. read files from disk:

pw.io.fs.read('./sample_docs', format='binary', mode='static', with_metadata=True)
"""
            )
        if len(docs_s) == 1:
            (docs,) = docs_s
        else:
            docs: pw.Table = docs_s[0].concat_reindex(*docs_s[1:])  # type: ignore

        @pw.udf
        def parse_doc(data: bytes, metadata) -> list[pw.Json]:
            rets = self.parser(data)
            metadata = metadata.value
            return [dict(text=ret[0], metadata={**metadata, **ret[1]}) for ret in rets]  # type: ignore

        parsed_docs = docs.select(data=parse_doc(docs.data, docs._metadata)).flatten(
            pw.this.data
        )

        @pw.udf
        def post_proc_docs(data_json: pw.Json) -> pw.Json:
            data: dict = data_json.value  # type:ignore
            text = data["text"]
            metadata = data["metadata"]

            for processor in self.doc_post_processors:
                text, metadata = processor(text, metadata)

            return dict(text=text, metadata=metadata)  # type: ignore

        parsed_docs = parsed_docs.select(data=post_proc_docs(pw.this.data))

        @pw.udf
        def split_doc(data_json: pw.Json) -> list[pw.Json]:
            data: dict = data_json.value  # type:ignore
            text = data["text"]
            metadata = data["metadata"]

            rets = self.splitter(text)
            return [
                dict(text=ret[0], metadata={**metadata, **ret[1]})  # type:ignore
                for ret in rets
            ]

        chunked_docs = parsed_docs.select(data=split_doc(pw.this.data)).flatten(
            pw.this.data
        )

        if asyncio.iscoroutinefunction(self.embedder):

            @pw.udf(**self.embedder_config)
            async def embedder(txt):
                result = await self.embedder(txt)
                return np.asarray(result)

        else:

            @pw.udf(**self.embedder_config)
            def embedder(txt):
                result = self.embedder(txt)
                return np.asarray(result)

        chunked_docs += chunked_docs.select(
            embedding=embedder(pw.this.data["text"].as_str())
        )

        knn_index = index.KNNIndex(
            chunked_docs.embedding,
            chunked_docs,
            n_dimensions=self.embedding_dimension,
            metadata=chunked_docs.data["metadata"],
            **self.index_params,  # type:ignore
        )

        parsed_docs += parsed_docs.select(
            modified=pw.this.data["metadata"]["modified_at"].as_int(),
            indexed=pw.this.data["metadata"]["seen_at"].as_int(),
            path=pw.this.data["metadata"]["path"].as_str(),
        )

        stats = parsed_docs.reduce(
            count=pw.reducers.count(),
            last_modified=pw.reducers.max(pw.this.modified),
            last_indexed=pw.reducers.max(pw.this.indexed),
            paths=pw.reducers.tuple(pw.this.path),
        )
        return locals()

    class StatisticsQuerySchema(pw.Schema):
        pass

    class QueryResultSchema(pw.Schema):
        result: pw.Json

    class InputResultSchema(pw.Schema):
        result: list[pw.Json]

    @pw.table_transformer
    def statistics_query(
        self, info_queries: pw.Table[StatisticsQuerySchema]
    ) -> pw.Table[QueryResultSchema]:
        stats = self._graph["stats"]

        # VectorStore statistics computation
        @pw.udf
        def format_stats(counts, last_modified, last_indexed) -> pw.Json:
            if counts is not None:
                response = {
                    "file_count": counts,
                    "last_modified": last_modified,
                    "last_indexed": last_indexed,
                }
            else:
                response = {
                    "file_count": 0,
                    "last_modified": None,
                    "last_indexed": None,
                }
            return pw.Json(response)

        info_results = info_queries.join_left(stats, id=info_queries.id).select(
            result=format_stats(stats.count, stats.last_modified, stats.last_indexed)
        )
        return info_results

    class FilterSchema(pw.Schema):
        metadata_filter: str | None = pw.column_definition(
            default_value=None, description="Metadata filter in JMESPath format"
        )
        filepath_globpattern: str | None = pw.column_definition(
            default_value=None, description="An optional Glob pattern for the file path"
        )

    InputsQuerySchema = FilterSchema

    @staticmethod
    def merge_filters(queries: pw.Table):
        @pw.udf
        def _get_jmespath_filter(
            metadata_filter: str, filepath_globpattern: str
        ) -> str | None:
            ret_parts = []
            if metadata_filter:
                ret_parts.append(f"({metadata_filter})")
            if filepath_globpattern:
                ret_parts.append(f'globmatch(`"{filepath_globpattern}"`, path)')
            if ret_parts:
                return " && ".join(ret_parts)
            return None

        queries = queries.without(
            *VectorStoreServer.FilterSchema.__columns__.keys()
        ) + queries.select(
            metadata_filter=_get_jmespath_filter(
                pw.this.metadata_filter, pw.this.filepath_globpattern
            )
        )
        return queries

    @pw.table_transformer
    def inputs_query(
        self, input_queries: pw.Table[InputsQuerySchema]  # type:ignore
    ) -> pw.Table[InputResultSchema]:
        docs = self._graph["docs"]
        # TODO: compare this approach to first joining queries to dicuments, then filtering,
        # then grouping to get each response.
        # The "dumb" tuple approach has more work precomputed for an all inputs query
        all_metas = docs.reduce(metadatas=pw.reducers.tuple(pw.this._metadata))

        input_queries = self.merge_filters(input_queries)

        @pw.udf
        def format_inputs(
            metadatas: list[pw.Json] | None, metadata_filter: str | None
        ) -> list[pw.Json]:
            metadatas: list = metadatas if metadatas is not None else []  # type:ignore
            assert metadatas is not None
            if metadata_filter:
                metadatas = [
                    m
                    for m in metadatas
                    if jmespath.search(
                        metadata_filter, m.value, options=_knn_lsh._glob_options
                    )
                ]

            return metadatas

        input_results = input_queries.join_left(all_metas, id=input_queries.id).select(
            all_metas.metadatas, input_queries.metadata_filter
        )
        input_results = input_results.select(
            result=format_inputs(pw.this.metadatas, pw.this.metadata_filter)
        )
        return input_results

    class RetrieveQuerySchema(pw.Schema):
        query: str = pw.column_definition(
            description="Your query for the similarity search",
            example="Pathway data processing framework",
        )
        k: int = pw.column_definition(
            description="The number of documents to provide", example=2
        )
        metadata_filter: str | None = pw.column_definition(
            default_value=None, description="Metadata filter in JMESPath format"
        )
        filepath_globpattern: str | None = pw.column_definition(
            default_value=None, description="An optional Glob pattern for the file path"
        )

    @pw.table_transformer
    def retrieve_query(
        self, retrieval_queries: pw.Table[RetrieveQuerySchema]
    ) -> pw.Table[QueryResultSchema]:
        embedder = self._graph["embedder"]
        knn_index = self._graph["knn_index"]

        # Relevant document search
        retrieval_queries = self.merge_filters(retrieval_queries)
        retrieval_queries += retrieval_queries.select(
            embedding=embedder(pw.this.query),
        )

        retrieval_results = retrieval_queries + knn_index.get_nearest_items(
            retrieval_queries.embedding,
            k=pw.this.k,
            collapse_rows=True,
            metadata_filter=retrieval_queries.metadata_filter,
            with_distances=True,
        ).select(
            result=pw.this.data,
            dist=pw.this.dist,
        )

        retrieval_results = retrieval_results.select(
            result=pw.apply_with_type(
                lambda x, y: pw.Json(
                    sorted(
                        [{**res.value, "dist": dist} for res, dist in zip(x, y)],
                        key=lambda x: x["dist"],  # type: ignore
                    )
                ),
                pw.Json,
                pw.this.result,
                pw.this.dist,
            )
        )

        return retrieval_results

    @pw.table_transformer
    def query(
        self,
        query_column: pw.ColumnReference,
        number_of_matches: pw.ColumnExpression | int = 3,
        collapse_rows: bool = True,
        with_distances: bool = False,
        metadata_filter: pw.ColumnExpression | None = None,
    ):
        embedder = self._graph["embedder"]
        knn_index = self._graph["knn_index"]

        query_embedding = query_column.table.select(embeddings=embedder(query_column))
        return knn_index.get_nearest_items(
            query_embedding.embeddings,
            number_of_matches,
            collapse_rows,
            with_distances,
            metadata_filter,
        )

    def run_server(
        self,
        host,
        port,
        threaded: bool = False,
        with_cache: bool = True,
        cache_backend: (
            pw.persistence.Backend | None
        ) = pw.persistence.Backend.filesystem("./Cache"),
    ):
        """
        Builds the document processing pipeline and runs it.

        Args:
            - host: host to bind the HTTP listener
            - port: to bind the HTTP listener
            - threaded: if True, run in a thread. Else block computation
            - with_cache: if True, embedding requests for the same contents are cached
            - cache_backend: the backend to use for caching if it is enabled. The
              default is the disk cache, hosted locally in the folder ``./Cache``. You
              can use ``Backend`` class of the
              [`persistence API`](/developers/api-docs/persistence-api/#pathway.persistence.Backend)
              to override it.

        Returns:
            If threaded, return the Thread object. Else, does not return.
        """

        webserver = pw.io.http.PathwayWebserver(host=host, port=port, with_cors=True)

        # TODO(move into webserver??)
        def serve(route, schema, handler, documentation):
            queries, writer = pw.io.http.rest_connector(
                webserver=webserver,
                route=route,
                methods=("GET", "POST"),
                schema=schema,
                autocommit_duration_ms=50,
                delete_completed_queries=True,
                documentation=documentation,
            )
            writer(handler(queries))

        serve(
            "/v1/retrieve",
            self.RetrieveQuerySchema,
            self.retrieve_query,
            pw.io.http.EndpointDocumentation(
                summary="Do a similarity search for your query",
                description="Request the given number of documents from the "
                "realtime-maintained index.",
                method_types=("GET",),
            ),
        )
        serve(
            "/v1/statistics",
            self.StatisticsQuerySchema,
            self.statistics_query,
            pw.io.http.EndpointDocumentation(
                summary="Get current indexer stats",
                description="Request for the basic stats of the indexer process. "
                "It returns the number of documents that are currently present in the "
                "indexer and the time the last of them was added.",
                method_types=("GET",),
            ),
        )
        serve(
            "/v1/inputs",
            self.InputsQuerySchema,
            self.inputs_query,
            pw.io.http.EndpointDocumentation(
                summary="Get indexed documents list",
                description="Request for the list of documents present in the indexer. "
                "It returns the list of metadata objects.",
                method_types=("GET",),
            ),
        )

        def run():
            if with_cache:
                if cache_backend is None:
                    raise ValueError(
                        "Cache usage was requested but the backend is unspecified"
                    )
                persistence_config = pw.persistence.Config.simple_config(
                    cache_backend,
                    persistence_mode=pw.PersistenceMode.UDF_CACHING,
                )
            else:
                persistence_config = None

            pw.run(
                monitoring_level=pw.MonitoringLevel.NONE,
                persistence_config=persistence_config,
            )

        if threaded:
            t = threading.Thread(target=run, name="VectorStoreServer")
            t.start()
            return t
        else:
            run()


class VectorStoreClient:
    """
    A client you can use to query VectorStoreServer.

    Please provide either the `url`, or `host` and `port`.

    Args:
        host: host on which `VectorStoreServer </developers/api-docs/pathway-xpacks-llm/vectorstore#pathway.xpacks.llm.vector_store.VectorStoreServer>`_ listens
        port: port on which `VectorStoreServer </developers/api-docs/pathway-xpacks-llm/vectorstore#pathway.xpacks.llm.vector_store.VectorStoreServer>`_ listens
        url: url at which `VectorStoreServer </developers/api-docs/pathway-xpacks-llm/vectorstore#pathway.xpacks.llm.vector_store.VectorStoreServer>`_ listens
        timeout: timeout for the post requests in seconds
    """  # noqa

    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
        url: str | None = None,
        timeout: int = 15,
        additional_headers: dict | None = None,
    ):
        err = "Either (`host` and `port`) or `url` must be provided, but not both."
        if url is not None:
            if host or port:
                raise ValueError(err)
            self.url = url
        else:
            if host is None:
                raise ValueError(err)
            port = port or 80
            self.url = f"http://{host}:{port}"

        self.timeout = timeout
        self.additional_headers = additional_headers or {}

    def query(
        self,
        query: str,
        k: int = 3,
        metadata_filter: str | None = None,
        filepath_globpattern: str | None = None,
    ) -> list[dict]:
        """
        Perform a query to the vector store and fetch results.

        Args:
            query:
            k: number of documents to be returned
            metadata_filter: optional string representing the metadata filtering query
                in the JMESPath format. The search will happen only for documents
                satisfying this filtering.
            filepath_globpattern: optional glob pattern specifying which documents
                will be searched for this query.
        """

        data = {"query": query, "k": k}
        if metadata_filter is not None:
            data["metadata_filter"] = metadata_filter
        if filepath_globpattern is not None:
            data["filepath_globpattern"] = filepath_globpattern
        url = self.url + "/v1/retrieve"
        response = requests.post(
            url,
            data=json.dumps(data),
            headers=self._get_request_headers(),
            timeout=self.timeout,
        )

        responses = response.json()
        return sorted(responses, key=lambda x: x["dist"])

    # Make an alias
    __call__ = query

    def get_vectorstore_statistics(self):
        """Fetch basic statistics about the vector store."""

        url = self.url + "/v1/statistics"
        response = requests.post(
            url,
            json={},
            headers=self._get_request_headers(),
            timeout=self.timeout,
        )
        responses = response.json()
        return responses

    def get_input_files(
        self,
        metadata_filter: str | None = None,
        filepath_globpattern: str | None = None,
    ):
        """
        Fetch information on documents in the the vector store.

        Args:
            metadata_filter: optional string representing the metadata filtering query
                in the JMESPath format. The search will happen only for documents
                satisfying this filtering.
            filepath_globpattern: optional glob pattern specifying which documents
                will be searched for this query.
        """
        url = self.url + "/v1/inputs"
        response = requests.post(
            url,
            json={
                "metadata_filter": metadata_filter,
                "filepath_globpattern": filepath_globpattern,
            },
            headers=self._get_request_headers(),
            timeout=self.timeout,
        )
        responses = response.json()
        return responses

    def _get_request_headers(self):
        request_headers = {"Content-Type": "application/json"}
        request_headers.update(self.additional_headers)
        return request_headers
