"""GNOME desktop proxy detection via gsettings (``org.gnome.system.proxy``)."""

from __future__ import annotations

from typing import Optional, Union

from ...proxy import ProxyMap
from ._gsettings import read_desktop_proxy

__all__ = ("detect",)


def detect() -> "Optional[Union[ProxyMap, str]]":
    return read_desktop_proxy("org.gnome.system.proxy")
