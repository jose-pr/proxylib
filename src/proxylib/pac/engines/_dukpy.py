"""``dukpy`` engine (the ``proxylib[dukpy]`` extra). It has no memory limit."""

from __future__ import annotations

from typing import Any, Callable

__all__ = ("DukpyEngine",)


class DukpyEngine:
    name = "dukpy"

    def __init__(self) -> None:
        from dukpy import JSInterpreter

        self._interp = JSInterpreter()

    def export_function(self, name: str, func: "Callable[..., Any]") -> None:
        self._interp.export_function(name, func)
        # export_function only wires up dukpy's shared call_python bridge;
        # a global function per name lets the script call it, and lets the
        # script redefine it like any other global.
        stub = (
            f"function {name}(){{ return call_python.apply(null, "
            f"['{name}'].concat(Array.prototype.slice.call(arguments))); }}"
        )
        self._interp.evaljs(stub)

    def eval(self, code: str) -> Any:
        return self._interp.evaljs(code)

    def call(self, name: str, *args: Any) -> Any:
        return self._interp.evaljs(f"{name}.apply(null, dukpy.args)", args=list(args))

    def set_memory_limit(self, limit: int) -> None:
        pass
