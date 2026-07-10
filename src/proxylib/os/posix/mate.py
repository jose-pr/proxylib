"""MATE desktop proxy detection via gsettings (``org.mate.system.proxy``).

MATE's schema is a near-verbatim fork of GNOME's (same key names), inherited
from their shared GNOME 2 ancestry.
"""

from __future__ import annotations

from ...proxy import ProxyMap
from ._gsettings import read_desktop_proxy

__all__ = ("detect",)


def detect() -> "ProxyMap|str|None":
    return read_desktop_proxy("org.mate.system.proxy")
