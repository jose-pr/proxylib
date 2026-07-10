"""Clearable cache around ``shutil.which``, shared by the gsettings and
NetworkManager backends.

A bare ``functools.lru_cache`` would poison tests that monkeypatch
``shutil.which`` per-test (each backend's own tests do this for ``gsettings``/
``nmcli``/``dbus-send``) -- ``clear_which_cache()`` is the seam tests use
instead. Calls the real ``shutil.which`` (not a copy of it), so patching
``shutil.which`` anywhere still takes effect the first time a given name is
looked up in a test.
"""

from __future__ import annotations

import shutil
from typing import Dict, Optional

_cache: "Dict[str, Optional[str]]" = {}


def which(name: str) -> "Optional[str]":
    if name not in _cache:
        _cache[name] = shutil.which(name)
    return _cache[name]


def clear_which_cache() -> None:
    _cache.clear()
