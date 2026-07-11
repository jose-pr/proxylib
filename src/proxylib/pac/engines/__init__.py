"""Pluggable PAC JS execution engines.

Select which one :class:`~proxylib.pac.javascript.JSContext` uses via the
``PROXYLIB_JS_ENGINE`` env var -- a **comma-separated** priority list (e.g.
``"dukpy,quickjs"``), one delimiter only. Each entry is tried in order;
the first one that's actually installed wins. Unset defaults to
``("quickjs", "dukpy")`` -- quickjs is the closer-to-spec/faster engine
when its (optional, C-extension) dependency happens to be installed;
``proxylib[jspac]`` still installs plain `dukpy` (pure-Python wheel, no C
toolchain risk) as the "any working engine" default, and dukpy remains the
runtime fallback when quickjs isn't present.
"""

from __future__ import annotations

import os
from typing import Dict, List, Optional, Type

from .base import JSEngine
from .dukpy import DukpyEngine
from .dukpy import available as _dukpy_available
from .quickjs import QuickJSEngine
from .quickjs import available as _quickjs_available

__all__ = ("JSEngine", "get_engine_class")

_ENGINES: "Dict[str, Optional[Type]]" = {
    "dukpy": DukpyEngine if _dukpy_available else None,
    "quickjs": QuickJSEngine if _quickjs_available else None,
}

_DEFAULT_PRIORITY = ("quickjs", "dukpy")


def _priority() -> "List[str]":
    env = os.environ.get("PROXYLIB_JS_ENGINE")
    if env:
        return [name.strip() for name in env.split(",") if name.strip()]
    return list(_DEFAULT_PRIORITY)


def get_engine_class() -> "Optional[Type]":
    """Return the highest-priority *installed* engine class, or ``None`` if
    none of the configured/default priority list is installed."""
    for name in _priority():
        cls = _ENGINES.get(name)
        if cls is not None:
            return cls
    return None
