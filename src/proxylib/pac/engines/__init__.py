"""PAC JavaScript engines.

Two are supported: ``quickjs`` (``proxylib[pac]``; closer to the spec, has
time and memory limits) and ``dukpy`` (``proxylib[dukpy]``; a wheel exists
where quickjs has none, such as Windows ARM64). Neither is imported until a
script needs it.

Which one runs: the ``engine=`` argument, else the ``PROXYLIB_JS_ENGINE``
environment variable (a comma-separated priority list such as
``"dukpy,quickjs"``), else quickjs, then dukpy. An unknown name is a
``ValueError``.
"""

from __future__ import annotations

import importlib.util
import os
from typing import Dict, List, Optional, Tuple, Type

from ._base import JSEngine

__all__ = ("JSEngine", "names", "get_engine")

# name -> (module that must be importable, "module:class" of the wrapper)
_ENGINES: "Dict[str, Tuple[str, str]]" = {
    "quickjs": ("quickjs", "._quickjs:QuickJSEngine"),
    "dukpy": ("dukpy", "._dukpy:DukpyEngine"),
}
_DEFAULT_PRIORITY = ("quickjs", "dukpy")


def _installed(name: str) -> bool:
    return importlib.util.find_spec(_ENGINES[name][0]) is not None


def names() -> "Tuple[str, ...]":
    """The engines installed here, in default priority order."""
    return tuple(name for name in _DEFAULT_PRIORITY if _installed(name))


def _load(name: str) -> "Type[JSEngine]":
    module, _, cls = _ENGINES[name][1].partition(":")
    return getattr(importlib.import_module(module, __name__), cls)


def _priority(engine: "Optional[str]") -> "List[str]":
    if engine:
        wanted = [engine]
    else:
        env = os.environ.get("PROXYLIB_JS_ENGINE", "")
        wanted = [n.strip() for n in env.split(",") if n.strip()] or list(_DEFAULT_PRIORITY)
    unknown = [n for n in wanted if n not in _ENGINES]
    if unknown:
        raise ValueError(f"unknown PAC engine {unknown[0]!r}; expected one of {tuple(_ENGINES)}")
    return wanted


def get_engine(engine: "Optional[str]" = None) -> "Optional[Type[JSEngine]]":
    """The engine class to use, or ``None`` when none of the wanted engines
    is installed."""
    for name in _priority(engine):
        if _installed(name):
            return _load(name)
    return None
