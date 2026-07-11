"""``quickjs``-backed :class:`~proxylib.pac.engines.base.JSEngine` (the ``proxylib[quickjs]`` extra).

Unlike dukpy, ``quickjs.Context.add_callable(name, func)`` registers ``func``
directly as a named global (no bridge-function indirection needed).
``Context.get(name)``/``eval(name)`` return a handle bound to whichever
function object existed *at that moment* -- they do **not** dynamically
re-resolve ``name`` later -- so :meth:`QuickJSEngine.call` deliberately
re-evaluates ``name`` on every call rather than caching the handle, or a
PAC script's redefinition of an exported name would never be seen.
"""

from __future__ import annotations

from typing import Any, Callable

__all__ = ("QuickJSEngine", "available")

try:
    import quickjs as _quickjs

    class QuickJSEngine:
        def __init__(self) -> None:
            self._ctx = _quickjs.Context()

        def export_function(self, name: str, func: "Callable[..., Any]") -> None:
            self._ctx.add_callable(name, func)

        def eval(self, code: str) -> Any:
            return self._ctx.eval(code)

        def call(self, name: str, *args: Any) -> Any:
            fn = self._ctx.eval(name)
            return fn(*args)

    available = True
except ImportError:
    QuickJSEngine = None  # type: ignore[assignment,misc]
    available = False
