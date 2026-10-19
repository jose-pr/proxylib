"""This machine's proxy settings.

- :func:`auto_proxy` -- the proxy map a program should use: the proxy
  environment variables when any is set, else the OS's own resolver backed by
  the OS settings.
- :func:`system_config` -- the OS or desktop settings, as a
  :class:`ProxyConfig`.
- :class:`WinHTTPProxyMap`, :class:`CFNetworkProxyMap`,
  :class:`LibProxyMap` -- the OS resolvers (Windows, macOS, libproxy).
"""

from __future__ import annotations

import os
import sys
from typing import Iterable, Mapping, Optional, Union

from ..bypass import BypassRules
from ..env import EnvProxyConfig, _read_env
from ..proxy import ChainProxyMap, ProxyMap, SimpleProxyMap
from ..wrappers import Bypass
from . import _darwin, _nt, _posix
from ._config import ProxyConfig
from ._darwin import CFNetworkProxyMap
from ._nt import WinHTTPProxyMap
from ._posix import _libproxy
from ._posix._libproxy import LibProxyMap
from ._run import log

__all__ = (
    "CFNetworkProxyMap",
    "LibProxyMap",
    "ProxyConfig",
    "WinHTTPProxyMap",
    "auto_proxy",
    "system_config",
)

# Read on every call, so tests can stand in for another OS.
_PLATFORM = sys.platform


def system_config() -> ProxyConfig:
    """This machine's proxy settings, from the OS or desktop; the environment
    variables are not read.

    Windows: the current user's Internet Options. macOS: System Configuration
    (``scutil --proxy``). Elsewhere: GNOME, MATE, KDE and NetworkManager, the
    first with a proxy configured, else the first with settings. With none
    readable, ``ProxyConfig()`` (``source="none"``, ``state="unset"``).
    """
    if _PLATFORM == "win32":
        config = _nt.read_config()
    elif _PLATFORM == "darwin":
        config = _darwin.read_config()
    else:
        config = _posix.read_config()
    if config is None:
        config = ProxyConfig()
    log.debug("system proxy settings: %r", config)
    return config


def _os_resolver() -> "Optional[ProxyMap]":
    if _PLATFORM == "win32":
        return _nt.WinHTTPProxyMap()
    if _PLATFORM == "darwin":
        return _darwin.CFNetworkProxyMap() if _darwin._get_cf_bindings() is not None else None
    lib = _libproxy._get_libproxy()
    return _libproxy.LibProxyMap(lib) if lib is not None else None


def _has_proxy_variable(env: "Mapping[str, str]") -> bool:
    proxies, _ = _read_env(env)
    return any(proxies.values())


def auto_proxy(
    *,
    system: bool = True,
    no_proxy: "Union[BypassRules, str, Iterable[str], None]" = None,
    wpad: bool = False,
    timeout: float = 10.0,
    on_missing_engine: str = "raise",
    environ: "Optional[Mapping[str, str]]" = None,
) -> ProxyMap:
    """The proxy map for this machine. It answers every URL.

    When any proxy variable (``HTTP_PROXY``, ``HTTPS_PROXY``, ``ALL_PROXY``,
    ...) is set in ``environ`` (default ``os.environ``), those variables and
    ``NO_PROXY`` alone decide, as in :func:`urllib.request.getproxies`: a
    scheme without a variable goes DIRECT, and the OS is not consulted. A
    variable may hold a PAC location (see :class:`EnvProxyConfig`).

    Otherwise the OS settings decide. With ``system=True`` the OS's own
    resolver answers when there is one -- WinHTTP on Windows, CFNetwork on
    macOS, libproxy elsewhere when it is installed -- and a URL it cannot
    answer goes to :meth:`ProxyConfig.to_proxymap` of :func:`system_config`;
    ``system=False`` uses only the latter. ``wpad``, ``timeout`` and
    ``on_missing_engine`` are passed to it: WPAD runs only when the OS asks
    for auto-detection, or with ``wpad=True`` when it has no settings.

    ``no_proxy`` rules (``BypassRules`` or ``NO_PROXY`` text) are applied
    over everything.
    """
    env = os.environ if environ is None else environ
    proxymap: ProxyMap
    if _has_proxy_variable(env):
        log.debug("using the proxy environment variables")
        proxymap = ChainProxyMap(EnvProxyConfig(env), SimpleProxyMap())
    else:
        fallback = system_config().to_proxymap(wpad=wpad, timeout=timeout, on_missing_engine=on_missing_engine)
        resolver = _os_resolver() if system else None
        log.debug("OS resolver: %r", resolver)
        proxymap = ChainProxyMap(resolver, fallback) if resolver is not None else fallback
    if no_proxy is not None:
        proxymap = Bypass(proxymap, no_proxy)
    return proxymap
