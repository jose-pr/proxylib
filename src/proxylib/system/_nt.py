"""Windows: the current user's Internet Options, and WinHTTP's own resolver.

The settings are read with ``WinHttpGetIEProxyConfigForCurrentUser`` rather
than from the registry's ``DefaultConnectionSettings`` blob, whose layout is
undocumented and differs between Windows releases. The WinHTTP bindings load
on first use, so this module imports on every OS.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from types import SimpleNamespace
from typing import List, NamedTuple, Optional, Tuple
from urllib.parse import urlsplit

from ..bypass import BypassRules
from ..proxy import Proxy, ProxyMap
from ._config import ProxyConfig, manual_map, parse_proxy_list
from ._run import log

__all__ = ("WinHTTPProxyMap", "read_config", "config_from_settings")


class _IEProxyConfig(ctypes.Structure):
    _fields_ = [
        ("fAutoDetect", wintypes.BOOL),
        ("lpszAutoConfigUrl", ctypes.c_void_p),
        ("lpszProxy", ctypes.c_void_p),
        ("lpszProxyBypass", ctypes.c_void_p),
    ]


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

# Milliseconds for name resolution, connect, send and receive on the session
# WinHTTP uses to fetch a PAC file; its own resolve default is unbounded.
_SESSION_TIMEOUT_MS = 10_000

_libs: "Optional[SimpleNamespace]" = None


def _load() -> SimpleNamespace:
    """winhttp and kernel32 with their signatures set; ``OSError`` off Windows."""
    global _libs
    if _libs is not None:
        return _libs
    if not hasattr(ctypes, "WinDLL"):
        raise OSError("WinHTTP is only available on Windows")
    # use_last_error: WinHttpGetProxyForUrl reports why it failed (no PAC
    # found, an NTLM/Kerberos challenge) only through GetLastError().
    winhttp = ctypes.WinDLL("winhttp", use_last_error=True)
    winhttp.WinHttpGetIEProxyConfigForCurrentUser.argtypes = [ctypes.POINTER(_IEProxyConfig)]
    winhttp.WinHttpGetIEProxyConfigForCurrentUser.restype = wintypes.BOOL
    winhttp.WinHttpOpen.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD
    ]
    winhttp.WinHttpOpen.restype = wintypes.HANDLE
    winhttp.WinHttpCloseHandle.argtypes = [wintypes.HANDLE]
    winhttp.WinHttpCloseHandle.restype = wintypes.BOOL
    winhttp.WinHttpGetProxyForUrl.argtypes = [
        wintypes.HANDLE,
        wintypes.LPCWSTR,
        ctypes.POINTER(_WinHttpAutoProxyOptions),
        ctypes.POINTER(_WinHttpProxyInfo),
    ]
    winhttp.WinHttpGetProxyForUrl.restype = wintypes.BOOL
    winhttp.WinHttpSetTimeouts.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int]
    winhttp.WinHttpSetTimeouts.restype = wintypes.BOOL
    kernel32 = ctypes.WinDLL("kernel32")
    kernel32.GlobalFree.argtypes = [ctypes.c_void_p]
    _libs = SimpleNamespace(winhttp=winhttp, kernel32=kernel32)
    return _libs


class _IEProxySettings(NamedTuple):
    auto_detect: bool
    auto_config_url: "Optional[str]"
    proxy: "Optional[str]"
    proxy_bypass: "Optional[str]"


def _wstring_at(ptr: "Optional[int]") -> "Optional[str]":
    return ctypes.wstring_at(ptr) if ptr else None


def _read_ie_proxy_config() -> "Optional[_IEProxySettings]":
    """The current user's Internet Options proxy settings, or ``None``."""
    libs = _load()
    cfg = _IEProxyConfig()
    if not libs.winhttp.WinHttpGetIEProxyConfigForCurrentUser(ctypes.byref(cfg)):
        return None
    try:
        return _IEProxySettings(
            auto_detect=bool(cfg.fAutoDetect),
            auto_config_url=_wstring_at(cfg.lpszAutoConfigUrl),
            proxy=_wstring_at(cfg.lpszProxy),
            proxy_bypass=_wstring_at(cfg.lpszProxyBypass),
        )
    finally:
        # The caller owns these strings (WINHTTP_CURRENT_USER_IE_PROXY_CONFIG).
        libs.kernel32.GlobalFree(cfg.lpszAutoConfigUrl)
        libs.kernel32.GlobalFree(cfg.lpszProxy)
        libs.kernel32.GlobalFree(cfg.lpszProxyBypass)


def config_from_settings(settings: "_IEProxySettings") -> ProxyConfig:
    """``ProxyServer`` is ``host:port`` for every scheme or
    ``http=a:80;https=b:443;socks=c:1080``, where ``socks=`` is SOCKS v4 (as
    Chromium reads it); ``ProxyOverride`` is a WinINet bypass list. Windows
    always has settings, so nothing switched on is ``state="direct"``."""
    proxies = parse_proxy_list(settings.proxy or "", "socks4")
    configured = settings.auto_detect or bool(settings.auto_config_url) or bool(proxies)
    return ProxyConfig(
        source="windows",
        state="configured" if configured else "direct",
        auto_detect=settings.auto_detect,
        pac_url=settings.auto_config_url or None,
        proxies=proxies,
        bypass=BypassRules.parse(settings.proxy_bypass or "", dialect="wininet"),
    )


def read_config() -> "Optional[ProxyConfig]":
    try:
        settings = _read_ie_proxy_config()
    except OSError as exc:
        log.debug("cannot read the Windows proxy settings: %s", exc)
        return None
    if settings is None:
        log.debug("WinHttpGetIEProxyConfigForCurrentUser failed")
        return None
    return config_from_settings(settings)


def _query_proxy_for_url(
    hsession: int,
    url: str,
    auto_detect: bool,
    auto_config_url: "Optional[str]",
    auto_logon: bool,
) -> "Tuple[Optional[str], Optional[str], bool, int]":
    """One ``WinHttpGetProxyForUrl`` call, as ``(proxy, proxy_bypass, ok,
    last_error)``; the strings WinHTTP allocates are freed here."""
    libs = _load()
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
    ok = bool(libs.winhttp.WinHttpGetProxyForUrl(hsession, url, ctypes.byref(options), ctypes.byref(info)))
    if not ok:
        return None, None, False, ctypes.get_last_error()
    try:
        return _wstring_at(info.lpszProxy), _wstring_at(info.lpszProxyBypass), True, 0
    finally:
        if info.lpszProxy:
            libs.kernel32.GlobalFree(info.lpszProxy)
        if info.lpszProxyBypass:
            libs.kernel32.GlobalFree(info.lpszProxyBypass)


def _resolve_for_scheme(url: str, proxy_str: str) -> "List[Proxy]":
    """Every proxy in a WinHTTP proxy list that applies to ``url``, in order.

    The list is ``[<scheme>=]<server>[:<port>]`` entries separated by ``;`` or
    whitespace (``WINHTTP_PROXY_INFO``). Entries for this scheme or for no
    scheme apply; with none of those, the http entries and then the https
    ones are used.
    """
    scheme = urlsplit(url).scheme
    entries: "List[Tuple[str, str]]" = []
    for token in proxy_str.replace(";", " ").split():
        protocol, sep, server = token.partition("=")
        if not sep:
            protocol, server = "", token
        if server:
            entries.append((protocol.strip().lower(), server))
    for wanted in ((scheme, ""), ("http",), ("https",)):
        selected = [server for protocol, server in entries if protocol in wanted]
        if selected:
            return [Proxy.parse(server) for server in selected]
    return []


class WinHTTPProxyMap(ProxyMap):
    """A proxy map answered by WinHTTP's resolver (``WinHttpGetProxyForUrl``).

    WinHTTP does the WPAD discovery (DHCP and DNS), fetches the PAC with the
    user's NTLM/Kerberos credentials when challenged, and runs it, so no JS
    engine is needed. When the settings name neither auto-detection nor a
    PAC, or WinHTTP fails, the manual proxy settings answer; with none, DIRECT.

    One WinHTTP session serves every lookup, and WinHTTP caches PAC results
    per session; :meth:`close` releases it (garbage collection does too).
    After ``close`` a lookup has no opinion (``KeyError``). Windows only:
    construction raises ``OSError`` elsewhere.
    """

    __slots__ = ("_hsession",)

    def __init__(self) -> None:
        self._hsession = None
        libs = _load()
        self._hsession = libs.winhttp.WinHttpOpen("proxylib", _WINHTTP_ACCESS_TYPE_NO_PROXY, None, None, 0)
        if self._hsession:
            libs.winhttp.WinHttpSetTimeouts(self._hsession, *([_SESSION_TIMEOUT_MS] * 4))

    def __repr__(self) -> str:
        return "WinHTTPProxyMap()" if self._hsession else "WinHTTPProxyMap(<closed>)"

    def close(self) -> None:
        if self._hsession:
            _load().winhttp.WinHttpCloseHandle(self._hsession)
            self._hsession = None

    def __del__(self) -> None:
        try:
            self.close()
        except (AttributeError, OSError):  # __init__ did not finish
            pass

    def __getitem__(self, url: str) -> "Tuple[Optional[Proxy], ...]":
        if not self._hsession:
            raise KeyError(url)
        ie = _read_ie_proxy_config()
        auto_detect = bool(ie and ie.auto_detect)
        auto_config_url = ie.auto_config_url if ie else None

        if auto_detect or auto_config_url:
            proxy, _bypass, ok, last_error = _query_proxy_for_url(
                self._hsession, url, auto_detect, auto_config_url, auto_logon=False
            )
            # Retry with fAutoLogonIfChallenged only after a real NTLM/Kerberos
            # challenge: setting it on every call turns off WinHTTP's caching.
            if not ok and last_error == _ERROR_WINHTTP_LOGIN_FAILURE:
                proxy, _bypass, ok, last_error = _query_proxy_for_url(
                    self._hsession, url, auto_detect, auto_config_url, auto_logon=True
                )
            if ok:
                if not proxy:
                    return (None,)
                return tuple(_resolve_for_scheme(url, proxy)) or (None,)
            log.debug("WinHttpGetProxyForUrl failed for %s with error %d", url, last_error)

        if ie is None:
            return (None,)
        config = config_from_settings(ie)
        return manual_map(config.proxies, config.bypass)[url]
