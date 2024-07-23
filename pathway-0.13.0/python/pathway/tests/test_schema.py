# Copyright © 2024 Pathway

from __future__ import annotations

import csv
import importlib
import pathlib
import sys
from typing import Any

import pytest

import pathway as pw
from pathway.internals.schema import Schema
from pathway.io._utils import _compat_schema
from pathway.tests.utils import write_csv


def assert_same_schema(left: type[Schema], right: type[Schema]):
    assert left == right and left.__name__ == right.__name__


def test_schema_type_inconsistency_error():
    with pytest.raises(TypeError):

        class TestSchema(pw.Schema):
            a: int = pw.column_definition(dtype=str)


def test_schema_column_definition_error():
    with pytest.raises(ValueError):

        class TestSchema(pw.Schema):
            a: int = 1


def test_schema_no_annotation():
    with pytest.raises(
        ValueError, match=r"definitions of columns a, c lack type annotation.*"
    ):

        class TestSchema(pw.Schema):
            a = pw.column_definition()
            b: int = pw.column_definition()
            c = pw.column_definition()


def test_schema_override_column_name():
    class A(pw.Schema):
        a: int = pw.column_definition(name="@timestamp")
        b: int

    assert "@timestamp" in A.keys()
    assert "b" in A.keys()


def test_schema_builder():
    schema = pw.schema_builder(
        columns={
            "a": pw.column_definition(dtype=int, name="aa"),
            "b": pw.column_definition(dtype=str, default_value="default"),
            "c": pw.column_definition(),
        },
        name="FooSchema",
        properties=pw.SchemaProperties(append_only=True),
    )

    class FooSchema(pw.Schema, append_only=True):
        a: int = pw.column_definition(dtype=int, name="aa")
        b: str = pw.column_definition(dtype=str, default_value="default")
        c: Any

    assert_same_schema(schema, FooSchema)


def test_schema_eq():
    class A(pw.Schema):
        a: int = pw.column_definition(primary_key=True)
        b: str = pw.column_definition(default_value="foo")

    class B(pw.Schema):
        b: str = pw.column_definition(default_value="foo")
        a: int = pw.column_definition(primary_key=True)

    class C(pw.Schema):
        a: int = pw.column_definition(primary_key=True)
        b: str = pw.column_definition(default_value="foo")
        c: int

    class D(pw.Schema):
        a: int = pw.column_definition()
        b: str = pw.column_definition(default_value="foo")

    class E(pw.Schema):
        a: str = pw.column_definition(primary_key=True)
        b: str = pw.column_definition(default_value="foo")

    class F(pw.Schema, append_only=True):
        a: int = pw.column_definition(primary_key=True)
        b: str = pw.column_definition(default_value="foo")

    class Same(pw.Schema):
        a: int = pw.column_definition(primary_key=True)
        b: str = pw.column_definition(default_value="foo")

    schema_from_builder = pw.schema_builder(
        columns={
            "a": pw.column_definition(primary_key=True, dtype=int),
            "b": pw.column_definition(default_value="foo", dtype=str),
        },
        name="Foo",
    )
    compat_schema = _compat_schema(
        value_columns=["a", "b"],
        primary_key=["a"],
        default_values={"b": "foo"},
        types={
            "a": pw.Type.INT,
            "b": pw.Type.STRING,
        },
    )

    assert A != B, "column order should match"
    assert A != C, "column count should match"
    assert A != D, "column properties should match"
    assert A != E, "column types should match"
    assert A != F, "schema properties should match"
    assert A == Same
    assert A == schema_from_builder
    assert A == compat_schema


def test_schema_class_generation(tmp_path: pathlib.Path):
    schema_from_builder = pw.schema_builder(
        columns={
            "a": pw.column_definition(primary_key=True, dtype=int),
            "b": pw.column_definition(default_value="foo", dtype=str),
            "c": pw.column_definition(dtype=Any),
            "d": pw.column_definition(default_value=5, dtype=int),
            "e": pw.column_definition(dtype=float),
            "f": pw.column_definition(dtype=tuple[int, Any]),
            "g": pw.column_definition(dtype=pw.DateTimeUtc),
            "h": pw.column_definition(dtype=tuple[int, ...]),
        },
        name="Foo",
    )

    path = tmp_path / "foo.py"

    module_name = "pathway_schema_test"

    try:
        schema_from_builder.generate_class_to_file(path, generate_imports=True)
        spec = importlib.util.spec_from_file_location(module_name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        assert_same_schema(schema_from_builder, module.Foo)
    finally:
        del sys.modules[module_name]


def test_schema_from_dict():
    schema_definition = {
        "col1": Any,
        "col2": {"dtype": "int", "default_value": 5},
        "col3": {"dtype": str, "default_value": "foo", "primary_key": True},
        "col4": "typing.Any",
    }
    schema_properties = {"append_only": True}
    schema = pw.schema_from_dict(
        schema_definition, name="Schema", properties=schema_properties
    )

    expected = pw.schema_builder(
        {
            "col1": pw.column_definition(dtype=Any),
            "col2": pw.column_definition(dtype=int, default_value=5),
            "col3": pw.column_definition(
                dtype=str, default_value="foo", primary_key=True
            ),
            "col4": pw.column_definition(dtype=Any),
        },
        name="Schema",
        properties=pw.SchemaProperties(append_only=True),
    )

    assert_same_schema(schema, expected)


def test_schema_from_csv(tmp_path: pathlib.Path):
    filename = str(tmp_path / "dataset.csv")

    write_csv(
        filename,
        """
        ID   | value    | time          | diff
        "a"  | "worrld" | 1692262484324 | 1
        #"b" | "worrld" | 1692262510368 | 1.1
        "c"  | "worrld" | 1692262510368 | 1
        """,
        quoting=csv.QUOTE_NONE,
        float_format="%g",
        index=False,
    )

    schema1 = pw.schema_from_csv(filename, name="schema1")
    expected1 = pw.schema_from_types(
        _name="schema1", ID=str, value=str, time=int, diff=float
    )
    assert_same_schema(schema1, expected1)

    # When only one row is to be parsed, the last column has type int
    schema2 = pw.schema_from_csv(filename, name="schema2", num_parsed_rows=1)
    expected2 = pw.schema_from_types(
        _name="schema2", ID=str, value=str, time=int, diff=int
    )
    assert_same_schema(schema2, expected2)

    # Skips commented row, so last column has type int
    schema3 = pw.schema_from_csv(filename, name="schema3", comment_character="#")
    expected3 = pw.schema_from_types(
        _name="schema3", ID=str, value=str, time=int, diff=int
    )
    assert_same_schema(schema3, expected3)

    # When no rows are parsed, all types are Any
    schema4 = pw.schema_from_csv(filename, name="schema4", num_parsed_rows=0)
    expected4 = pw.schema_from_types(
        _name="schema4", ID=Any, value=Any, time=Any, diff=Any
    )
    assert_same_schema(schema4, expected4)

    # Changing delimiter yields only one column
    schema5 = pw.schema_from_csv(filename, name="schema5", delimiter="]")
    expected5 = pw.schema_builder(
        {"ID,value,time,diff": pw.column_definition(dtype=str)}, name="schema5"
    )
    assert_same_schema(schema5, expected5)

    write_csv(
        filename,
        """
        ID   | "va""l""ue"
        "1"  | "worrld"
        "3"  | "worrld"
        """,
        quoting=csv.QUOTE_NONE,
        float_format="%g",
        index=False,
    )

    schema6 = pw.schema_from_csv(filename, name="schema6")
    expected6 = pw.schema_builder(
        {
            "ID": pw.column_definition(dtype=int),
            'va"l"ue': pw.column_definition(dtype=str),
        },
        name="schema6",
    )
    assert_same_schema(schema6, expected6)

    schema7 = pw.schema_from_csv(filename, name="schema7", quote="'")
    expected7 = pw.schema_builder(
        {
            "ID": pw.column_definition(dtype=str),
            '"va""l""ue"': pw.column_definition(dtype=str),
        },
        name="schema7",
    )
    assert_same_schema(schema7, expected7)

    schema8 = pw.schema_from_csv(filename, name="schema8", double_quote_escapes=False)
    expected8 = pw.schema_builder(
        {
            "ID": pw.column_definition(dtype=int),
            'va"l""ue"': pw.column_definition(dtype=str),
        },
        name="schema8",
    )
    assert_same_schema(schema8, expected8)


def test_schema_canonical_json():
    class A(pw.Schema):
        a: dict
        b: pw.Json

    assert A.typehints() == {"a": pw.Json, "b": pw.Json}


def test_schema_ambiguous_property():
    with pytest.raises(
        ValueError,
        match="ambiguous property; schema property `append_only`"
        + " has value True but column `a` got False",
    ):

        class A(pw.Schema, append_only=True):
            a: int = pw.column_definition(append_only=False)

    with pytest.raises(
        ValueError,
        match="ambiguous property; schema property `append_only`"
        + " has value False but column `a` got True",
    ):

        class B(pw.Schema, append_only=False):
            a: int = pw.column_definition(append_only=True)


def test_schema_properties():
    class A(pw.Schema, append_only=True):
        a: int = pw.column_definition(append_only=True)
        b: int = pw.column_definition()

    assert A["a"].append_only is True
    assert A["b"].append_only is True
    assert A.universe_properties.append_only is True

    class B(pw.Schema, append_only=False):
        a: int = pw.column_definition(append_only=False)
        b: int = pw.column_definition()

    assert B["a"].append_only is False
    assert B["b"].append_only is False
    assert B.universe_properties.append_only is False

    class C(pw.Schema):
        a: int = pw.column_definition(append_only=True)
        b: int = pw.column_definition(append_only=False)
        c: int = pw.column_definition()

    assert C["a"].append_only is True
    assert C["b"].append_only is False
    assert C["c"].append_only is False
    assert C.universe_properties.append_only is True

    class D(pw.Schema, append_only=True):
        pass

    assert D.universe_properties.append_only is True


def test_schemas_not_to_be_called():
    with pytest.raises(TypeError):
        pw.Table.empty().schema()


def test_advanced_schemas_not_to_be_called():
    with pytest.raises(TypeError):
        (pw.Table.empty().schema | pw.Table.empty().schema)()
