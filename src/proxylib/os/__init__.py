"""Platform-agnostic system proxy detection.

Dispatches to a per-OS backend (:mod:`.nt` on Windows, :mod:`.darwin` on
macOS, :mod:`.posix` elsewhere) and, via :func:`auto_proxy`, falls back to
WPAD discovery (:mod:`proxylib.pac.wpad`) when the OS/env has no explicit
proxy configured.

Both :func:`system_proxy` and :func:`auto_proxy` take a ``provider``:

- ``"python"`` (default): proxylib's own detection + PAC-via-``dukpy``
  path -- works everywhere, including sandboxes/testing.
- ``"system"``: outsources resolution to the OS's native proxy engine
  (``WinHttpProxyMap`` on Windows, ``CFNetworkProxyMap`` on macOS,
  ``LibProxyMap`` on POSIX if its shared library is loadable -- falls back
  to ``"python"`` there if not). These already do their own WPAD/PAC, so
  :func:`auto_proxy` doesn't run its own WPAD fallback on top of them.
"""

from __future__ import annotations

import sys
from typing import Optional

from ..pac import load as load_pac
from ..proxy import ProxyMap, SimpleProxyMap

__all__ = ("system_proxy", "auto_proxy")

if sys.platform == "win32":
    from .nt import system_proxy as _python_system_proxy
elif sys.platform == "darwin":
    from .darwin import system_proxy as _python_system_proxy
else:
    from .posix import system_proxy as _python_system_proxy


def _native_system_provider() -> "Optional[ProxyMap]":
    """Construct this platform's native ``provider="system"`` ``ProxyMap``,
    or ``None`` if it's not available here (e.g. libproxy's shared library
    isn't installed on this POSIX machine) -- caller falls through to
    ``"python"``."""
    if sys.platform == "win32":
        from .nt import WinHttpProxyMap

        return WinHttpProxyMap()
    if sys.platform == "darwin":
        from .darwin import CFNetworkProxyMap

        return CFNetworkProxyMap()
    from .posix.libproxy import LibProxyMap, _get_libproxy

    lib = _get_libproxy()
    return LibProxyMap(lib) if lib is not None else None


def system_proxy(provider: str = "python") -> "ProxyMap|str":
    """Read this machine's proxy configuration. See the module docstring
    for what ``provider`` means."""
    if provider == "system":
        native = _native_system_provider()
        if native is not None:
            return native
    return _python_system_proxy()


def auto_proxy(provider: str = "python", **urlopen_kwargs) -> ProxyMap:
    """Resolve the effective ``ProxyMap`` for this machine.

    Order: OS-native settings / env vars (:func:`system_proxy`) → if that
    yields a PAC URL, load it → if it yields no usable config at all (the
    ``"python"`` provider's own signal for "OS has nothing configured"),
    try WPAD discovery → otherwise DIRECT.
    """
    proxy = system_proxy(provider)
    if isinstance(proxy, str):
        return load_pac(proxy, **urlopen_kwargs)
    if isinstance(proxy, SimpleProxyMap) and proxy[""] == (None,):
        from ..pac.wpad import discover

        discovered = discover(**urlopen_kwargs)
        if discovered is not None:
            return discovered
    return proxy
