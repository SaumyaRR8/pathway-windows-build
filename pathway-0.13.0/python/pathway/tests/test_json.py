# Copyright © 2024 Pathway

from __future__ import annotations

import pathlib
import re
from typing import Any, Optional

import pandas as pd
import pytest

import pathway as pw
from pathway.debug import table_from_pandas
from pathway.tests.utils import (
    T,
    assert_table_equality,
    assert_table_equality_wo_index,
    run_all,
    write_lines,
)


def _json_table_from_list(data):
    class _JsonSubject(pw.io.python.ConnectorSubject):
        def __init__(self, data: list[dict[str, Any]]) -> None:
            super().__init__()
            self.data = data

        def run(self) -> None:
            for key, row in enumerate(self.data):
                self.next_json({"key": key + 1, **row})

    schema = pw.schema_builder(
        columns={
            "key": pw.column_definition(dtype=int, primary_key=True),
            **{name: pw.column_definition(dtype=pw.Json) for name in data[0]},
        }
    )

    return pw.io.python.read(_JsonSubject(data), schema=schema).without(pw.this.key)


def _json_table(**kwargs) -> pw.Table:
    return _json_table_from_list([dict(zip(kwargs, v)) for v in zip(*kwargs.values())])


def _optional_json_table(**kwargs) -> pw.Table:
    @pw.udf
    def filter_null(col: pw.Json) -> pw.Json | None:
        if col == pw.Json(None):
            return None
        return col

    table = _json_table(**kwargs)

    return table.select(**{name: filter_null(pw.this[name]) for name in kwargs})


def test_json_get_simple():
    input = _json_table(data=[{"field": 1}, {"field": 2}])

    result = input.select(ret=pw.this.data.get("field"))

    assert_table_equality(
        _optional_json_table(ret=[1, 2]),
        result,
    )


def test_json_get_none():
    input = _json_table(data=[{}])

    with pytest.raises(
        TypeError, match=re.escape(f"Cannot get from {pw.Json | None}.")
    ):
        input.select(result=pw.this.data.get("a").get("b"))


def test_json_get_default():
    input = _json_table(
        data=[
            {"a": {"b": 1}},
            {"a": {"b": None}},
            {"a": {}},
            {"a": [1, 2, 3]},
            {"a": 42},
            {"a": None},
            {},
            [1, 2, 3],
            None,
            1,
            "foo",
        ]
    )

    result = input.select(result=pw.this.data.get("a", default={"b": 42}))

    assert_table_equality(
        _json_table(
            result=[
                {"b": 1},
                {"b": None},
                {},
                [1, 2, 3],
                42,
                None,
                {"b": 42},
                {"b": 42},
                {"b": 42},
                {"b": 42},
                {"b": 42},
            ]
        ),
        result,
    )


def test_json_get_wo_default():
    input = _json_table(
        data=[
            {"a": {"b": 1}},
        ]
    )

    with pytest.raises(
        TypeError, match=re.escape(rf"Cannot get from {pw.Json | None}.")
    ):
        input.select(result=pw.this.data.get("a").get("b"))


def test_json_dict_get_int_index():
    input = _json_table(
        data=[
            {"a": 1},
        ]
    )

    result = input.select(result=pw.this.data.get(1))

    assert_table_equality(
        T(
            """
                | result
            1   |
            """
        ).update_types(result=Optional[pw.Json]),
        result,
    )


def test_json_array_get_str_index():
    input = _json_table(
        data=[
            {"a": [1, 2, 3]},
        ]
    )

    result = input.select(result=pw.this.data["a"].get("foo"))

    assert_table_equality(
        T(
            """
                | result
            1   |
            """
        ).update_types(result=Optional[pw.Json]),
        result,
    )


def test_json_get_wrong_default():
    input = _json_table(
        data=[
            {"a": {"b": 1}},
        ]
    )

    with pytest.raises(
        TypeError,
        match=re.escape(rf"Default must be of type {pw.Json | None}, found {int}."),
    ):
        input.select(result=pw.this.data.get("a", 42).get("b"))


def test_json_get_item():
    input = _json_table(
        data=[
            {"a": {"b": 1}},
            {"a": {"b": None}},
            {},
            {"a": {}},
            {"a": [1, 2, 3]},
            {"a": 42},
            {"a": None},
        ]
    )

    result = input.select(result=pw.this.data["a"]["b"])

    assert_table_equality(
        _json_table(result=[1, None, None, None, None, None, None]),
        result,
    )


def test_json_get_array_index():
    input = _json_table(
        index=[0, 1, 2],
        data=[{"field": [1, 2, 3]}, {"field": [4, 5, 6]}, {"field": [7, 8, 9]}],
    )

    result = input.select(result=pw.this.data["field"][pw.this.index.as_int()])

    assert_table_equality(
        _json_table(result=[1, 5, 9]),
        result,
    )


@pytest.mark.parametrize("index", [-1, -4, 3])
def test_json_get_array_index_out_of_bounds(index):
    input = _json_table(data=[{"field": [0, 1, 2]}])

    result = input.select(result=pw.this.data["field"][index])

    assert_table_equality(
        _json_table(result=[None]),
        result,
    )


def test_json_get_item_optional_json():
    input = _json_table(data=[{}])

    with pytest.raises(
        TypeError,
        match=re.escape(f"Cannot get from {pw.Json | None}."),
    ):
        input.select(result=pw.this.data.get("a")["b"])


@pytest.mark.parametrize(
    "from_,to_,method",
    [
        (
            [{"field": 42}, {"field": -1}, {"field": None}, {}],
            [42, -1, None, None],
            pw.ColumnExpression.as_int,
        ),
        (
            [
                {"field": 1.5},
                {"field": 10},
                {"field": 0},
                {"field": -1},
                {"field": 2**32 + 1},
                {"field": 2**45 + 1},
                {"field": None},
                {},
            ],
            [1.5, 10.0, 0.0, -1.0, float(2**32 + 1), float(2**45 + 1), None, None],
            pw.ColumnExpression.as_float,
        ),
        (
            [{"field": "foo"}, {"field": "42"}, {"field": "true"}, {"field": None}, {}],
            ["foo", "42", "true", None, None],
            pw.ColumnExpression.as_str,
        ),
        (
            [{"field": True}, {"field": False}, {"field": None}, {}],
            [True, False, None, None],
            pw.ColumnExpression.as_bool,
        ),
    ],
)
def test_json_as_type(from_, to_, method):
    to_dtype = type(to_[0])

    input = _json_table(data=from_)

    result = input.select(result=method(pw.this.data.get("field")))

    expected = table_from_pandas(
        pd.DataFrame({"key": list(range(1, len(to_) + 1)), "result": to_}),
        schema=pw.schema_builder(
            columns={
                "key": pw.column_definition(primary_key=True, dtype=int),
                "result": pw.column_definition(dtype=Optional[to_dtype]),
            }
        ),
    ).without(pw.this.key)

    assert_table_equality(result, expected)


@pytest.mark.parametrize(
    "value",
    ["42", "foo", 1.6, True],
)
def test_json_as_int_wrong_values(value):
    input = _json_table(data=[{"field": value}])

    input.select(result=pw.this.data.get("field").as_int())

    with pytest.raises(ValueError):
        run_all()


@pytest.mark.parametrize(
    "value",
    ["42", "foo", True],
)
def test_json_as_float_wrong_values(value):
    input = _json_table(data=[{"field": value}])

    input.select(result=pw.this.data.get("field").as_float())

    with pytest.raises(ValueError):
        run_all()


@pytest.mark.parametrize(
    "value",
    [1, 1.6, True],
)
def test_json_as_str_wrong_values(value):
    input = _json_table(data=[{"field": value}])

    input.select(result=pw.this.data.get("field").as_str())

    with pytest.raises(ValueError):
        run_all()


@pytest.mark.parametrize(
    "value",
    [1, 0, 1.6, "1", "0", "true", "True"],
)
def test_json_as_bool_wrong_values(value):
    input = _json_table(data=[{"field": value}])

    input.select(result=pw.this.data.get("field").as_bool())

    with pytest.raises(ValueError):
        run_all()


def test_json_input():
    table = _json_table_from_list(
        [
            {
                "a": {"field": 1},
                "b": 2,
                "c": 1.5,
                "d": True,
                "e": "foo",
                "f": [1, 2, 3],
            }
        ]
    )

    result = table.select(
        a=pw.this.a["field"].as_int(),
        b=pw.this.b.as_int(),
        c=pw.this.c.as_float(),
        d=pw.this.d.as_bool(),
        e=pw.this.e.as_str(),
        f=pw.this.f[1].as_int(),
    )

    assert_table_equality(
        T(
            """
                | a | b | c   | d    | e    | f
            1   | 1 | 2 | 1.5 | True | foo  | 2
            """
        ).update_types(
            a=Optional[int],
            b=Optional[int],
            c=Optional[float],
            d=Optional[bool],
            e=Optional[str],
            f=Optional[int],
        ),
        result,
    )


def test_json_apply():
    table = _json_table(a=[1, 2, 3])

    @pw.udf
    def map(a: pw.Json) -> int:
        assert isinstance(a.value, int)
        return a.value + 1

    result = table.select(ret=map(**table))

    assert_table_equality(
        T(
            """
                | ret
            1   | 2
            2   | 3
            3   | 4
            """
        ),
        result,
    )


def test_json_flatten():
    input = _json_table(
        data=[[1, 2], [3], [4, 5]],
    )

    result = input.flatten(pw.this.data).select(data=pw.this.data.as_int())

    assert_table_equality_wo_index(
        T(
            """
                | data
            1   | 1
            2   | 2
            3   | 3
            4   | 4
            5   | 5
            """
        ).update_types(data=Optional[int]),
        result,
    )


@pytest.mark.parametrize(
    "value",
    [1, 0, 1.6, "1", "0", "true", {"field": [1]}, None],
)
def test_json_flatten_wrong_values(value):
    input = _json_table(
        data=[value],
    )

    input.flatten(pw.this.data)

    with pytest.raises(ValueError, match=r"Pathway can't flatten this Json.*"):
        run_all()


def test_json_udf_array_getitem():
    table = _json_table(a=[{"field": [1]}, {"field": [2]}, {"field": [3]}])

    @pw.udf
    def map(a: pw.Json) -> int:
        value = a["field"][0].as_int()
        assert isinstance(value, int)
        return value + 1

    result = table.select(ret=map(**table))

    assert_table_equality(
        T(
            """
                | ret
            1   | 2
            2   | 3
            3   | 4
            """
        ),
        result,
    )


def test_json_udf_str_getitem():
    table = _json_table(a=[{"field": "foo"}, {"field": "bar"}, {"field": "baz"}])

    @pw.udf
    def map(a: pw.Json) -> str:
        value = a["field"][0].as_str()
        assert isinstance(value, str)
        return value

    result = table.select(ret=map(**table))

    assert_table_equality(
        T(
            """
                | ret
            1   | f
            2   | b
            3   | b
            """
        ),
        result,
    )


def test_json_udf_number_getitem():
    table = _json_table(a=[1, 2, 3])

    @pw.udf
    def map(a: pw.Json) -> int:
        a["field"]
        return 42

    table.select(ret=map(**table))

    with pytest.raises(TypeError):
        run_all()


@pytest.mark.parametrize(
    "values,method",
    [
        ([0, 1, -1], pw.Json.as_int),
        ([1.0, 3.14, -1.2, -1, 42], pw.Json.as_float),
        (["foo", "bar", "baz"], pw.Json.as_str),
        ([True, False], pw.Json.as_bool),
        ([[1, 2, 3], [3, 4, 5]], pw.Json.as_list),
        ([{"a": "foo"}, {"b": "bar"}], pw.Json.as_dict),
    ],
)
def test_json_udf_as_type(values, method):
    to_dtype = type(values[0])
    table = _json_table(data=values)

    @pw.udf
    def map(value: pw.Json):
        return method(value)

    result = table.select(ret=map(pw.this.data)).update_types(ret=to_dtype)

    expected = table_from_pandas(
        pd.DataFrame({"key": list(range(1, len(values) + 1)), "ret": values}),
        schema=pw.schema_builder(
            columns={
                "key": pw.column_definition(primary_key=True, dtype=int),
                "ret": pw.column_definition(dtype=to_dtype),
            }
        ),
    ).without(pw.this.key)

    assert_table_equality(result, expected)


@pytest.mark.parametrize(
    "value",
    [None, 1, 42, "42", 3.14, True, [1, 2, 3], {"a": "foo"}],
)
@pytest.mark.parametrize(
    "_type,method",
    [
        (int, pw.Json.as_int),
        (float, pw.Json.as_float),
        (str, pw.Json.as_str),
        (bool, pw.Json.as_bool),
        (list, pw.Json.as_list),
        (dict, pw.Json.as_dict),
    ],
)
def test_json_udf_as_type_wrong_values(value, _type, method):
    if isinstance(value, _type):
        return
    if isinstance(value, int) and _type == float:
        return

    table = _json_table(a=[{"field": value}])

    @pw.udf
    def map(a: pw.Json) -> Any:
        return method(a["field"])

    table.select(ret=map(**table))

    with pytest.raises(ValueError, match="Cannot convert Json.*"):
        run_all()


def test_json_type():
    table = _json_table(
        a=[{"field": 1}], b=[2], c=[1.5], d=[True], e="foo", f=[[1, 2, 3]]
    )

    @pw.udf
    def assert_types(**kwargs) -> bool:
        return all(isinstance(arg, pw.Json) for arg in kwargs.values())

    result = table.select(ret=assert_types(**table))

    assert_table_equality(
        T(
            """
                | ret
            1   | True
            """
        ),
        result,
    )


def test_json_recursive():
    table = T(
        """
            | value
        1   | 1
        2   | 2
        3   | 3
        """
    )

    @pw.udf
    def wrap(value: int) -> pw.Json:
        j = pw.Json(pw.Json(pw.Json(value)))
        assert isinstance(j.value, int)
        return j

    result = table.select(ret=wrap(pw.this.value).as_int())

    assert_table_equality(
        T(
            """
                | ret
            1   | 1
            2   | 2
            3   | 3
            """
        ).update_types(ret=Optional[int]),
        result,
    )


def test_json_nested():
    table = T(
        """
            | value
        1   | foo
        2   | bar
        3   | baz
        """
    )

    @pw.udf
    def wrap(value: int) -> pw.Json:
        j = pw.Json(pw.Json([pw.Json(value)]))
        assert isinstance(j[0].as_str(), str)
        return j

    result = table.select(ret=wrap(pw.this.value).get(0).as_str())

    assert_table_equality(
        result,
        T(
            """
                | ret
            1   | foo
            2   | bar
            3   | baz
            """
        ).update_types(ret=Optional[str]),
    )


@pytest.mark.parametrize(
    "delimiter",
    [",", ";", "\t"],
)
def test_json_in_csv(tmp_path: pathlib.Path, delimiter: str):
    values = [
        ('"{""a"": 1,""b"": ""foo"", ""c"": null, ""d"": [1,2,3]}"', dict),
        ('"[1,2,3]"', list),
        ("[]", list),
        ("1", int),
        ('"42"', int),
        ("1.5", float),
        ('""""""', str),
        ('"""42"""', str),
        ('"""foo"""', str),
        ('"""true"""', str),
        ("true", bool),
        ('"false"', bool),
        ("null", type(None)),
    ]

    if delimiter != ",":
        values += [
            ('{"field": 1, "b": "foo", "c": null, "d": [1,2,3]}', dict),
            ("[1,2,3]", list),
        ]

    headers = [f"c{i}" for i in range(0, len(values))]
    input_path = tmp_path / "input.csv"
    write_lines(
        input_path,
        [
            delimiter.join(headers),
            delimiter.join([v[0] for v in values]),
        ],
    )

    schema = pw.schema_builder(
        {name: pw.column_definition(dtype=pw.Json) for name in [c for c in headers]}
    )
    table = pw.io.csv.read(
        input_path,
        schema=schema,
        mode="static",
        csv_settings=pw.io.csv.CsvParserSettings(delimiter=delimiter),
    )

    @pw.udf
    def assert_types(**kwargs) -> bool:
        result = all(isinstance(arg, pw.Json) for arg in kwargs.values())
        for v, t in zip(kwargs.values(), [v[1] for v in values]):
            assert isinstance(v.value, t)
        return result

    result = table.select(ret=assert_types(**table))

    assert_table_equality_wo_index(
        T(
            """
                | ret
            1   | True
            """
        ),
        result,
    )


@pytest.mark.parametrize(
    "data,_type",
    [
        ([0, 1.0, -1.5, "0", "0.0", True], float),
        ([0, 1.0, -1.5, "0", True], int),
        ([True, 1.5, 42, 0, "", "1", "0", [42], {}], bool),
    ],
)
def test_json_coerce(data, _type):
    @pw.udf(return_type=_type)
    def coerce(value: pw.Json):
        result = _type(value)
        assert isinstance(result, _type)
        return result

    table = _json_table(data=data).select(ret=coerce(pw.this.data))

    expected = pw.debug.table_from_rows(
        schema=pw.schema_builder(
            columns={
                "ret": pw.column_definition(dtype=_type),
            }
        ),
        rows=[(_type(x),) for x in data],
    )

    assert_table_equality_wo_index(
        table,
        expected,
    )


def test_json_iter():
    table = _json_table(data=[{"field": [1, 2, 3]}, {"field": [4, 5, 6]}])

    @pw.udf
    def sum_(a: pw.Json) -> int:
        return sum(x.as_int() for x in a["field"])

    result = table.select(ret=sum_(pw.this.data))

    assert_table_equality(
        T(
            """
                | ret
            1   | 6
            2   | 15
            """
        ).update_types(ret=int),
        result,
    )


def test_json_iter_wrong_value():
    table = _json_table(data=[{"field": 42}])

    @pw.udf
    def sum_(value: pw.Json) -> int:
        return sum(x.as_int() for x in value["field"])

    table.select(ret=sum_(pw.this.data))

    with pytest.raises(TypeError, match="'int' object is not iterable"):
        run_all()


def test_json_len():
    table = _json_table(
        data=[{"field": [1, 2, 3]}, {"field": {"foo": 1, "bar": [1, 2, 3]}}]
    )

    @pw.udf
    def len_(value: pw.Json) -> int:
        return len(value["field"])

    result = table.select(ret=len_(pw.this.data))

    assert_table_equality(
        T(
            """
                | ret
            1   | 3
            2   | 2
            """
        ).update_types(ret=int),
        result,
    )


def test_json_len_wrong_value():
    table = _json_table(data=[{"field": 42}])

    @pw.udf
    def len_(value: pw.Json) -> int:
        return len(value["field"])

    table.select(ret=len_(pw.this.data))

    with pytest.raises(TypeError, match="object of type 'int' has no len()"):
        run_all()


def test_json_index():
    table = _json_table(data=[{"field": 42}])

    @pw.udf
    def bin_(value: pw.Json) -> str:
        return bin(value["field"])

    result = table.select(ret=bin_(pw.this.data))

    assert_table_equality(
        T(
            """
                | ret
            1   | 0b101010
            """
        ).update_types(ret=str),
        result,
    )


def test_json_index_wrong_value():
    table = _json_table(data=[{"field": 42.5}])

    @pw.udf
    def bin_(value: pw.Json) -> str:
        return bin(value["field"])

    table.select(ret=bin_(pw.this.data))

    with pytest.raises(
        TypeError, match="'float' object cannot be interpreted as an integer"
    ):
        run_all()


def test_json_reversed():
    table = _json_table(
        data=[{"field": ["foo", "bar"]}, {"field": {"baz": 42, "foo": 42}}]
    )

    @pw.udf
    def reversed_(value: pw.Json) -> pw.Json:
        result = reversed(value["field"])
        return next(result)

    result = table.select(ret=reversed_(pw.this.data))

    assert_table_equality(result, _json_table(ret=["bar", "foo"]))


def test_json_reversed_wrong_value():
    table = _json_table(data=[{"field": 42}])

    @pw.udf
    def reversed_(value: pw.Json) -> pw.Json:
        result = reversed(value["field"])
        return next(result)

    table.select(ret=reversed_(pw.this.data))

    with pytest.raises(TypeError, match="'int' object is not reversible"):
        run_all()
