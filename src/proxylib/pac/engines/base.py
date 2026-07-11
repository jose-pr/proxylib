"""Common interface a PAC JS execution engine must implement.

:mod:`proxylib.pac.javascript`'s ``JSContext`` is written against this
protocol, not any specific engine -- ``dukpy.py``/``quickjs.py`` each wrap a
concrete engine behind it.
"""

from __future__ import annotations

from typing import Any, Callable, Protocol, runtime_checkable

__all__ = ("JSEngine",)


@runtime_checkable
class JSEngine(Protocol):
    """One JS execution context."""

    def export_function(self, name: str, func: "Callable[..., Any]") -> None:
        """Make ``func`` callable from JS as the global function ``name``."""
        ...

    def eval(self, code: str) -> Any:
        """Evaluate a script (used once, to load the PAC source)."""
        ...

    def call(self, name: str, *args: Any) -> Any:
        """Call the JS global function ``name`` with ``args``.

        Must resolve ``name`` fresh in the engine's global scope on every
        call, not once at bind time -- this is what implements "a PAC
        script that redefines an exported name overrides it": the name is
        looked up again after the script has had a chance to reassign it.
        """
        ...
