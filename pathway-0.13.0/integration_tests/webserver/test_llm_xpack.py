import multiprocessing
import pathlib
import time

import openapi_spec_validator
import requests
from langchain.text_splitter import CharacterTextSplitter
from langchain_core.embeddings import Embeddings

import pathway as pw
from pathway.xpacks.llm.vector_store import VectorStoreClient, VectorStoreServer

PATHWAY_HOST = "127.0.0.1"
MAX_ATTEMPTS = 20


class FakeEmbeddings(Embeddings):
    def embed_query(self, text: str) -> list[float]:
        return [1.0, 1.0, 1.0 if text == "foo" else -1.0]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self.embed_query(text) for text in texts]


def pathway_server(tmp_path, port):
    data_sources = []
    data_sources.append(
        pw.io.fs.read(
            tmp_path,
            format="binary",
            mode="streaming",
            with_metadata=True,
        )
    )

    embeddings_model = FakeEmbeddings()
    splitter = CharacterTextSplitter("\n\n", chunk_size=4, chunk_overlap=0)

    vector_server = VectorStoreServer.from_langchain_components(
        *data_sources, embedder=embeddings_model, splitter=splitter
    )
    thread = vector_server.run_server(
        host=PATHWAY_HOST,
        port=port,
        threaded=True,
        with_cache=False,
    )
    thread.join()


def test_llm_xpack_autogenerated_docs_validity(tmp_path: pathlib.Path, port: int):
    p = multiprocessing.Process(target=pathway_server, args=[tmp_path, port])
    p.start()

    description = None
    for _ in range(MAX_ATTEMPTS):
        try:
            schema = requests.get(
                f"http://{PATHWAY_HOST}:{port}/_schema?format=json", timeout=1
            )
            schema.raise_for_status()
            description = schema.json()
        except Exception:
            print("No reply so far, retrying in 1 second...")
            time.sleep(1)
            continue
        else:
            print("Got a reply from server, proceeding to checker stage")
            break

    p.terminate()

    assert description is not None
    openapi_spec_validator.validate(description)


def test_similarity_search_without_metadata(tmp_path: pathlib.Path, port: int):
    with open(tmp_path / "file_one.txt", "w+") as f:
        f.write("foo")

    p = multiprocessing.Process(target=pathway_server, args=[tmp_path, port])
    p.start()
    client = VectorStoreClient(host=PATHWAY_HOST, port=port)
    attempts = 0
    output = []
    while attempts < MAX_ATTEMPTS:
        try:
            output = client("foo")
        except requests.exceptions.RequestException:
            print("No reply so far, retrying in 1 second...")
        else:
            print("Got a reply from server, proceeding to checker stage")
            break
        time.sleep(1)
        attempts += 1
    p.terminate()
    assert len(output) == 1
    assert output[0]["dist"] < 0.0001
    assert output[0]["text"] == "foo"
    assert "metadata" in output[0]


def test_vector_store_with_langchain(tmp_path: pathlib.Path, port) -> None:
    with open(tmp_path / "file_one.txt", "w+") as f:
        f.write("foo\n\nbar")

    time.sleep(5)
    p = multiprocessing.Process(target=pathway_server, args=[tmp_path, port])
    p.start()
    time.sleep(5)
    client = VectorStoreClient(host=PATHWAY_HOST, port=port)
    attempts = 0
    output = []
    while attempts < MAX_ATTEMPTS:
        try:
            output = client.query("foo", 1, filepath_globpattern="**/file_one.txt")
        except requests.exceptions.RequestException:
            print("No reply so far, retrying in 1 second...")
        else:
            print("Got a reply from server, proceeding to checker stage")
            break
        time.sleep(3)
        attempts += 1
    time.sleep(3)
    p.terminate()
    assert len(output) == 1
    assert output[0]["text"] == "foo"