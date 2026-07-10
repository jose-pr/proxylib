"""Windows system proxy detection via the WinHTTP "IE proxy config" API.

Uses ``WinHttpGetIEProxyConfigForCurrentUser`` (stdlib ``ctypes``, no extra
dependency) rather than hand-parsing the registry's undocumented
``Connections\\DefaultConnectionSettings``/``SavedLegacySettings`` binary
blob. That blob *is* the underlying data source (its flags DWORD at offset 8
has bit ``0x08`` set when "Automatically detect settings" is on — verified
empirically), but its trailing layout has known version differences across
Windows releases; the WinHTTP API is Microsoft's supported way to read the
same data without guessing byte offsets. This mirrors what Chromium does.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from typing import Dict, NamedTuple, Optional

from ..env import EnvProxyConfig
from ..pac.wpad import discover as _wpad_discover
from ..proxy import ProxyMap, SimpleProxyMap

__all__ = ("system_proxy",)


class _IEProxyConfig(ctypes.Structure):
    _fields_ = [
        ("fAutoDetect", wintypes.BOOL),
        ("lpszAutoConfigUrl", ctypes.c_void_p),
        ("lpszProxy", ctypes.c_void_p),
        ("lpszProxyBypass", ctypes.c_void_p),
    ]


_winhttp = ctypes.WinDLL("winhttp")
_winhttp.WinHttpGetIEProxyConfigForCurrentUser.argtypes = [ctypes.POINTER(_IEProxyConfig)]
_winhttp.WinHttpGetIEProxyConfigForCurrentUser.restype = wintypes.BOOL

_kernel32 = ctypes.WinDLL("kernel32")
_kernel32.GlobalFree.argtypes = [ctypes.c_void_p]


class _IEProxySettings(NamedTuple):
    auto_detect: bool
    auto_config_url: "Optional[str]"
    proxy: "Optional[str]"
    proxy_bypass: "Optional[str]"


def _wstring_at(ptr: "Optional[int]") -> "Optional[str]":
    return ctypes.wstring_at(ptr) if ptr else None


def _read_ie_proxy_config() -> "Optional[_IEProxySettings]":
    """Read the current user's IE/WinHTTP proxy config, or None on failure."""
    cfg = _IEProxyConfig()
    if not _winhttp.WinHttpGetIEProxyConfigForCurrentUser(ctypes.byref(cfg)):
        return None
    try:
        return _IEProxySettings(
            auto_detect=bool(cfg.fAutoDetect),
            auto_config_url=_wstring_at(cfg.lpszAutoConfigUrl),
            proxy=_wstring_at(cfg.lpszProxy),
            proxy_bypass=_wstring_at(cfg.lpszProxyBypass),
        )
    finally:
        _kernel32.GlobalFree(cfg.lpszAutoConfigUrl)
        _kernel32.GlobalFree(cfg.lpszProxy)
        _kernel32.GlobalFree(cfg.lpszProxyBypass)


def _as_url(host_port: str) -> str:
    """WinHTTP proxy strings are bare "host:port", unlike HTTP_PROXY-style URLs."""
    return host_port if "://" in host_port else f"http://{host_port}"


def _split_per_protocol_proxy(proxy: str) -> "Dict[str, str]":
    """WinHTTP's proxy string is either "host:port" (all protocols) or
    "protocol=host:port;protocol=host:port" (per-protocol)."""
    if "=" not in proxy:
        return {"http": proxy, "https": proxy}
    result: "Dict[str, str]" = {}
    for entry in proxy.split(";"):
        protocol, _, value = entry.partition("=")
        protocol, value = protocol.strip().lower(), value.strip()
        if protocol and value:
            result[protocol] = value
    return result


def system_proxy() -> "ProxyMap|str":
    """Read proxy settings the way Windows/IE/Edge do.

    Mirrors Windows' own precedence: if "Automatically detect settings" is
    on, WPAD is tried first; then the configured PAC script (if any); then a
    manual proxy (if any); otherwise DIRECT.
    """
    settings = _read_ie_proxy_config()
    if settings is None:
        return SimpleProxyMap()

    if settings.auto_detect:
        discovered = _wpad_discover()
        if discovered is not None:
            return discovered

    if settings.auto_config_url:
        return settings.auto_config_url

    if settings.proxy:
        per_protocol = _split_per_protocol_proxy(settings.proxy)
        http_proxy = per_protocol.get("http") or per_protocol.get("https")
        https_proxy = per_protocol.get("https") or per_protocol.get("http")
        if http_proxy or https_proxy:
            overrides = (settings.proxy_bypass or "").replace(";", " ").split()
            return EnvProxyConfig(
                _as_url(http_proxy) if http_proxy else None,
                _as_url(https_proxy) if https_proxy else None,
                overrides,
            )

    return SimpleProxyMap()
