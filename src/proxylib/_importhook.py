"""Call a function when a module is imported, or at once if it already is.

The same design as the ``importpatch`` package (which ``proxylib[patch]``
installs to do this in every interpreter): a ``sys.meta_path`` finder asks the
other finders for the module's spec and wraps its loader, so the callback runs
once the module's code has.
"""

from __future__ import annotations

import sys
import threading
from types import ModuleType
from typing import Callable, Dict, List

__all__ = ("when_imported",)

Callback = Callable[[str], None]

_callbacks: "Dict[str, List[Callback]]" = {}
_lock = threading.Lock()


def _notify(name: str) -> None:
    with _lock:
        callbacks = list(_callbacks.get(name, ()))
    for callback in callbacks:
        callback(name)


class _Loader:
    __slots__ = ("_loader",)

    def __init__(self, loader) -> None:
        self._loader = loader

    def __getattr__(self, name: str):
        return getattr(self._loader, name)

    def exec_module(self, module: ModuleType) -> None:
        self._loader.exec_module(module)
        # The import system binds a submodule on its package only after this
        # returns; a callback may reach the module as package.child.
        package, _, child = module.__name__.rpartition(".")
        if package in sys.modules:
            setattr(sys.modules[package], child, module)
        _notify(module.__name__)


class _Finder:
    def __init__(self) -> None:
        self._busy: "set[str]" = set()

    def find_spec(self, fullname: str, path=None, target=None):
        if fullname not in _callbacks or fullname in self._busy:
            return None
        self._busy.add(fullname)
        try:
            spec = None
            for finder in list(sys.meta_path):
                find_spec = getattr(finder, "find_spec", None)
                if finder is self or find_spec is None:
                    continue
                spec = find_spec(fullname, path, target)
                if spec is not None:
                    break
        finally:
            self._busy.discard(fullname)
        if spec is not None and hasattr(spec.loader, "exec_module"):
            spec.loader = _Loader(spec.loader)
        return spec


_finder = _Finder()


def when_imported(name: str, callback: Callback) -> None:
    """Call ``callback(name)`` once module ``name`` has been imported; at once
    when it already has been."""
    with _lock:
        callbacks = _callbacks.setdefault(name, [])
        if callback not in callbacks:
            callbacks.append(callback)
        if _finder not in sys.meta_path:
            sys.meta_path.insert(0, _finder)
    # A None entry blocks the import, and a module still initialising is not
    # imported yet (its loader runs without this hook, so the callback waits
    # for a later trigger).
    module = sys.modules.get(name)
    if module is not None and not getattr(getattr(module, "__spec__", None), "_initializing", False):
        callback(name)
