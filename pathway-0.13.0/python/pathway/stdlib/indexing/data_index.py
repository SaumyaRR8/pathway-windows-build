# Copyright © 2024 Pathway

# TODO: adjust so that it can be extended to cover H3index
from abc import ABC, abstractmethod
from dataclasses import dataclass

import pathway.internals as pw
from pathway.internals.dtype import FLOAT, DType, List
from pathway.internals.joins import JoinResult
from pathway.stdlib.indexing.colnames import (
    _INDEX_REPLY,
    _MATCHED_ID,
    _PACKED_DATA,
    _QUERY_ID,
    _SCORE,
    _TOPK,
)
from pathway.stdlib.utils.col import unpack_col


class IdScoreSchema(pw.Schema):
    _pw_index_reply_id: pw.Pointer
    _pw_index_reply_score: float


def _extract_data_flat(
    data_table: pw.Table,
    id_matching: pw.Table,
    query_table: pw.Table,
    as_of_now: bool = False,
) -> JoinResult:
    """
    This function takes `query_table` and left-joins it with `data_table`, using
    `id_matching` table to determine which query and data rows should be joined.
    Somewhat narrow naming comes from the fact it's an internal function of
    DataIndex, which operates on tables with data and queries.

    Args:
    data_table (pw.Table): table with data
    id_matching (pw.Table): table with at least two pointer columns (with names
        taken from variables `_QUERY_ID` and `_MATCHED_ID`), indicating
        which rows of query_table and data_table match
    query_table: table with queries
    as_of_now (bool): indicates, whether the `id_matching` is given in "as of now"
        way, or it revisits the decisions; (if id_matching is given as_of_now, and
        it is computed using a table with the same universe as `data_table`,
        we need to use asof_join to extract the results, to avoid joining outdated
        IDs with current state of the data_table)

    Returns:
    JoinResult, with one row corresponding to one matching between queries and data.
    """
    join_inner = pw.Table.asof_now_join_inner if as_of_now else pw.Table.join_inner
    join_left = pw.Table.asof_now_join_left if as_of_now else pw.Table.join_left

    joined = join_inner(id_matching, data_table, pw.left[_MATCHED_ID] == pw.right.id)
    selected_data = joined.select(pw.left[_QUERY_ID], pw.left[_SCORE], *pw.right)
    if as_of_now:
        selected_data = selected_data._forget_immediately()
    return join_left(query_table, selected_data, pw.left.id == pw.right[_QUERY_ID])


def _extract_data_collapsed_rows(
    data_table: pw.Table,
    id_matching: pw.Table,
    query_table: pw.Table,
    as_of_now: bool = False,
) -> JoinResult:
    """
    This function takes `query_table` and left-joins it with `data_table`, using
    `id_matching` table to determine which query and data rows should be joined.
    Somewhat narrow naming comes from the fact it's an internal function of
    DataIndex, which operates on tables with data and queries.

    Args:
    data_table (pw.Table): table with data
    id_matching (pw.Table): table with at least two pointer columns (with names
        taken from variables `_QUERY_ID` and `_MATCHED_ID`), indicating
        which rows of query_table and data_table match
    query_table: table with queries
    as_of_now (bool): indicates, whether the `id_matching` is given in "as of now"
        way, or it revisits the decisions; (if id_matching is given as_of_now, and
        it is computed using a table with the same universe as `data_table`,
        we need to use asof_join to extract the results, to avoid joining outdated
        IDs with current state of the data_table)

    Returns:
    JoinResult, with one row corresponding to one query, all matched data entries are
        collapsed into tuples.
    """

    join_inner = pw.Table.asof_now_join_inner if as_of_now else pw.Table.join_inner
    join_left = pw.Table.asof_now_join_left if as_of_now else pw.Table.join_left
    compacted_data = data_table + data_table.select(
        **{_PACKED_DATA: pw.make_tuple(*data_table)}
    )

    joined = join_inner(
        id_matching, compacted_data, pw.left[_MATCHED_ID] == pw.right.id
    ).select(
        pw.left[_QUERY_ID],
        pw.left[_SCORE],
        _pw_groupby_sort_key=-pw.this[_SCORE],
        *pw.right,
    )

    if as_of_now:
        joined = joined._forget_immediately()
    selected_data = joined.groupby(
        id=pw.this[_QUERY_ID],
        sort_by=pw.this._pw_groupby_sort_key,
    ).reduce(
        **{
            _TOPK: pw.reducers.tuple(pw.this[_PACKED_DATA]),
            _SCORE: pw.reducers.tuple(pw.this[_SCORE]),
        }
    )

    selected_data_rows = selected_data.select(
        transposed=pw.apply(lambda x: tuple(zip(*x)), pw.this[_TOPK]),
    )
    new_type_map: dict[str, DType] = {}
    for key in data_table.keys():
        new_type_map[key] = List(data_table[key]._column.dtype)

    selected_data_rows = unpack_col(selected_data_rows.transposed, *data_table.keys())
    selected_data_rows += selected_data.select(pw.this[_SCORE])
    new_type_map[_SCORE] = List(FLOAT)

    selected_data_rows = selected_data_rows.update_types(**new_type_map)

    # Keep queries that didn't match with anything, hence left join
    return join_left(
        query_table,
        selected_data_rows,
        query_table.id == selected_data_rows.id,
        id=query_table.id,
    )


@dataclass(frozen=True)
class InnerIndex(ABC):
    """
    Abstract class representing a data structure that accepts data (in ``self.data_column``)
    with optional metadata (in ``self.metadata_column``), and answers queries with a set of
    'matching' IDs from the data structure (optionally filtered with JMESPath query run
    against stored metadata). The IDs are taken from the table that contains
    the `data_column` column. Which IDs are considered as matched is defined in particular
    implementations of subclasses of this class. Can be used as ``index`` argument of
    :py:class:`~pathway.stdlib.indexing.DataIndex`,
    which is a wrapper that augments the matching IDs with some additional data.

    Args:
        data_column (pw.ColumnExpression [list[float]]): the column expression
            representing the data.
        metadata_column (pw.ColumnExpression [str] | None): optional column expression,
            string representation of some auxiliary data, in JSON format.

    """

    data_column: pw.ColumnReference
    metadata_column: pw.ColumnExpression | None

    @abstractmethod
    def query(
        self,
        query_column: pw.ColumnReference,
        *,
        number_of_matches: pw.ColumnExpression | int = 3,
        metadata_filter: pw.ColumnExpression | None = None,
    ) -> pw.Table:
        """
        An abstract method. Any implementation of ``query`` in a subclass for each
        entry in ``query_column`` is supposed to return a tuple containing pairs, each pair
        consisting of the matched ID and the score indicating quality of the match
        (all that taking into account ``number_of_matches`` and ``metadata_filter`` parameters).

        Whenever the index changes (via new entries in self.data_column), it should adjust
        all old answers to the queries (which is a default behavior of pathway code, as
        long as it does not use operators telling that it is not the case).

        The resulting table with results needs contain a column ``_pw_index_reply`` (name defined
        in :py:class:`~pathway.stdlib.indexing.colnames._INDEX_REPLY`), in which the resulting
        tuples are stored.

        """
        pass

    @abstractmethod
    def query_as_of_now(
        self,
        query_column: pw.ColumnReference,
        *,
        number_of_matches: pw.ColumnExpression | int = 3,
        metadata_filter: pw.ColumnExpression | None = None,
    ) -> pw.Table:
        """
        An abstract method. Any implementation of ``query_as_of_now`` in a subclass for each
        entry in ``query_column`` is supposed to return a tuple containing pairs, each pair
        consisting of the matched ID and the score indicating quality of the match
        (all that taking into account ``number_of_matches`` and ``metadata_filter`` parameters).

        The implementation of the index should not update the answers to the old queries,
        when its internal state is modified.

        The resulting table with results needs contain a column ``_pw_index_reply`` (name defined
        in pathway.stdlib.indexing.colnames._INDEX_REPLY), in which the resulting
        tuples are stored.
        """
        pass


@dataclass
class DataIndex:
    """
    A class that given an implementation of an index provides methods that augment
    the search results with supplementary `data`.

    Args:
        data_table (pw.Table): table containing supplementary data, using match-by-id (
            ID from data_table and ID from the response of ``inner_index``)
        inner_index (InnerIndex): a data structure that accepts data from some ``data_column``
            and for each query answers with a list of IDs, one ID per matched row from ``data_column``.
            The IDs are taken from the table that contains the ``data_column`` column
        embedder (pw.UDF | None): optional, if set, the index applies the ``embedder`` on
            the column passed to ``inner_index``;

    """

    data_table: pw.Table
    inner_index: InnerIndex
    embedder: pw.UDF | None = None

    def _repack_results(
        self,
        raw_result: pw.Table,
        query_table: pw.Table,
        collapse_rows: bool,
        as_of_now: bool,
    ) -> JoinResult:
        """
        Method used internally to augment the InnerIndex response with
        data from ``self.data_table``.

        The table raw_results needs to contain a column `_INDEX_REPLY`,
        storing a list of matching IDs (optionally also distances).
        ID of an entry needs to match an ID from query_table,
        the IDs stored in the `_INDEX_REPLY` list need to match
        ID column in ``self.data_table``.

        Args:
            raw_results (pw.Table[pw.Tuple[pw.Pointer, float]]):
                matching between identifiers of queries and identifiers of items stored
                in the index.
            query_table (pw.Table):
                table with queries - contains all columns from the query table,
                passes them to the output
            collapse_rows (bool):
                defines output format; if set to true, each query ID has one
                corresponding output row, containing lists with relevant responses
            as_of_now (bool):
                indicates whether the augmented response should remain fixed or
                should update on change in ``self.data_table``

        """

        flattened_ret = raw_result.with_columns(**{_QUERY_ID: pw.this.id}).flatten(
            pw.this[_INDEX_REPLY]
        )

        unpacked_results = flattened_ret

        unpacked_results += unpack_col(
            flattened_ret[_INDEX_REPLY], schema=IdScoreSchema
        )
        extract_data = (
            _extract_data_collapsed_rows if collapse_rows else _extract_data_flat
        )

        return extract_data(
            self.data_table,
            unpacked_results.without(_INDEX_REPLY),
            query_table,
            as_of_now=as_of_now,
        )

    def query(
        self,
        query_column: pw.ColumnReference,
        *,
        number_of_matches: pw.ColumnExpression | int = 3,
        collapse_rows: bool = True,
        metadata_filter: pw.ColumnExpression | None = None,
    ) -> JoinResult:
        """
        This method takes the query from ``query_column``, optionally applies
        ``self.embedder`` on it and passes it to inner index to obtain matching entries
        stored in the :py:class:`~pathway.stdlib.indexing.InnerIndex` (being a match
        depends on the implementation and the internal state of the ``InnerIndex``).

        For each query and for each column in ``self.data_table`` it computes a tuple of values
        that are in the rows that have IDs indicated by the response of the ``InnerIndex``.
        It returns a :py:class:`~pathway.JoinResult` of a left join between query table
        (a table that holds ``query_column``) and the mentioned table of tuples (exactly
        one row per query, with values not present if set of matching IDs is empty).

        Optionally, the method can skip the tupling step, and return a ``JoinResult`` of a left
        join between query table, and ``self.data_table``, using the result of ``InnerIndex`` to indicate
        when the IDs match (exactly one row per match plus one row per query with no matches).

        The answers to the old queries are updated when the state of the index changes. To work
        properly, the ``inner_index`` has to be an instance of ``InnerIndex`` supporting ``query``.

        Args:
            query_column (pw.ColumnReference): A column containing the queries, needs
                to be in the format compatible with ``self.inner_index`` (or ``self.embedder``).
            number_of_matches (pw.ColumnExpression | int ): The maximum number of
                matches returned for each query.
            collapse_rows (bool): Indicates the format of the output. If set to ``True``,
                the resulting table has exactly one row for each query, each column
                of the right side of the resulting ``JoinResult`` contains a tuple consisting
                of values from matched rows of corresponding column in ``self.data_table``.
                If set to ``False``, the result is a left join between the table holding the
                ``query_column`` and ``self.data_index``, using the results from ``self.inner_index``
                to indicate the matches between the IDs.
            metadata_filter (pw.ColumnExpression [str | None] | pw.ColumnExpression [str] | None):
                Optional, contains a boolean JMESPath query that is used to filter the potential
                answers inside ``self.inner_index`` - matching entries are included only when
                the filter function specified in `metadata_filter`` returns ``True``, when run
                against data in ``inner_index.metadata_column``, in a potentially matched row.
                Passing ``None`` as value in the column defined in the parameter ``metadata_filter``
                indicates that all possible matches corresponding to this query pass
                the filtering step.

        """

        q_col = query_column
        if self.embedder is not None:
            q_col = query_column.table.select(
                _pw_embedded_query=self.embedder(query_column)
            )._pw_embedded_query

        raw_results = self.inner_index.query(
            query_column=q_col,
            number_of_matches=number_of_matches,
            metadata_filter=metadata_filter,
        )
        return self._repack_results(
            raw_results,
            query_column.table,
            collapse_rows,
            as_of_now=False,
        )

    def query_as_of_now(
        self,
        query_column: pw.ColumnReference,
        number_of_matches: pw.ColumnExpression | int = 3,
        collapse_rows: bool = True,
        metadata_filter: pw.ColumnExpression | None = None,
    ) -> JoinResult:
        """
        This method takes the query from ``query_column``, optionally applies
        self.embedder on it and passes it to inner index to obtain matching entries
        stored in the :py:class:`~pathway.stdlib.indexing.InnerIndex` (being a match
        depends on the implementation and the internal state of the ``InnerIndex``).

        For each query and for each column in ``self.data_table`` it computes a tuple of values
        that are in the rows that have IDs indicated by the response of the ``InnerIndex``.
        It returns a :py:class:`~pathway.JoinResult` of a left join between query table (a table that holds
        ``query_column``) and the mentioned table of tuples (exactly one row per query,
        with values not present if set of matching IDs is empty).

        Optionally, the method can skip the tupling step, and return a ``JoinResult`` of a left
        join between query table, and self.data_table, using the result of ``InnerIndex`` to indicate
        when the IDs match (exactly one row per match plus one row per query with no matches).

        The index answers according to the current state of the data structure and does not
        revisit old answers. To to work properly, the ``inner_index`` has to be an instance
        of ``InnerIndex`` supporting ``query`` (all predefined indices support it, this is an
        information for third party extensions).

        Args:
            query_column (pw.ColumnReference): A column containing the queries, needs
                to be in the format compatible with ``self.inner_index`` (or ``self.embedder``).
            number_of_matches (pw.ColumnExpression | int ): The maximum number of
                matches returned for each query.
            collapse_rows (bool): Indicates the format of the output. If set to ``True``,
                the resulting table has exactly one row for each query, each column
                of the right side of the resulting ``JoinResult`` contains a tuple consisting
                of values from matched rows of corresponding column in self.data_table.
                If set to ``False``, the result is a left join between the table holding the
                ``query_column`` and ``self.data_index``, using the results from ``self.inner_index``
                to indicate the matches between the IDs.
            metadata_filter (pw.ColumnExpression [str | None] | pw.ColumnExpression [str] | None):
                Optional, contains a boolean JMESPath query that is used to filter the potential
                answers inside ``self.inner_index`` - matching entries are included only when
                the filter function specified in `metadata_filter`` returns ``True``, when run
                against data in ``inner_index.metadata_column``, in a potentially matched row.
                Passing ``None`` as value in the column defined in the parameter ``metadata_filter``
                indicates that all possible matches corresponding to this query pass
                the filtering step.
        """

        q_col = query_column
        if self.embedder is not None:
            q_col = query_column.table.select(
                _pw_embedded_query=self.embedder(query_column)
            )._pw_embedded_query

        raw_results = self.inner_index.query_as_of_now(
            query_column=q_col,
            number_of_matches=number_of_matches,
            metadata_filter=metadata_filter,
        )
        return self._repack_results(
            raw_results,
            query_column.table,
            collapse_rows,
            as_of_now=True,
        )
