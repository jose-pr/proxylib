"""``dukpy``-backed :class:`~proxylib.pac.engines.base.JSEngine` (the ``proxylib[jspac]`` extra)."""

from __future__ import annotations

from typing import Any, Callable

__all__ = ("DukpyEngine", "available")

try:
    from dukpy import JSInterpreter as _JSInterpreter

    class DukpyEngine:
        def __init__(self) -> None:
            self._interp = _JSInterpreter()

        def export_function(self, name: str, func: "Callable[..., Any]") -> None:
            self._interp.export_function(name, func)
            # export_function only wires up the shared `call_python` bridge;
            # give `name` its own top-level JS function so both a PAC script
            # and our own call() can invoke it by name, and so a script that
            # redefines `name` simply shadows this stub (JS-level
            # reassignment) rather than erroring.
            stub = (
                f"function {name}(){{ return call_python.apply(null, "
                f"['{name}'].concat(Array.prototype.slice.call(arguments))); }}"
            )
            self._interp.evaljs(stub)

        def eval(self, code: str) -> Any:
            return self._interp.evaljs(code)

        def call(self, name: str, *args: Any) -> Any:
            return self._interp.evaljs(f"{name}.apply(null, dukpy.args)", args=list(args))

    available = True
except ImportError:
    DukpyEngine = None  # type: ignore[assignment,misc]
    available = False
