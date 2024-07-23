# Copyright © 2024 Pathway

import json
from typing import Any, Iterable

import numpy as np
import pandas as pd
import pytest

import pathway as pw
from pathway.engine import USearchMetricKind
from pathway.stdlib.indexing.bm25 import TantivyBM25
from pathway.stdlib.indexing.data_index import _SCORE, DataIndex
from pathway.stdlib.indexing.nearest_neighbors import LshKnn, USearchKnn
from pathway.stdlib.indexing.vector_document_index import default_lsh_knn_document_index
from pathway.stdlib.ml.index import KNNIndex
from pathway.tests.utils import (
    T,
    assert_table_equality_wo_index,
    assert_table_equality_wo_index_types,
    xfail_on_multiple_threads,
)


class PointSchema(pw.Schema):
    coords: Any
    is_query: bool


def sort_arrays(arrays: list[np.ndarray] | None) -> list[tuple[float, float]]:
    if arrays is None:
        return []

    return sorted([tuple(array) for array in arrays])


def get_points() -> list[tuple[tuple[float, ...], bool]]:
    points = [
        (2, 2, 0),
        (3, -2, 0),
        (0, 0, 1),
        (-1, 0, 0),
        (2, -2, 1),
        (1, 2, 0),
        (-1, 1, 1),
        (-3, 1, 0),
        (-2, -3, 1),
        (1, -4, 0),
    ]
    return [(point[:-1], point[-1] == 1) for point in points]


def to_tuple_of_floats(input: Iterable[Any]) -> tuple[float, ...]:
    return tuple(float(x) for x in input)


def nn_as_table(
    to_table: list[tuple[tuple[int, int], tuple[tuple[int, int], ...]]]
) -> pw.Table:
    return pw.debug.table_from_pandas(
        pd.DataFrame(
            {
                "coords": [to_tuple_of_floats(point[0]) for point in to_table],
                "nn": [
                    tuple(to_tuple_of_floats(x) for x in point[1]) for point in to_table
                ],
            }
        )
    )


def nn_with_dists_as_table(
    to_table: list[
        tuple[tuple[int, int], tuple[tuple[int, int], ...], tuple[float, ...]]
    ]
) -> pw.Table:
    return pw.debug.table_from_pandas(
        pd.DataFrame(
            {
                "coords": [to_tuple_of_floats(point[0]) for point in to_table],
                "dist": [to_tuple_of_floats(point[2]) for point in to_table],
                "nn": [
                    tuple(to_tuple_of_floats(x) for x in point[1]) for point in to_table
                ],
            }
        )
    )


def make_usearch_data_index(
    data_column: pw.ColumnReference,
    data_table: pw.Table,
    dimensions: int,
    *,
    embedder: pw.UDF | None = None,
    metadata_column: pw.ColumnExpression | None = None,
):
    inner_index = USearchKnn(
        data_column=data_column,
        metadata_column=metadata_column,
        dimensions=dimensions,
        reserved_space=1000,
        metric=USearchMetricKind.L2SQ,
    )

    return DataIndex(
        data_table=data_table,
        inner_index=inner_index,
        embedder=embedder,
    )


def test_all_at_once():
    data = get_points()
    df = pd.DataFrame(
        {
            "coords": [to_tuple_of_floats(point[0]) for point in data],
            "is_query": [point[1] for point in data],
        }
    )
    table = pw.debug.table_from_pandas(df)
    points = table.filter(~pw.this.is_query).without(pw.this.is_query)
    queries = table.filter(pw.this.is_query).without(pw.this.is_query)
    index = KNNIndex(points.coords, points, n_dimensions=2, n_and=5)
    result = queries + index.get_nearest_items(queries.coords, k=2).select(
        nn=pw.apply(sort_arrays, pw.this.coords)
    )

    knn_lsh_index = LshKnn(points.coords, None, dimensions=2, n_and=5)
    index2 = DataIndex(points, knn_lsh_index)

    queries = queries.with_columns(k=2)
    result2 = index2.query(queries.coords, number_of_matches=queries.k).select(
        coords=pw.left.coords, nn=pw.apply(sort_arrays, pw.right.coords)
    )

    expected = nn_as_table(
        [
            ((0, 0), ((-1, 0), (1, 2))),
            ((2, -2), ((1, -4), (3, -2))),
            ((-1, 1), ((-3, 1), (-1, 0))),
            ((-2, -3), ((-1, 0), (1, -4))),
        ]
    )

    assert_table_equality_wo_index(result, expected)
    assert_table_equality_wo_index(result2, expected)


def test_all_at_once_metadata_filter():
    data = get_points()

    class InputSchema(pw.Schema):
        coords: tuple[float, float]
        is_query: bool
        metadata: pw.Json

    df = pd.DataFrame(
        {
            "coords": [to_tuple_of_floats(point[0]) for point in data],
            "is_query": [point[1] for point in data],
            "metadata": [{"foo": i} for i, _ in enumerate(data)],
        }
    )
    table = pw.debug.table_from_pandas(df, schema=InputSchema)
    points = table.filter(~pw.this.is_query).without(pw.this.is_query)
    queries = table.filter(pw.this.is_query).without(pw.this.is_query, pw.this.metadata)
    index = KNNIndex(
        points.coords,
        points,
        n_dimensions=2,
        n_and=5,
        metadata=points.metadata,
    )
    queries += queries.select(metadata_filter="foo > `4`")
    result = queries.without(pw.this.metadata_filter) + index.get_nearest_items(
        queries.coords, k=2, metadata_filter=queries.metadata_filter
    ).select(
        nn=pw.apply(sort_arrays, pw.this.coords),
    )

    knn_lsh_index = LshKnn(
        points.coords,
        points.metadata,
        dimensions=2,
        n_and=5,
    )
    index2 = DataIndex(points, knn_lsh_index)
    queries = queries.with_columns(k=2)
    result2 = index2.query(
        queries.coords,
        number_of_matches=queries.k,
        metadata_filter=queries.metadata_filter,
    ).select(coords=pw.left.coords, nn=pw.apply(sort_arrays, pw.right.coords))

    expected = nn_as_table(
        [
            ((0, 0), ((-3, 1), (1, 2))),
            ((2, -2), ((1, -4), (1, 2))),
            ((-1, 1), ((-3, 1), (1, 2))),
            ((-2, -3), ((-3, 1), (1, -4))),
        ]
    )
    assert_table_equality_wo_index(result, expected)
    assert_table_equality_wo_index(result2, expected)


def stream_points(with_k: bool = False) -> tuple[pw.Table, pw.Table]:
    points = (
        T(
            """
         x |  y | __time__
         2 |  2 |     2
         3 | -2 |     4
        -1 |  0 |     8
         1 |  2 |    12
        -3 |  1 |    16
         1 | -4 |    20
    """
        )
        .with_columns(x=pw.cast(float, pw.this.x), y=pw.cast(float, pw.this.y))
        .select(coords=pw.make_tuple(pw.this.x, pw.this.y))
    )
    queries = (
        T(
            """
         x |  y | k | __time__
         0 |  0 | 1 |     6
         2 | -2 | 2 |    10
        -1 |  1 | 3 |    14
        -2 | -3 | 0 |    18
    """
        )
        .with_columns(x=pw.cast(float, pw.this.x), y=pw.cast(float, pw.this.y))
        .select(coords=pw.make_tuple(pw.this.x, pw.this.y), k=pw.this.k)
    )
    if not with_k:
        queries = queries.without(pw.this.k)
    return points, queries


def test_update_old():
    points, queries = stream_points()
    index = KNNIndex(points.coords, points, n_dimensions=2, n_and=5)
    result = queries + index.get_nearest_items(queries.coords, k=2).select(
        nn=pw.apply(sort_arrays, pw.this.coords)
    )
    expected = nn_as_table(
        [
            ((0, 0), ((-1, 0), (1, 2))),
            ((2, -2), ((1, -4), (3, -2))),
            ((-1, 1), ((-3, 1), (-1, 0))),
            ((-2, -3), ((-1, 0), (1, -4))),
        ]
    )

    knn_lsh_index = LshKnn(
        points.coords,
        metadata_column=None,
        dimensions=2,
        n_and=5,
    )
    index2 = DataIndex(points, knn_lsh_index)
    queries = queries.with_columns(k=2)
    result2 = index2.query(
        queries.coords,
        number_of_matches=queries.k,
    ).select(coords=pw.left.coords, nn=pw.apply(sort_arrays, pw.right.coords))

    assert_table_equality_wo_index(result, expected)
    assert_table_equality_wo_index(result2, expected)


def test_asof_now():
    points, queries = stream_points()
    index = KNNIndex(points.coords, points, n_dimensions=2, n_and=5)
    result = queries + index.get_nearest_items_asof_now(queries.coords, k=2).select(
        nn=pw.apply(sort_arrays, pw.this.coords)
    )
    expected = nn_as_table(
        [
            ((0, 0), ((2, 2), (3, -2))),
            ((2, -2), ((-1, 0), (3, -2))),
            ((-1, 1), ((-1, 0), (1, 2))),
            ((-2, -3), ((-3, 1), (-1, 0))),
        ]
    )

    knn_lsh_index = LshKnn(
        points.coords,
        metadata_column=None,
        dimensions=2,
        n_and=5,
    )
    index2 = DataIndex(points, knn_lsh_index)

    index3 = make_usearch_data_index(
        points.coords, data_table=points, dimensions=2, metadata_column=None
    )

    result2 = index2.query_as_of_now(
        queries.coords,
        number_of_matches=2,
    ).select(coords=pw.left.coords, nn=pw.apply(sort_arrays, pw.right.coords))

    result3 = index3.query_as_of_now(
        queries.coords,
        number_of_matches=2,
    ).select(coords=pw.left.coords, nn=pw.apply(sort_arrays, pw.right.coords))

    assert_table_equality_wo_index(result, expected)
    assert_table_equality_wo_index(result2, expected)
    assert_table_equality_wo_index(result3, expected)


def test_update_old_with_variable_k():
    points, queries = stream_points(with_k=True)
    index = KNNIndex(points.coords, points, n_dimensions=2, n_and=5)
    result = queries.without(pw.this.k) + index.get_nearest_items(
        queries.coords, queries.k
    ).with_universe_of(queries).select(nn=pw.apply(sort_arrays, pw.this.coords))
    expected = nn_as_table(
        [
            ((0, 0), ((-1, 0),)),
            ((2, -2), ((1, -4), (3, -2))),
            ((-1, 1), ((-3, 1), (-1, 0), (1, 2))),
            ((-2, -3), ()),
        ]
    )

    knn_lsh_index = LshKnn(
        points.coords,
        None,
        dimensions=2,
        n_and=5,
    )
    index2 = DataIndex(points, knn_lsh_index)
    result2 = index2.query(
        queries.coords,
        number_of_matches=queries.k,
    ).select(coords=pw.left.coords, nn=pw.apply(sort_arrays, pw.right.coords))

    assert_table_equality_wo_index(result, expected)
    assert_table_equality_wo_index(result2, expected)


def test_asof_now_with_variable_k():
    points, queries = stream_points(with_k=True)
    index = KNNIndex(points.coords, points, n_dimensions=2, n_and=5)
    result = queries.without(pw.this.k) + index.get_nearest_items_asof_now(
        queries.coords, queries.k
    ).select(nn=pw.apply(sort_arrays, pw.this.coords))
    expected = nn_as_table(
        [
            ((0, 0), ((2, 2),)),
            ((2, -2), ((-1, 0), (3, -2))),
            ((-1, 1), ((-1, 0), (1, 2), (2, 2))),
            ((-2, -3), ()),
        ]
    )
    knn_lsh_index = LshKnn(
        points.coords,
        metadata_column=None,
        dimensions=2,
        n_and=5,
    )
    index2 = DataIndex(points, knn_lsh_index)
    result2 = index2.query_as_of_now(
        queries.coords,
        number_of_matches=queries.k,
    ).select(coords=pw.left.coords, nn=pw.apply(sort_arrays, pw.right.coords))

    index3 = make_usearch_data_index(
        points.coords, data_table=points, dimensions=2, metadata_column=None
    )
    result3 = index3.query_as_of_now(
        queries.coords,
        number_of_matches=queries.k,
    ).select(coords=pw.left.coords, nn=pw.apply(sort_arrays, pw.right.coords))

    assert_table_equality_wo_index(result, expected)
    assert_table_equality_wo_index(result2, expected)
    assert_table_equality_wo_index(result3, expected)


def test_get_distances():
    data = get_points()
    df = pd.DataFrame(
        {
            "coords": [to_tuple_of_floats(point[0]) for point in data],
            "is_query": [point[1] for point in data],
        }
    )
    table = pw.debug.table_from_pandas(df)
    points = table.filter(~pw.this.is_query).without(pw.this.is_query)
    queries = table.filter(pw.this.is_query).without(pw.this.is_query)
    index = KNNIndex(points.coords, points, n_dimensions=2, n_and=5)
    result = queries + index.get_nearest_items(
        queries.coords, k=2, with_distances=True
    ).select(
        pw.this.dist,
        nn=pw.this.coords,
    )

    expected = nn_with_dists_as_table(
        [
            ((0, 0), ((-1, 0), (1, 2)), (1, 5)),
            ((2, -2), ((3, -2), (1, -4)), (1, 5)),
            ((-1, 1), ((-1, 0), (-3, 1)), (1, 4)),
            ((-2, -3), ((1, -4), (-1, 0)), (10, 10)),
        ]
    )
    assert_table_equality_wo_index_types(result, expected)
    knn_lsh_index = LshKnn(
        points.coords,
        metadata_column=None,
        dimensions=2,
        n_and=5,
    )

    @pw.udf
    def negate_tuple(t):
        return tuple(-x for x in t)

    index2 = DataIndex(points, knn_lsh_index)
    queries = queries.with_columns(k=2)
    result2 = index2.query(
        queries.coords,
        number_of_matches=queries.k,
    ).select(
        coords=pw.left.coords, dist=negate_tuple(pw.right[_SCORE]), nn=pw.right.coords
    )

    assert_table_equality_wo_index_types(result2, expected)


def test_incorrect_metadata_filter():
    data = get_points()

    class InputSchema(pw.Schema):
        coords: tuple[float, float]
        is_query: bool
        metadata: pw.Json

    df = pd.DataFrame(
        {
            "coords": [to_tuple_of_floats(point[0]) for point in data],
            "is_query": [point[1] for point in data],
            "metadata": [{"foo": i} for i, _ in enumerate(data)],
        }
    )
    table = pw.debug.table_from_pandas(df, schema=InputSchema)
    points = table.filter(~pw.this.is_query).without(pw.this.is_query)
    queries = table.filter(pw.this.is_query).without(pw.this.is_query, pw.this.metadata)
    index = KNNIndex(
        points.coords,
        points,
        n_dimensions=2,
        n_and=5,
        metadata=points.metadata,
    )
    queries += queries.select(metadata_filter="contains(foo)")
    result = queries.without(pw.this.metadata_filter) + index.get_nearest_items(
        queries.coords, k=2, metadata_filter=queries.metadata_filter
    ).select(
        nn=pw.apply(sort_arrays, pw.this.coords),
    )
    expected = nn_as_table(
        [
            ((0, 0), ()),
            ((2, -2), ()),
            ((-1, 1), ()),
            ((-2, -3), ()),
        ]
    )
    knn_lsh_index = LshKnn(
        points.coords,
        metadata_column=points.metadata,
        dimensions=2,
        n_and=5,
    )
    index2 = DataIndex(points, knn_lsh_index)
    queries = queries.with_columns(k=2)
    result2 = index2.query(
        queries.coords,
        number_of_matches=queries.k,
        metadata_filter=queries.metadata_filter,
    ).select(coords=pw.left.coords, nn=pw.apply(sort_arrays, pw.right.coords))

    assert_table_equality_wo_index(result, expected)
    assert_table_equality_wo_index(result2, expected)


def test_mismatched_type_error_message_knn_lsh():
    table = pw.debug.table_from_markdown(
        """
        text
        aaa
        bbb
        ccc
        ddd
        """
    )

    knn_lsh_index = LshKnn(table.text, None, dimensions=2, n_and=5)
    index = DataIndex(table, knn_lsh_index)

    exp_message = (
        "Some columns have types incompatible with expected types: "
        + "data column should be compatible with type List\\(FLOAT\\) but is of type "
        + "STR, query column should be compatible with type List\\(FLOAT\\) but is of type STR"
    )
    with pytest.raises(TypeError, match=exp_message):
        index.query(table.text, number_of_matches=2).select(
            coords=pw.left.coords, nn=pw.apply(sort_arrays, pw.right.coords)
        )


def test_full_text_search():
    index_data = pw.debug.table_from_markdown(
        """
        index_text                                                          | extra_info| __time__
        Lorem ipsum dolor sit amet, consectetur adipiscing elit.            | 1         |     2
        Cras ex lorem, luctus nec dui eu, pellentesque vestibulum velit.    | 2         |     2
        Nunc laoreet tortor quis odio mattis vulputate.                     | 3         |     2
        Quisque vel dictum neque, at efficitur nisi.                        | 4         |     2
        Aliquam dui nibh, cursus ac porttitor nec, placerat quis nisi.      | 5         |     2
        Curabitur vehicula enim vitae rhoncus feugiat.                      | 6         |     2
        """,
        split_on_whitespace=False,
    )

    queries = pw.debug.table_from_markdown(
        """
        query_text | __time__
        nisi       | 2
        elit       | 2
        lorem      | 2
        marchewka  | 2
        """,
        split_on_whitespace=False,
    )

    index = TantivyBM25(index_data.index_text, metadata_column=None)
    data_index = DataIndex(index_data, index, embedder=None)
    ret = data_index.query_as_of_now(
        query_column=queries.query_text, number_of_matches=4
    ).select(qtext=pw.left.query_text, info=pw.right.extra_info)

    class ExpSchema(pw.Schema):
        qtext: str
        info: list[int] | None

    df = pd.DataFrame(
        {
            "qtext": ["elit", "lorem", "marchewka", "nisi"],
            "info": [(1,), (1, 2), None, (4, 5)],
        },
    )
    expected = pw.debug.table_from_pandas(df, schema=ExpSchema)
    assert_table_equality_wo_index(ret, expected)


def test_mismatched_type_error_message_bm25():
    class InputSchema(pw.Schema):
        int_col: int

    table = pw.debug.table_from_markdown(
        """
        int_col
        1
        2
        3
        4
        """,
        schema=InputSchema,
    )

    tantivy_index = TantivyBM25(table.int_col, None)
    index = DataIndex(table, tantivy_index)

    exp_message = (
        "Some columns have types incompatible with expected types: "
        + "data column should be compatible with type STR but is of type "
        + "INT, query column should be compatible with type STR but is of type INT"
    )
    with pytest.raises(TypeError, match=exp_message):
        index.query_as_of_now(table.int_col, number_of_matches=2).select(
            coords=pw.left.coords, nn=pw.apply(sort_arrays, pw.right.coords)
        )


@xfail_on_multiple_threads  # index duplicated across workers, more error messages
def test_errors_on_index_input():
    @pw.udf
    def make_point(r: int) -> list[float]:
        if r == 2 or r == 3:
            raise ValueError("Encountered 2 or 3")
        return [float(r), float(r)]

    data = pw.debug.table_from_markdown(
        """
        r
        1
        3
        5
        8
    """
    ).with_columns(d=make_point(pw.this.r))
    queries = pw.debug.table_from_markdown(
        """
        r
        2
        4
        6
    """
    ).with_columns(d=make_point(pw.this.r))

    index = make_usearch_data_index(data.d, data, dimensions=2)
    result = index.query_as_of_now(
        queries.d, number_of_matches=2, collapse_rows=False
    ).select(l=pw.left.r, r=pw.right.r)
    expected = pw.debug.table_from_markdown(
        """
        l | r
        2 |
        4 | 5
        4 | 1
        6 | 5
        6 | 8
    """
    )
    expected_err = pw.debug.table_from_markdown(
        """
        message
        ValueError: Encountered 2 or 3
        ValueError: Encountered 2 or 3
        Error value encountered in index update, skipping the row
        Error value encountered in index search, can't answer the query
        value error: Pathway can't flatten this value Error
    """,
        split_on_whitespace=False,
    )
    assert_table_equality_wo_index(
        (result, pw.global_error_log().select(pw.this.message)),
        (expected, expected_err),
        terminate_on_error=False,
    )


def test_errors_in_index_filter():
    @pw.udf
    def make_point(r: int) -> list[float]:
        return [float(r), float(r)]

    @pw.udf
    def load_json(s: str) -> pw.Json:
        return json.loads(s)

    data = pw.debug.table_from_markdown(
        """
        r | filter_data
        1 | {"v":2}
        5 | {"v":1}
        8 | {"v":1}
    """
    ).with_columns(d=make_point(pw.this.r), filter_data=load_json(pw.this.filter_data))
    queries = pw.debug.table_from_markdown(
        """
        r | filter_expr
        4 | v==`1`
        6 | p==0
    """
    ).with_columns(d=make_point(pw.this.r))

    index = make_usearch_data_index(
        data.d, data, dimensions=2, metadata_column=data.filter_data
    )
    result = index.query_as_of_now(
        queries.d,
        number_of_matches=2,
        collapse_rows=False,
        metadata_filter=queries.filter_expr,
    ).select(l=pw.left.r, r=pw.right.r)
    result_err = pw.global_error_log().select(
        message=pw.this.message.str.replace("\n", "")
    )
    expected = pw.debug.table_from_markdown(
        """
        l | r
        4 | 5
        4 | 8
        6 |
    """
    )
    expected_err = pw.debug.table_from_markdown(
        """
        message
        Parse error: Unexpected nud token -- found Number(0) (line 0, column 3)p==0   ^
        value error: Pathway can't flatten this value Error
    """,
        split_on_whitespace=False,
    )
    assert_table_equality_wo_index(
        (result, result_err),
        (expected, expected_err),
        terminate_on_error=False,
    )


def test_output_joined_with_other_columns():
    @pw.udf
    def embedder(x: str) -> list[float]:
        return [0.0, 1.0, 2.0]

    @pw.udf
    def sort_docs(x: list[str]) -> list[str]:
        return sorted(x)

    query = pw.debug.table_from_rows(pw.schema_from_types(query=str), [("a",)])
    docs = pw.debug.table_from_rows(
        pw.schema_from_types(doc=str), [("a",), ("b",), ("c",)]
    )

    index = default_lsh_knn_document_index(
        docs.doc, docs, dimensions=3, embedder=embedder
    )
    res = query + index.query(query.query, collapse_rows=True).select(
        doc=sort_docs(pw.right.doc)
    )
    expected = pw.debug.table_from_pandas(
        pd.DataFrame({"query": ["a"], "doc": [("a", "b", "c")]})
    )
    assert_table_equality_wo_index(res.update_types(doc=list[str]), expected)
