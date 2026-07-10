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
from typing import Dict, Iterable, NamedTuple, Optional

from ..env import EnvProxyConfig
from ..pac.wpad import discover as _wpad_discover
from ..proxy import URL, Proxy, ProxyMap, SimpleProxyMap

__all__ = ("system_proxy", "WinHttpProxyMap")


class _IEProxyConfig(ctypes.Structure):
    _fields_ = [
        ("fAutoDetect", wintypes.BOOL),
        ("lpszAutoConfigUrl", ctypes.c_void_p),
        ("lpszProxy", ctypes.c_void_p),
        ("lpszProxyBypass", ctypes.c_void_p),
    ]


# use_last_error=True: WinHttpGetProxyForUrl's failure reason (e.g. "no PAC
# server found" vs. "NTLM/Kerberos challenge") is only available via
# GetLastError(), not a return value.
_winhttp = ctypes.WinDLL("winhttp", use_last_error=True)
_winhttp.WinHttpGetIEProxyConfigForCurrentUser.argtypes = [ctypes.POINTER(_IEProxyConfig)]
_winhttp.WinHttpGetIEProxyConfigForCurrentUser.restype = wintypes.BOOL

_kernel32 = ctypes.WinDLL("kernel32")
_kernel32.GlobalFree.argtypes = [ctypes.c_void_p]


class _WinHttpAutoProxyOptions(ctypes.Structure):
    _fields_ = [
        ("dwFlags", wintypes.DWORD),
        ("dwAutoDetectFlags", wintypes.DWORD),
        ("lpszAutoConfigUrl", wintypes.LPCWSTR),
        ("lpvReserved", ctypes.c_void_p),
        ("dwReserved", wintypes.DWORD),
        ("fAutoLogonIfChallenged", wintypes.BOOL),
    ]


class _WinHttpProxyInfo(ctypes.Structure):
    _fields_ = [
        ("dwAccessType", wintypes.DWORD),
        ("lpszProxy", ctypes.c_void_p),
        ("lpszProxyBypass", ctypes.c_void_p),
    ]


_WINHTTP_ACCESS_TYPE_NO_PROXY = 1
_WINHTTP_AUTOPROXY_AUTO_DETECT = 0x00000001
_WINHTTP_AUTOPROXY_CONFIG_URL = 0x00000002
_WINHTTP_AUTO_DETECT_TYPE_DHCP = 0x00000001
_WINHTTP_AUTO_DETECT_TYPE_DNS_A = 0x00000002
_ERROR_WINHTTP_LOGIN_FAILURE = 12015

_winhttp.WinHttpOpen.argtypes = [
    wintypes.LPCWSTR, wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD
]
_winhttp.WinHttpOpen.restype = wintypes.HANDLE
_winhttp.WinHttpCloseHandle.argtypes = [wintypes.HANDLE]
_winhttp.WinHttpCloseHandle.restype = wintypes.BOOL
_winhttp.WinHttpGetProxyForUrl.argtypes = [
    wintypes.HANDLE,
    wintypes.LPCWSTR,
    ctypes.POINTER(_WinHttpAutoProxyOptions),
    ctypes.POINTER(_WinHttpProxyInfo),
]
_winhttp.WinHttpGetProxyForUrl.restype = wintypes.BOOL


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


def _manual_proxy_map(settings: "_IEProxySettings") -> "Optional[ProxyMap]":
    """Build the manual-proxy ``EnvProxyConfig`` from ``settings.proxy``/
    ``proxy_bypass``, or ``None`` if nothing is configured. Shared by
    ``system_proxy()``'s own manual-proxy step and ``WinHttpProxyMap``'s
    fallback for when autoproxy isn't configured, or fails.
    """
    if not settings.proxy:
        return None
    per_protocol = _split_per_protocol_proxy(settings.proxy)
    http_proxy = per_protocol.get("http") or per_protocol.get("https")
    https_proxy = per_protocol.get("https") or per_protocol.get("http")
    if not (http_proxy or https_proxy):
        return None
    overrides = (settings.proxy_bypass or "").replace(";", " ").split()
    return EnvProxyConfig(
        _as_url(http_proxy) if http_proxy else None,
        _as_url(https_proxy) if https_proxy else None,
        overrides,
    )


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

    return _manual_proxy_map(settings) or SimpleProxyMap()


def _query_proxy_for_url(
    hsession: int,
    url: str,
    auto_detect: bool,
    auto_config_url: "Optional[str]",
    auto_logon: bool,
) -> "tuple[Optional[str], Optional[str], bool, int]":
    """Raw ``WinHttpGetProxyForUrl`` call.

    Returns ``(proxy, proxy_bypass, ok, last_error)`` as plain values --
    the ``GlobalFree``-requiring ``WINHTTP_PROXY_INFO`` strings never leak
    out of this function, so tests can monkeypatch this one seam instead of
    dealing with ctypes structs/memory directly.
    """
    options = _WinHttpAutoProxyOptions()
    flags = 0
    if auto_detect:
        flags |= _WINHTTP_AUTOPROXY_AUTO_DETECT
        options.dwAutoDetectFlags = _WINHTTP_AUTO_DETECT_TYPE_DHCP | _WINHTTP_AUTO_DETECT_TYPE_DNS_A
    if auto_config_url:
        flags |= _WINHTTP_AUTOPROXY_CONFIG_URL
        options.lpszAutoConfigUrl = auto_config_url
    options.dwFlags = flags
    options.fAutoLogonIfChallenged = auto_logon

    info = _WinHttpProxyInfo()
    ctypes.set_last_error(0)
    ok = bool(
        _winhttp.WinHttpGetProxyForUrl(hsession, url, ctypes.byref(options), ctypes.byref(info))
    )
    if not ok:
        return None, None, False, ctypes.get_last_error()
    try:
        return _wstring_at(info.lpszProxy), _wstring_at(info.lpszProxyBypass), True, 0
    finally:
        if info.lpszProxy:
            _kernel32.GlobalFree(info.lpszProxy)
        if info.lpszProxyBypass:
            _kernel32.GlobalFree(info.lpszProxyBypass)


def _resolve_for_scheme(url: str, proxy_str: str) -> "Optional[Proxy]":
    per_protocol = _split_per_protocol_proxy(proxy_str)
    scheme = URL.from_str(url).scheme
    selected = per_protocol.get(scheme) or per_protocol.get("http") or per_protocol.get("https")
    return Proxy.from_str(_as_url(selected)) if selected else None


class WinHttpProxyMap(ProxyMap):
    """A ``ProxyMap`` backed by WinHTTP's own autoproxy engine (``WinHttpGetProxyForUrl``).

    Unlike :func:`system_proxy`'s Python-side WPAD/PAC path, this outsources
    WPAD/DHCP-252 discovery, NTLM/Kerberos SSO for fetching the PAC script,
    and PAC JS execution itself to WinHTTP -- no ``dukpy`` needed on
    Windows. Falls back to the static manual proxy (from
    ``WinHttpGetIEProxyConfigForCurrentUser``) when autoproxy isn't
    configured, or when ``WinHttpGetProxyForUrl`` fails; DIRECT if nothing
    at all is configured.

    Reuses one ``WinHttpOpen`` session handle for its lifetime (release it
    with :meth:`close`, or let garbage collection do it) -- opening a
    session per lookup would be wasteful, and WinHTTP's own autoproxy
    result caching is scoped to the session.
    """

    __slots__ = ("_hsession",)

    def __init__(self) -> None:
        self._hsession = _winhttp.WinHttpOpen(
            "proxylib", _WINHTTP_ACCESS_TYPE_NO_PROXY, None, None, 0
        )

    def close(self) -> None:
        if self._hsession:
            _winhttp.WinHttpCloseHandle(self._hsession)
            self._hsession = None

    def __del__(self) -> None:
        self.close()

    def __getitem__(self, url: str) -> "Iterable[Optional[Proxy]]":
        if not self._hsession:
            raise KeyError(url)
        ie = _read_ie_proxy_config()
        auto_detect = bool(ie and ie.auto_detect)
        auto_config_url = ie.auto_config_url if ie else None

        if auto_detect or auto_config_url:
            proxy, _bypass, ok, last_error = _query_proxy_for_url(
                self._hsession, url, auto_detect, auto_config_url, auto_logon=False
            )
            # Documented WinHTTP pattern: only retry with
            # fAutoLogonIfChallenged=True on an actual NTLM/Kerberos
            # challenge -- always-True disables WinHTTP's own autoproxy
            # result caching.
            if not ok and last_error == _ERROR_WINHTTP_LOGIN_FAILURE:
                proxy, _bypass, ok, last_error = _query_proxy_for_url(
                    self._hsession, url, auto_detect, auto_config_url, auto_logon=True
                )
            if ok:
                if not proxy:
                    return [None]
                resolved = _resolve_for_scheme(url, proxy)
                return [resolved] if resolved else [None]
            # WinHttpGetProxyForUrl failed (e.g. ERROR_WINHTTP_AUTODETECTION_FAILED)
            # -- fall through to the static manual-proxy fallback below.

        manual = _manual_proxy_map(ie) if ie else None
        if manual is not None:
            return manual[url]
        return [None]
