# Copyright © 2024 Pathway

from __future__ import annotations

import asyncio
import os
import pathlib
import re
import sys
import threading
import warnings
from typing import Optional
from unittest import mock

import pytest

import pathway as pw
from pathway.internals import api
from pathway.tests.utils import (
    T,
    assert_stream_equality,
    assert_table_equality,
    deprecated_call_here,
    run_all,
    warns_here,
    xfail_on_multiple_threads,
)


def test_udf():
    @pw.udf
    def inc(a: int) -> int:
        return a + 1

    input = pw.debug.table_from_markdown(
        """
        a
        1
        2
        3
        """
    )

    result = input.select(ret=inc(pw.this.a))

    assert_table_equality(
        result,
        T(
            """
            ret
            2
            3
            4
            """,
        ),
    )


def test_udf_class_deprecated():
    with deprecated_call_here(
        match=re.escape(
            "UDFSync is deprecated, use UDF with executor=pw.udfs.sync_executor() instead."
        )
    ):

        class Inc(pw.UDFSync):
            def __init__(self, inc) -> None:
                super().__init__()
                self.inc = inc

            def __wrapped__(self, a: int) -> int:
                return a + self.inc

    input = pw.debug.table_from_markdown(
        """
        a
        1
        2
        3
        """
    )

    inc = Inc(2)
    result = input.select(ret=inc(pw.this.a))

    assert_table_equality(
        result,
        T(
            """
            ret
            3
            4
            5
            """,
        ),
    )


def test_udf_class():
    class Inc(pw.UDF):
        def __init__(self, inc) -> None:
            super().__init__()
            self.inc = inc

        def __wrapped__(self, a: int) -> int:
            return a + self.inc

    input = pw.debug.table_from_markdown(
        """
        a
        1
        2
        3
        """
    )

    inc = Inc(2)
    result = input.select(ret=inc(pw.this.a))

    assert_table_equality(
        result,
        T(
            """
            ret
            3
            4
            5
            """,
        ),
    )


def test_udf_async_options_deprecated(tmp_path: pathlib.Path):
    cache_dir = tmp_path / "test_cache"

    counter = mock.Mock()

    with deprecated_call_here():

        @pw.udf_async(cache_strategy=pw.udfs.DiskCache())
        async def inc(x: int) -> int:
            counter()
            return x + 5

    input = T(
        """
        foo
        1
        2
        3
        """
    )
    result = input.select(ret=inc(pw.this.foo))
    expected = T(
        """
        ret
        6
        7
        8
        """
    )

    # run twice to check if cache is used
    assert_table_equality(
        result,
        expected,
        persistence_config=pw.persistence.Config.simple_config(
            pw.persistence.Backend.filesystem(cache_dir),
        ),
    )
    assert_table_equality(
        result,
        expected,
        persistence_config=pw.persistence.Config.simple_config(
            pw.persistence.Backend.filesystem(cache_dir),
        ),
    )
    assert os.path.exists(cache_dir)
    assert counter.call_count == 3


def test_udf_async_options(tmp_path: pathlib.Path):
    cache_dir = tmp_path / "test_cache"

    counter = mock.Mock()

    @pw.udf(cache_strategy=pw.udfs.DiskCache())
    async def inc(x: int) -> int:
        counter()
        return x + 5

    input = T(
        """
        foo
        1
        2
        3
        """
    )
    result = input.select(ret=inc(pw.this.foo))
    expected = T(
        """
        ret
        6
        7
        8
        """
    )

    # run twice to check if cache is used
    assert_table_equality(
        result,
        expected,
        persistence_config=pw.persistence.Config.simple_config(
            pw.persistence.Backend.filesystem(cache_dir),
        ),
    )
    assert_table_equality(
        result,
        expected,
        persistence_config=pw.persistence.Config.simple_config(
            pw.persistence.Backend.filesystem(cache_dir),
        ),
    )
    assert os.path.exists(cache_dir)
    assert counter.call_count == 3


def test_udf_async_deprecated():
    with deprecated_call_here():

        @pw.udf_async
        async def inc(a: int) -> int:
            await asyncio.sleep(0.1)
            return a + 3

    input = pw.debug.table_from_markdown(
        """
        a
        1
        2
        3
        """
    )

    result = input.select(ret=inc(pw.this.a))

    assert_table_equality(
        result,
        T(
            """
            ret
            4
            5
            6
            """,
        ),
    )


@pytest.mark.skipif(sys.version_info < (3, 11), reason="test requires asyncio.Barrier")
def test_udf_async():
    barrier = asyncio.Barrier(3)  # type: ignore[attr-defined]
    # mypy complains because of versions lower than 3.11

    @pw.udf
    async def inc(a: int) -> int:
        await barrier.wait()
        return a + 3

    input = pw.debug.table_from_markdown(
        """
        a
        1
        2
        3
        """
    )

    result = input.select(ret=inc(pw.this.a))

    assert_table_equality(
        result,
        T(
            """
            ret
            4
            5
            6
            """,
        ),
    )


def test_udf_sync():
    barrier = threading.Barrier(3, timeout=1)

    @pw.udf
    def inc(a: int) -> int:
        barrier.wait()
        return a + 3

    input = pw.debug.table_from_markdown(
        """
        a
        1
        2
        3
        """
    )

    input.select(ret=inc(pw.this.a))

    with pytest.raises(threading.BrokenBarrierError):
        run_all()


def test_udf_sync_with_async_executor():
    barrier = threading.Barrier(3, timeout=10)

    @pw.udf(executor=pw.udfs.async_executor())
    def inc(a: int) -> int:
        barrier.wait()
        return a + 3

    input = pw.debug.table_from_markdown(
        """
        a
        1
        2
        3
        """
    )

    result = input.select(ret=inc(pw.this.a))

    assert_table_equality(
        result,
        T(
            """
            ret
            4
            5
            6
            """,
        ),
    )


def test_udf_async_class_deprecated():
    with deprecated_call_here(
        match=re.escape(
            "UDFAsync is deprecated, use UDF with executor=pw.udfs.async_executor() instead."
        )
    ):

        class Inc(pw.UDFAsync):
            def __init__(self, inc, **kwargs) -> None:
                super().__init__(**kwargs)
                self.inc = inc

            async def __wrapped__(self, a: int) -> int:
                await asyncio.sleep(0.1)
                return a + self.inc

    input = pw.debug.table_from_markdown(
        """
        a
        1
        2
        3
        """
    )

    inc = Inc(40)
    result = input.select(ret=inc(pw.this.a))

    assert_table_equality(
        result,
        T(
            """
            ret
            41
            42
            43
            """,
        ),
    )


def test_udf_async_class():
    class Inc(pw.UDF):
        def __init__(self, inc, **kwargs) -> None:
            super().__init__(**kwargs)
            self.inc = inc

        async def __wrapped__(self, a: int) -> int:
            await asyncio.sleep(0.1)
            return a + self.inc

    input = pw.debug.table_from_markdown(
        """
        a
        1
        2
        3
        """
    )

    inc = Inc(40)
    result = input.select(ret=inc(pw.this.a))

    assert_table_equality(
        result,
        T(
            """
            ret
            41
            42
            43
            """,
        ),
    )


def test_udf_propagate_none():
    internal_add = mock.Mock()

    @pw.udf(propagate_none=True)
    def add(a: int, b: int) -> int:
        assert a is not None
        assert b is not None
        internal_add()
        return a + b

    input = T(
        """
        a | b
        1 | 6
        2 |
          | 8
        """
    )

    result = input.select(ret=add(pw.this.a, pw.this.b))

    assert_table_equality(
        result,
        T(
            """
            ret
            7
            None
            None
            """,
        ),
    )
    internal_add.assert_called_once()


@pytest.mark.parametrize("sync", [True, False])
def test_udf_make_deterministic(sync: bool) -> None:
    internal_inc = mock.Mock()

    if sync:

        @pw.udf
        def inc(a: int) -> int:
            internal_inc(a)
            return a + 1

    else:

        @pw.udf
        async def inc(a: int) -> int:
            await asyncio.sleep(a / 10)
            internal_inc(a)
            return a + 1

    input = T(
        """
          | a | __time__ | __diff__
        1 | 1 |     2    |     1
        2 | 2 |     2    |     1
        2 | 2 |     4    |    -1
        3 | 3 |     6    |     1
        4 | 1 |     8    |     1
        3 | 3 |     8    |    -1
        3 | 4 |     8    |     1
        """
    )

    result = input.select(ret=inc(pw.this.a))

    assert_table_equality(
        result,
        T(
            """
              | ret
            1 | 2
            3 | 5
            4 | 2
            """,
        ),
    )
    internal_inc.assert_has_calls(
        [mock.call(1), mock.call(2), mock.call(3), mock.call(1), mock.call(4)],
        any_order=True,
    )
    assert internal_inc.call_count == 5


@pytest.mark.parametrize("sync", [True, False])
def test_udf_make_deterministic_2(sync: bool) -> None:
    counter = mock.Mock()
    if sync:

        @pw.udf
        def foo(a: int) -> int:
            counter(a)
            return a

    else:

        @pw.udf
        async def foo(a: int) -> int:
            await asyncio.sleep(a / 10)
            counter(a)
            return a

    input = T(
        """
        a | __time__ | __diff__
        1 |     2    |     1
        1 |     4    |    -1
        1 |     6    |     1
        1 |     8    |    -1
        1 |    10    |     1
    """,
        id_from=["a"],
    )

    res = input.select(a=foo(pw.this.a))

    assert_stream_equality(
        res,
        T(
            """
            a | __time__ | __diff__
            1 |     2    |     1
            1 |     4    |    -1
            1 |     6    |     1
            1 |     8    |    -1
            1 |    10    |     1
        """,
            id_from=["a"],
        ),
    )
    counter.assert_has_calls(
        [mock.call(1), mock.call(1), mock.call(1)],
        any_order=True,
    )
    assert counter.call_count == 3


@xfail_on_multiple_threads
def test_udf_cache(monkeypatch, tmp_path: pathlib.Path):
    monkeypatch.delenv("PATHWAY_PERSISTENT_STORAGE", raising=False)
    internal_inc = mock.Mock()

    @pw.udf(deterministic=True, cache_strategy=pw.udfs.DiskCache())
    def inc(a: int) -> int:
        internal_inc(a)
        return a + 1

    input = T(
        """
        a
        1
        2
        2
        3
        1
        """
    )

    result = input.select(ret=inc(pw.this.a))

    pstorage_dir = tmp_path / "PStorage"
    persistence_config = pw.persistence.Config.simple_config(
        backend=pw.persistence.Backend.filesystem(pstorage_dir),
        persistence_mode=api.PersistenceMode.UDF_CACHING,
    )
    assert_table_equality(
        result,
        T(
            """
            ret
            2
            3
            3
            4
            2
            """,
        ),
        persistence_config=persistence_config,
    )
    internal_inc.assert_has_calls(
        [mock.call(1), mock.call(2), mock.call(3)], any_order=True
    )
    assert internal_inc.call_count == 3


@pytest.mark.parametrize("sync", [True, False])
def test_udf_deterministic_not_stored(monkeypatch, tmp_path: pathlib.Path, sync):
    monkeypatch.delenv("PATHWAY_PERSISTENT_STORAGE", raising=False)
    internal_inc = mock.Mock()

    if sync:

        @pw.udf(deterministic=True)
        def inc(a: int) -> int:
            internal_inc(a)
            return a + 1

    else:

        @pw.udf(deterministic=True)
        async def inc(a: int) -> int:
            await asyncio.sleep(a / 10)
            internal_inc(a)
            return a + 1

    input = T(
        """
        a
        1
        2
        2
        3
        1
        """
    )

    result = input.select(ret=inc(pw.this.a))

    pstorage_dir = tmp_path / "PStorage"
    persistence_config = pw.persistence.Config.simple_config(
        backend=pw.persistence.Backend.filesystem(pstorage_dir),
        persistence_mode=api.PersistenceMode.UDF_CACHING,
    )
    assert_table_equality(
        result,
        T(
            """
            ret
            2
            3
            3
            4
            2
            """,
        ),
        persistence_config=persistence_config,
    )
    internal_inc.assert_has_calls(
        [mock.call(1), mock.call(2), mock.call(3), mock.call(2), mock.call(1)],
        any_order=True,
    )
    assert internal_inc.call_count == 5


def test_async_udf_propagate_none():
    internal_add = mock.Mock()

    @pw.udf(propagate_none=True)
    async def add(a: int, b: int) -> int:
        assert a is not None
        assert b is not None
        internal_add()
        return a + b

    input = T(
        """
        a | b
        1 | 6
        2 |
          | 8
        """
    )

    result = input.select(ret=add(pw.this.a, pw.this.b))

    assert_table_equality(
        result,
        T(
            """
            ret
            7
            None
            None
            """,
        ),
    )
    internal_add.assert_called_once()


def test_async_udf_with_none():
    internal_add = mock.Mock()

    @pw.udf()
    async def add(a: int, b: int) -> int:
        internal_add()
        if a is None:
            return b
        if b is None:
            return a
        return a + b

    input = T(
        """
        a | b
        1 | 6
        2 |
          | 8
        """
    )

    result = input.select(ret=add(pw.this.a, pw.this.b))

    assert_table_equality(
        result,
        T(
            """
            ret
            7
            2
            8
            """,
        ),
    )
    assert internal_add.call_count == 3


def test_udf_timeout():
    @pw.udf(executor=pw.udfs.async_executor(timeout=0.1))
    async def inc(a: int) -> int:
        await asyncio.sleep(2)
        return a + 1

    input = pw.debug.table_from_markdown(
        """
        a
        1
        """
    )

    input.select(ret=inc(pw.this.a))
    expected: type[Exception]
    if sys.version_info < (3, 11):
        expected = asyncio.exceptions.TimeoutError
    else:
        expected = TimeoutError
    with pytest.raises(expected):
        run_all()


def test_udf_too_fast_for_timeout():
    @pw.udf(executor=pw.udfs.async_executor(timeout=10.0))
    async def inc(a: int) -> int:
        return a + 1

    input = pw.debug.table_from_markdown(
        """
        a
        1
        2
        3
        """
    )

    result = input.select(ret=inc(pw.this.a))
    assert_table_equality(
        result,
        T(
            """
            ret
            2
            3
            4
            """,
        ),
    )


def test_asynchronous_deprecation():
    message = re.escape(
        "pathway.asynchronous module is deprecated. Its content has been moved to pathway.udfs."
    )
    with deprecated_call_here(match=message):
        assert pw.asynchronous.AsyncRetryStrategy == pw.udfs.AsyncRetryStrategy

    with deprecated_call_here(match=message):
        assert pw.asynchronous.CacheStrategy == pw.udfs.CacheStrategy

    with deprecated_call_here(match=message):
        assert pw.asynchronous.DefaultCache == pw.udfs.DefaultCache

    with deprecated_call_here(match=message):
        assert (
            pw.asynchronous.ExponentialBackoffRetryStrategy
            == pw.udfs.ExponentialBackoffRetryStrategy
        )

    with deprecated_call_here(match=message):
        assert (
            pw.asynchronous.FixedDelayRetryStrategy == pw.udfs.FixedDelayRetryStrategy
        )

    with deprecated_call_here(match=message):
        assert pw.asynchronous.NoRetryStrategy == pw.udfs.NoRetryStrategy

    with deprecated_call_here(match=message):
        assert pw.asynchronous.async_options == pw.udfs.async_options

    with deprecated_call_here(match=message):
        assert pw.asynchronous.coerce_async == pw.udfs.coerce_async

    with deprecated_call_here(match=message):
        assert pw.asynchronous.with_cache_strategy == pw.udfs.with_cache_strategy

    with deprecated_call_here(match=message):
        assert pw.asynchronous.with_capacity == pw.udfs.with_capacity

    with deprecated_call_here(match=message):
        assert pw.asynchronous.with_retry_strategy == pw.udfs.with_retry_strategy


@pytest.mark.parametrize("sync", [True, False])
def test_udf_in_memory_cache(sync: bool) -> None:
    internal_inc = mock.Mock()

    if sync:

        @pw.udf(cache_strategy=pw.udfs.InMemoryCache())
        def inc(a: int) -> int:
            internal_inc(a)
            return a + 1

    else:

        @pw.udf(cache_strategy=pw.udfs.InMemoryCache())
        async def inc(a: int) -> int:
            await asyncio.sleep(a / 10)
            internal_inc(a)
            return a + 1

    input = pw.debug.table_from_markdown(
        """
        a
        1
        2
        1
        2
        3
    """
    )
    result = input.select(ret=inc(pw.this.a))
    expected = T(
        """
        ret
        2
        3
        2
        3
        4
        """
    )
    assert_table_equality(result, expected)
    internal_inc.assert_has_calls(
        [mock.call(1), mock.call(2), mock.call(3)], any_order=True
    )
    assert internal_inc.call_count == 3

    assert_table_equality(result, expected)
    assert internal_inc.call_count == 3  # count did not change


@pytest.mark.parametrize("sync", [True, False])
def test_udf_in_memory_cache_with_limit(sync: bool) -> None:
    internal_inc = mock.Mock()

    if sync:

        @pw.udf(cache_strategy=pw.udfs.InMemoryCache(max_size=0))
        def inc(a: int) -> int:
            internal_inc(a)
            return a + 1

    else:

        @pw.udf(cache_strategy=pw.udfs.InMemoryCache(max_size=0))
        async def inc(a: int) -> int:
            await asyncio.sleep(a / 10)
            internal_inc(a)
            return a + 1

    input = pw.debug.table_from_markdown(
        """
        a | __time__
        1 |     2
        1 |     4
        1 |     6
    """
    )
    result = input.select(ret=inc(pw.this.a))
    expected = T(
        """
        ret
        2
        2
        2
        """
    )
    assert_table_equality(result, expected)
    internal_inc.assert_has_calls([mock.call(1), mock.call(1), mock.call(1)])
    assert internal_inc.call_count == 3


@pytest.mark.parametrize("sync", [True, False])
def test_udf_in_memory_cache_multiple_places(sync: bool) -> None:
    internal_inc = mock.Mock()

    if sync:

        @pw.udf(cache_strategy=pw.udfs.InMemoryCache())
        def inc(a: int) -> int:
            internal_inc(a)
            return a + 1

    else:

        @pw.udf(cache_strategy=pw.udfs.InMemoryCache())
        async def inc(a: int) -> int:
            internal_inc(a)
            return a + 1

    input = pw.debug.table_from_markdown(
        """
        a
        1
        2
        1
        2
        3
    """
    )
    result = input.with_columns(ret=inc(pw.this.a))
    result = result.with_columns(ret_2=inc(pw.this.a))
    expected = T(
        """
        a | ret | ret_2
        1 |  2  |   2
        2 |  3  |   3
        1 |  2  |   2
        2 |  3  |   3
        3 |  4  |   4
        """
    )
    assert_table_equality(result, expected)
    internal_inc.assert_has_calls(
        [mock.call(1), mock.call(2), mock.call(3)], any_order=True
    )
    assert internal_inc.call_count == 3


def test_udf_warn_on_too_specific_return_type() -> None:
    @pw.udf(return_type=int)
    def f(a: int) -> Optional[int]:
        return a + 1

    msg = (
        "The value of return_type parameter (<class 'int'>) is inconsistent with UDF's"
        + " return type annotation (typing.Optional[int])."
    )
    with warns_here(Warning, match=re.escape(msg)):
        f(pw.this.a)


def test_udf_dont_warn_on_broader_return_type() -> None:
    @pw.udf(return_type=Optional[int])
    def f(a: int) -> int:
        return a + 1

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        f(pw.this.a)
