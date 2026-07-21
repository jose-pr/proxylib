"""macOS system proxy detection via ``scutil --proxy`` (no extra dependency),
plus :class:`CFNetworkProxyMap`, a ctypes binding to the native CFNetwork
proxy-resolution API.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import subprocess
import time
from typing import Any, Dict, Iterable, List, Optional, Tuple

from ..env import EnvProxyConfig
from ..pac.wpad import discover as _wpad_discover
from ..proxy import Proxy, ProxyMap, SimpleProxyMap

__all__ = ("system_proxy", "CFNetworkProxyMap")

_kCFStringEncodingUTF8 = 0x08000100
_kCFNumberSInt64Type = 4
_CFProxyAutoConfigurationResultCallback = ctypes.CFUNCTYPE(
    None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p
)


def _parse_scutil_block(lines: "List[str]", pos: int) -> "Tuple[Dict[str, Any], int]":
    """Parse one ``{ ... }`` block of scutil's key/value dump into a dict (arrays become lists)."""
    result: "Dict[str, Any]" = {}
    while pos < len(lines):
        line = lines[pos].strip()
        pos += 1
        if line == "}":
            break
        if ":" not in line:
            continue
        key, _, rest = line.partition(":")
        key, rest = key.strip(), rest.strip()
        if rest in ("<dictionary> {", "<array> {"):
            value, pos = _parse_scutil_block(lines, pos)
            if rest == "<array> {" and all(k.isdigit() for k in value):
                value = [value[k] for k in sorted(value, key=int)]
            result[key] = value
        else:
            result[key] = rest
    return result, pos


def _read_scutil_proxy() -> "Dict[str, Any]":
    """Run and parse ``scutil --proxy`` into a nested dict; ``{}`` if unavailable."""
    try:
        output = subprocess.run(
            ["scutil", "--proxy"],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return {}

    lines = [ln.rstrip() for ln in output.splitlines()]
    start = next(
        (i + 1 for i, ln in enumerate(lines) if ln.strip().endswith("<dictionary> {")),
        0,
    )
    settings, _ = _parse_scutil_block(lines, start)
    return settings


def system_proxy() -> "ProxyMap|str":
    """Read proxy settings from macOS's System Configuration via ``scutil --proxy``.

    Mirrors macOS's own Network preferences precedence: if "Auto Proxy
    Discovery" (WPAD) is on, it's tried first; then Automatic Proxy
    Configuration (a PAC URL) if enabled; then a manual HTTP/HTTPS proxy;
    otherwise DIRECT.
    """
    settings = _read_scutil_proxy()

    if settings.get("ProxyAutoDiscoveryEnable") == "1":
        discovered = _wpad_discover()
        if discovered is not None:
            return discovered

    if settings.get("ProxyAutoConfigEnable") == "1":
        pac_url = settings.get("ProxyAutoConfigURLString")
        if pac_url:
            return pac_url

    http_enabled = settings.get("HTTPEnable") == "1"
    https_enabled = settings.get("HTTPSEnable") == "1"
    http_proxy = (
        f"http://{settings['HTTPProxy']}:{settings.get('HTTPPort', 80)}"
        if http_enabled and settings.get("HTTPProxy")
        else None
    )
    https_proxy = (
        f"http://{settings['HTTPSProxy']}:{settings.get('HTTPSPort', 443)}"
        if https_enabled and settings.get("HTTPSProxy")
        else None
    )
    if http_proxy or https_proxy:
        overrides = settings.get("ExceptionsList", [])
        return EnvProxyConfig(
            http_proxy or https_proxy, https_proxy or http_proxy, overrides
        )

    return SimpleProxyMap()


# ---- CFNetworkProxyMap: native CFNetwork/CoreFoundation proxy resolution -----
#
# Written against documented CFNetwork/CoreFoundation API signatures
# (CFProxySupport.h, CFRunLoop.h); no macOS is available in this dev
# environment, so this was validated by pushing a throwaway ci-* tag and
# running tests/test_os.py::test_cfnetworkproxymap_real_smoke (no mocking)
# against a real macos-latest GitHub Actions runner -- passed on Python 3.9
# and 3.13. That smoke test only confirms
# the happy path (DIRECT/manual proxy on a runner with nothing configured);
# the PAC-execution/run-loop-deadline branch is still unexercised by real
# CI and should be treated with more caution until it is.
#
# All ctypes/CFNetwork work is lazy (only touched inside _get_cf_bindings(),
# called only from _resolve_proxies_for_url(), called only from
# CFNetworkProxyMap.__getitem__()) so importing this module stays side-effect
# free on any platform -- the same reason libproxy.py's binding is lazy, and
# necessary here since tests import proxylib.os.darwin unconditionally on
# every OS (see tests/test_os.py's existing darwin.py tests, none of which
# are skipif'd to macOS-only).


class _CFBindings:
    """Resolved CoreFoundation/CFNetwork function pointers + constant symbols."""

    def __init__(self, cf: "ctypes.CDLL", cfnetwork: "ctypes.CDLL") -> None:
        self.cf = cf
        self.cfnetwork = cfnetwork

        cf.CFRelease.argtypes = [ctypes.c_void_p]
        cf.CFRelease.restype = None
        cf.CFRetain.argtypes = [ctypes.c_void_p]
        cf.CFRetain.restype = ctypes.c_void_p
        cf.CFStringCreateWithCString.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint32]
        cf.CFStringCreateWithCString.restype = ctypes.c_void_p
        cf.CFStringGetCString.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_long, ctypes.c_uint32]
        cf.CFStringGetCString.restype = ctypes.c_bool
        cf.CFStringGetLength.argtypes = [ctypes.c_void_p]
        cf.CFStringGetLength.restype = ctypes.c_long
        cf.CFDictionaryGetValue.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        cf.CFDictionaryGetValue.restype = ctypes.c_void_p
        cf.CFArrayGetCount.argtypes = [ctypes.c_void_p]
        cf.CFArrayGetCount.restype = ctypes.c_long
        cf.CFArrayGetValueAtIndex.argtypes = [ctypes.c_void_p, ctypes.c_long]
        cf.CFArrayGetValueAtIndex.restype = ctypes.c_void_p
        cf.CFNumberGetValue.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
        cf.CFNumberGetValue.restype = ctypes.c_bool
        cf.CFURLCreateWithString.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
        cf.CFURLCreateWithString.restype = ctypes.c_void_p
        cf.CFURLGetString.argtypes = [ctypes.c_void_p]
        cf.CFURLGetString.restype = ctypes.c_void_p
        cf.CFRunLoopGetCurrent.argtypes = []
        cf.CFRunLoopGetCurrent.restype = ctypes.c_void_p
        cf.CFRunLoopAddSource.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
        cf.CFRunLoopAddSource.restype = None
        cf.CFRunLoopRemoveSource.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
        cf.CFRunLoopRemoveSource.restype = None
        cf.CFRunLoopRunInMode.argtypes = [ctypes.c_void_p, ctypes.c_double, ctypes.c_bool]
        cf.CFRunLoopRunInMode.restype = ctypes.c_int32

        cfnetwork.CFNetworkCopySystemProxySettings.argtypes = []
        cfnetwork.CFNetworkCopySystemProxySettings.restype = ctypes.c_void_p
        cfnetwork.CFNetworkCopyProxiesForURL.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        cfnetwork.CFNetworkCopyProxiesForURL.restype = ctypes.c_void_p
        cfnetwork.CFNetworkExecuteProxyAutoConfigurationURL.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
            _CFProxyAutoConfigurationResultCallback,
            ctypes.c_void_p,
        ]
        cfnetwork.CFNetworkExecuteProxyAutoConfigurationURL.restype = ctypes.c_void_p

        self.kCFRunLoopDefaultMode = ctypes.c_void_p.in_dll(cf, "kCFRunLoopDefaultMode").value

        self.kCFProxyTypeKey = ctypes.c_void_p.in_dll(cfnetwork, "kCFProxyTypeKey").value
        self.kCFProxyHostNameKey = ctypes.c_void_p.in_dll(cfnetwork, "kCFProxyHostNameKey").value
        self.kCFProxyPortNumberKey = ctypes.c_void_p.in_dll(cfnetwork, "kCFProxyPortNumberKey").value
        self.kCFProxyAutoConfigurationURLKey = ctypes.c_void_p.in_dll(
            cfnetwork, "kCFProxyAutoConfigurationURLKey"
        ).value

        self.kCFProxyTypeNone = ctypes.c_void_p.in_dll(cfnetwork, "kCFProxyTypeNone").value
        self.kCFProxyTypeHTTP = ctypes.c_void_p.in_dll(cfnetwork, "kCFProxyTypeHTTP").value
        self.kCFProxyTypeHTTPS = ctypes.c_void_p.in_dll(cfnetwork, "kCFProxyTypeHTTPS").value
        self.kCFProxyTypeSOCKS = ctypes.c_void_p.in_dll(cfnetwork, "kCFProxyTypeSOCKS").value
        self.kCFProxyTypeFTP = ctypes.c_void_p.in_dll(cfnetwork, "kCFProxyTypeFTP").value
        self.kCFProxyTypeAutoConfigurationURL = ctypes.c_void_p.in_dll(
            cfnetwork, "kCFProxyTypeAutoConfigurationURL"
        ).value


_UNLOADED = object()
_cf_bindings: "Optional[_CFBindings]" = _UNLOADED  # type: ignore[assignment]


def _load_cf_bindings() -> "Optional[_CFBindings]":
    cf_path = ctypes.util.find_library("CoreFoundation")
    cfnetwork_path = ctypes.util.find_library("CFNetwork")
    if not cf_path or not cfnetwork_path:
        return None
    try:
        return _CFBindings(ctypes.CDLL(cf_path), ctypes.CDLL(cfnetwork_path))
    except (OSError, AttributeError, ValueError):
        return None


def _get_cf_bindings() -> "Optional[_CFBindings]":
    # Loaded lazily on first use (and memoized), same pattern as
    # os/posix/libproxy.py's _get_libproxy(): don't scan for these libraries
    # at import time on platforms where they'll never exist. Tests
    # monkeypatch _cf_bindings directly, which takes precedence.
    global _cf_bindings
    if _cf_bindings is _UNLOADED:
        _cf_bindings = _load_cf_bindings()
    return _cf_bindings


def _cfstring_to_str(cf: "ctypes.CDLL", ref: "Optional[int]") -> "Optional[str]":
    if not ref:
        return None
    length = cf.CFStringGetLength(ref)
    size = length * 4 + 1
    buf = ctypes.create_string_buffer(size)
    if cf.CFStringGetCString(ref, buf, size, _kCFStringEncodingUTF8):
        return buf.value.decode("utf-8")
    return None


def _cfnumber_to_int(cf: "ctypes.CDLL", ref: "Optional[int]") -> "Optional[int]":
    if not ref:
        return None
    value = ctypes.c_int64(0)
    if cf.CFNumberGetValue(ref, _kCFNumberSInt64Type, ctypes.byref(value)):
        return value.value
    return None


def _parse_proxy_entry(cfb: "_CFBindings", entry: int) -> "Tuple[str, Optional[str]]":
    """Parse one ``CFNetworkCopyProxiesForURL`` result dict.

    Returns ``("direct", None)``, ``("proxy", "scheme://host:port")``, or
    ``("pac", pac_url_string)`` for the "system says: run this PAC script"
    case (``kCFProxyTypeAutoConfigurationURL``) -- the caller is responsible
    for actually executing it via ``CFNetworkExecuteProxyAutoConfigurationURL``.
    """
    cf = cfb.cf
    proxy_type = cf.CFDictionaryGetValue(entry, cfb.kCFProxyTypeKey)
    if proxy_type == cfb.kCFProxyTypeNone:
        return ("direct", None)
    if proxy_type == cfb.kCFProxyTypeAutoConfigurationURL:
        pac_url_ref = cf.CFDictionaryGetValue(entry, cfb.kCFProxyAutoConfigurationURLKey)
        pac_url_string_ref = cf.CFURLGetString(pac_url_ref) if pac_url_ref else None
        return ("pac", _cfstring_to_str(cf, pac_url_string_ref))
    scheme = {
        cfb.kCFProxyTypeHTTP: "http",
        cfb.kCFProxyTypeHTTPS: "https",
        cfb.kCFProxyTypeSOCKS: "socks5",
        cfb.kCFProxyTypeFTP: "ftp",
    }.get(proxy_type)
    if scheme is None:
        # kCFProxyTypeAutoConfigurationJavaScript or an unrecognized type --
        # no usable entry to try.
        return ("direct", None)
    host = _cfstring_to_str(cf, cf.CFDictionaryGetValue(entry, cfb.kCFProxyHostNameKey))
    if not host:
        return ("direct", None)
    port = _cfnumber_to_int(cf, cf.CFDictionaryGetValue(entry, cfb.kCFProxyPortNumberKey))
    return ("proxy", f"{scheme}://{host}:{port}" if port else f"{scheme}://{host}")


def _run_pac_and_get_proxies(
    cfb: "_CFBindings", pac_cf_url: int, target_cf_url: int, deadline_at: float
) -> "Optional[int]":
    """Execute a PAC script against ``target_cf_url``, pumping the current
    run loop in small slices until the callback fires or ``deadline_at``
    (a ``time.monotonic()`` timestamp) passes.

    Returns the resulting ``CFArrayRef`` of proxy dicts (caller must
    ``CFRelease`` it), or ``None`` on timeout/failure -- a dead PAC server or
    hung DNS lookup must not block ``CFRunLoopRunInMode`` forever.
    """
    cf = cfb.cf
    state = {"array": None, "done": False}

    def _callback(_client, proxy_list, _error):
        if proxy_list:
            cf.CFRetain(proxy_list)  # only valid for the callback's duration otherwise
            state["array"] = proxy_list
        state["done"] = True

    callback = _CFProxyAutoConfigurationResultCallback(_callback)
    source = cfb.cfnetwork.CFNetworkExecuteProxyAutoConfigurationURL(
        pac_cf_url, target_cf_url, callback, None
    )
    if not source:
        return None
    run_loop = cf.CFRunLoopGetCurrent()
    cf.CFRunLoopAddSource(run_loop, source, cfb.kCFRunLoopDefaultMode)
    try:
        while not state["done"]:
            remaining = deadline_at - time.monotonic()
            if remaining <= 0:
                return None
            cf.CFRunLoopRunInMode(cfb.kCFRunLoopDefaultMode, min(remaining, 0.2), True)
    finally:
        cf.CFRunLoopRemoveSource(run_loop, source, cfb.kCFRunLoopDefaultMode)
        cf.CFRelease(source)
    return state["array"]


def _resolve_proxies_for_url(url: str, deadline: float = 5.0) -> "Optional[List[Optional[str]]]":
    """Resolve ``url`` via ``CFNetworkCopyProxiesForURL``, natively executing
    a configured system PAC script (``CFNetworkExecuteProxyAutoConfigurationURL``)
    if one applies.

    Returns a list where each entry is ``None`` (DIRECT) or a
    ``"scheme://host:port"`` string, in fallback-try order -- or ``None``
    for the whole call (not an entry) if CoreFoundation/CFNetwork aren't
    loadable, or PAC execution didn't finish within ``deadline`` seconds.
    Callers must treat that ``None`` as a resolution failure (raise
    ``KeyError``), not DIRECT.
    """
    cfb = _get_cf_bindings()
    if cfb is None:
        return None
    cf = cfb.cf
    deadline_at = time.monotonic() + deadline

    url_ref = cf.CFStringCreateWithCString(None, url.encode("utf-8"), _kCFStringEncodingUTF8)
    cf_url = cf.CFURLCreateWithString(None, url_ref, None)
    cf.CFRelease(url_ref)
    if not cf_url:
        return None

    try:
        settings = cfb.cfnetwork.CFNetworkCopySystemProxySettings()
        if not settings:
            return None
        try:
            proxies = cfb.cfnetwork.CFNetworkCopyProxiesForURL(cf_url, settings)
            if not proxies:
                return None
            try:
                results: "List[Optional[str]]" = []
                for i in range(cf.CFArrayGetCount(proxies)):
                    entry = cf.CFArrayGetValueAtIndex(proxies, i)
                    kind, extra = _parse_proxy_entry(cfb, entry)
                    if kind != "pac":
                        results.append(extra)
                        continue
                    if not extra:
                        return None
                    pac_url_ref = cf.CFStringCreateWithCString(
                        None, extra.encode("utf-8"), _kCFStringEncodingUTF8
                    )
                    pac_cf_url = cf.CFURLCreateWithString(None, pac_url_ref, None)
                    cf.CFRelease(pac_url_ref)
                    if not pac_cf_url:
                        return None
                    try:
                        pac_array = _run_pac_and_get_proxies(cfb, pac_cf_url, cf_url, deadline_at)
                    finally:
                        cf.CFRelease(pac_cf_url)
                    if pac_array is None:
                        return None
                    try:
                        for j in range(cf.CFArrayGetCount(pac_array)):
                            pac_kind, pac_extra = _parse_proxy_entry(cfb, cf.CFArrayGetValueAtIndex(pac_array, j))
                            results.append(pac_extra if pac_kind == "proxy" else None)
                    finally:
                        cf.CFRelease(pac_array)
                return results or [None]
            finally:
                cf.CFRelease(proxies)
        finally:
            cf.CFRelease(settings)
    finally:
        cf.CFRelease(cf_url)


class CFNetworkProxyMap(ProxyMap):
    """Resolves each request URL via macOS's native CFNetwork proxy engine.

    Unlike :func:`system_proxy` (which reads static settings once via
    ``scutil --proxy`` and relies on `EnvProxyConfig` for NO_PROXY-style
    matching), ``CFNetworkCopyProxiesForURL`` applies the system's real
    per-URL bypass-exception matching itself. When the system is configured
    with a PAC URL, it's executed natively (``CFNetworkExecuteProxyAutoConfigurationURL``)
    -- no ``dukpy`` needed -- pumped against a run loop in small slices up to
    ``deadline`` seconds (default 5.0) so a dead PAC server or hung DNS
    lookup can't block forever; on timeout, raises ``KeyError`` (a
    resolution failure per the ``ProxyMap`` contract -- same as
    ``LibProxyMap`` -- so a fallback/chain can proceed) rather than hanging
    or silently returning DIRECT.

    Validated by a real (unmocked) smoke test on macOS CI, but only for the
    common "direct/manual proxy" path -- the PAC-execution/run-loop-deadline
    branch is not yet exercised by that CI job, so treat it more cautiously.
    """

    __slots__ = ("deadline",)

    def __init__(self, deadline: float = 5.0) -> None:
        self.deadline = deadline

    def __getitem__(self, url: str) -> "Iterable[Optional[Proxy]]":
        entries = _resolve_proxies_for_url(url, self.deadline)
        if entries is None:
            raise KeyError(url)
        return [Proxy.from_str(entry) if entry else None for entry in entries]
