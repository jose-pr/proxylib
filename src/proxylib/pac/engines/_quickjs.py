"""``quickjs`` engine (the ``proxylib[pac]`` extra: ``quickjs-ng`` on Python
3.10+, ``quickjs`` on 3.9).

``Context.get(name)`` binds to the function that exists at that moment, so
:meth:`QuickJSEngine.call` evaluates ``name`` on every call; otherwise a PAC
script's redefinition of an exported name would never be seen.
"""

from __future__ import annotations

from typing import Any, Callable

__all__ = ("QuickJSEngine",)


class QuickJSEngine:
    name = "quickjs"

    def __init__(self) -> None:
        import quickjs

        self._ctx = quickjs.Context()

    def export_function(self, name: str, func: "Callable[..., Any]") -> None:
        self._ctx.add_callable(name, func)

    def eval(self, code: str) -> Any:
        return self._ctx.eval(code)

    def call(self, name: str, *args: Any) -> Any:
        return self._ctx.eval(name)(*args)

    def set_memory_limit(self, limit: int) -> None:
        # quickjs's own time limit is not used: with one set, a script can no
        # longer call the Python PAC builtins.
        if hasattr(self._ctx, "set_memory_limit"):
            self._ctx.set_memory_limit(limit)
