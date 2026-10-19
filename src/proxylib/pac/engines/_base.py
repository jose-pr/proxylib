"""The interface a PAC JavaScript engine implements.

:class:`~proxylib.pac.PacScript` is written against this protocol; the
``_dukpy`` and ``_quickjs`` modules wrap the two supported engines behind it.
"""

from __future__ import annotations

from typing import Any, Callable, Protocol, runtime_checkable

__all__ = ("JSEngine",)


@runtime_checkable
class JSEngine(Protocol):
    """One JavaScript execution context. Not thread-safe: ``PacScript`` calls
    it from a single thread."""

    def export_function(self, name: str, func: "Callable[..., Any]") -> None:
        """Make ``func`` callable from JS as the global function ``name``."""
        ...

    def eval(self, code: str) -> Any:
        """Evaluate a script (the PAC source, once)."""
        ...

    def call(self, name: str, *args: Any) -> Any:
        """Call the JS global function ``name`` with ``args``.

        ``name`` is resolved in the global scope on every call, so a script
        that redefines an exported function overrides it.
        """
        ...

    def set_memory_limit(self, limit: int) -> None:
        """Cap the context's memory at ``limit`` bytes where the engine
        supports it; an engine without one ignores the call. (Time is bounded
        from outside: the script runs in a helper process.)"""
        ...
