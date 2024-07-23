# Copyright © 2024 Pathway

from __future__ import annotations

import asyncio
import functools
from collections.abc import Awaitable, Callable
from typing import ParamSpec, TypeVar

from pathway.internals.runtime_type_check import check_arg_types

T = TypeVar("T")
P = ParamSpec("P")


@check_arg_types
def coerce_async(
    func: Callable[P, T] | Callable[P, Awaitable[T]]
) -> Callable[P, Awaitable[T]]:
    """
    Wraps a regular function to be executed in async executor.
    It acts as a noop if the provided function is already a coroutine.
    """

    if asyncio.iscoroutinefunction(func):
        return func
    else:

        @functools.wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            event_loop = asyncio.get_event_loop()
            assert event_loop.is_running(), "event loop should be running"
            pfunc = functools.partial(func, *args, **kwargs)
            return await event_loop.run_in_executor(None, func=pfunc)  # type: ignore[arg-type]

        return wrapper
