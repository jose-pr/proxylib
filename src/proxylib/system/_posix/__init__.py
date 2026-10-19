"""Linux and other POSIX desktops: GNOME, MATE, KDE, then NetworkManager.

There is no session detection, and a machine often carries another
desktop's defaults (GNOME's ``mode='none'`` under KDE), so the first source
with a proxy configured wins; when none has one, the first that has settings
answers. Other desktops are reached through libproxy or the environment
variables.
"""

from __future__ import annotations

from typing import Optional

from .._config import ProxyConfig
from . import _gsettings, _kde, _networkmanager

__all__ = ("read_config",)


def _readers():
    # Looked up on every call so tests can replace a backend's read_config.
    yield lambda: _gsettings.read_config("org.gnome.system.proxy", "gnome")
    yield lambda: _gsettings.read_config("org.mate.system.proxy", "mate")
    yield _kde.read_config
    yield _networkmanager.read_config


def read_config() -> "Optional[ProxyConfig]":
    first: "Optional[ProxyConfig]" = None
    for reader in _readers():
        config = reader()
        if config is None:
            continue
        if config.state == "configured":
            return config
        first = first or config
    return first
