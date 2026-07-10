"""Platform-agnostic system proxy detection.

Dispatches to a per-OS backend (:mod:`.nt` on Windows, :mod:`.darwin` on
macOS, :mod:`.posix` elsewhere) and, via :func:`auto_proxy`, falls back to
WPAD discovery (:mod:`proxylib.pac.wpad`) when the OS/env has no explicit
proxy configured.
"""

from __future__ import annotations

import sys

from ..pac import load as load_pac
from ..proxy import ProxyMap, SimpleProxyMap

__all__ = ("system_proxy", "auto_proxy")

if sys.platform == "win32":
    from .nt import system_proxy
elif sys.platform == "darwin":
    from .darwin import system_proxy
else:
    from .posix import system_proxy


def auto_proxy(**urlopen_kwargs) -> ProxyMap:
    """Resolve the effective ``ProxyMap`` for this machine.

    Order: OS-native settings / env vars (:func:`system_proxy`) → if that
    yields a PAC URL, load it → if it yields no usable config at all, try
    WPAD discovery → otherwise DIRECT.
    """
    proxy = system_proxy()
    if isinstance(proxy, str):
        return load_pac(proxy, **urlopen_kwargs)
    if isinstance(proxy, SimpleProxyMap) and proxy[""] == (None,):
        from ..pac.wpad import discover

        discovered = discover(**urlopen_kwargs)
        if discovered is not None:
            return discovered
    return proxy
