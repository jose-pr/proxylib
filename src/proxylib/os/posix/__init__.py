"""Linux/other POSIX system proxy detection.

There is no single authoritative proxy config store on Linux; the portable
convention is environment variables. As a best-effort improvement,
:func:`system_proxy` also tries (in order): libproxy (:mod:`.libproxy`, if
its ``proxy`` CLI is installed -- generally the most authoritative single
source since it's itself a full cross-desktop resolution engine), GNOME
(:mod:`.gnome`), MATE (:mod:`.mate`), KDE (:mod:`.kde`), and NetworkManager
(:mod:`.networkmanager`) -- each only if its respective binary/file is
present, each degrading to "not configured" (not an error) otherwise. If
more than one of these has stale/leftover config on the same machine (e.g.
switched desktop environments), the first match in that order wins -- there
is no desktop-session detection (``XDG_CURRENT_DESKTOP``) to disambiguate.
Other desktop environments (Xfce, Cinnamon, ...) aren't covered directly
(though libproxy, if installed, may cover them) — set ``HTTP_PROXY``/
``HTTPS_PROXY``/``NO_PROXY`` or ``PROXY_PAC`` explicitly on those.
"""

from __future__ import annotations

import os

from ...env import EnvProxyConfig
from ...proxy import ProxyMap, SimpleProxyMap
from . import gnome, kde, libproxy, mate, networkmanager

__all__ = ("system_proxy",)

# Modules, not their .detect functions directly -- looking up `.detect` as an
# attribute at call time (not pre-binding it into a tuple at import time)
# means tests can monkeypatch e.g. `libproxy.detect` and have it take effect.
_DESKTOP_BACKENDS = (libproxy, gnome, mate, kde, networkmanager)


def system_proxy() -> "ProxyMap|str":
    """``PROXY_PAC``/``HTTP_PROXY``-family env vars, with best-effort desktop checks."""
    pac = os.environ.get("PROXY_PAC")
    if pac:
        return pac

    for backend in _DESKTOP_BACKENDS:
        result = backend.detect()
        if result is not None:
            return result

    has_env_proxy = any(
        os.environ.get(name)
        for name in ("HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy")
    )
    if has_env_proxy:
        return EnvProxyConfig.from_env()

    return SimpleProxyMap()
