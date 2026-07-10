"""Small stdlib-first networking helpers used across proxylib.

``get_local_interfaces`` prefers the optional ``ifaddr`` package (accurate
adapter/prefix info on every OS) and falls back to a best-effort,
stdlib-only implementation when it isn't installed.
"""

from __future__ import annotations

import ipaddress as _ip
import socket as _socket
import time as _time
from typing import TYPE_CHECKING, Iterable, List, Optional, Tuple, Union

if TYPE_CHECKING:
    # Runtime import would be circular: proxy.py imports this module.
    from .proxy import Proxy

_Interface = Union[_ip.IPv4Interface, _ip.IPv6Interface]

try:
    import ifaddr as _ifaddr

    def _enumerate_interfaces() -> "List[_Interface]":
        """Return this host's local network interfaces as ip_interface objects."""
        ips: "List[_Interface]" = []

        for adapter in _ifaddr.get_adapters():
            for ip in adapter.ips:
                if ip.is_IPv4:
                    ips.append(_ip.IPv4Interface((ip.ip, ip.network_prefix)))
                else:
                    ips.append(
                        _ip.IPv6Interface(
                            (ip.ip[0] + "%" + str(ip.ip[2]), ip.network_prefix)
                        )
                    )
        return ips

except ImportError:

    def _enumerate_interfaces() -> "List[_Interface]":
        """Best-effort fallback: resolve all addresses for the local hostname.

        Without ``ifaddr`` there is no portable stdlib way to enumerate real
        adapters/prefixes, so every address is reported as a host route
        (/32 or /128). Install the ``ifaddr`` extra for accurate results.
        """
        ips: "List[_Interface]" = []
        seen: "set[str]" = set()
        hostname = _socket.gethostname()
        try:
            infos = _socket.getaddrinfo(hostname, None)
        except OSError:
            infos = []
        for family, _, _, _, sockaddr in infos:
            addr = sockaddr[0]
            if addr in seen:
                continue
            seen.add(addr)
            if family == _socket.AF_INET:
                ips.append(_ip.IPv4Interface(f"{addr}/32"))
            elif family == _socket.AF_INET6:
                ips.append(_ip.IPv6Interface(f"{addr.split('%')[0]}/128"))
        if not ips:
            try:
                addr = _socket.gethostbyname(hostname)
                ips.append(_ip.IPv4Interface(f"{addr}/32"))
            except OSError:
                pass
        return ips


# (monotonic timestamp, result) of the last _enumerate_interfaces() call, or
# None before the first call. Real interface enumeration (the ifaddr-less
# getaddrinfo fallback especially) blocks, and <local>-in-NO_PROXY lookups
# hit it on every request -- cache briefly. clear_interfaces_cache() is the
# seam tests use to bypass it, same shape as pac.wpad's _cache.
_interfaces_cache: "Optional[Tuple[float, List[_Interface]]]" = None


def get_local_interfaces(cache_ttl: "float|None" = 10.0) -> "List[_Interface]":
    """Return this host's local network interfaces, cached for ``cache_ttl`` seconds.

    Pass ``cache_ttl=0``/``None`` to force a fresh enumeration.
    """
    global _interfaces_cache
    if cache_ttl:
        cached = _interfaces_cache
        if cached is not None and (_time.monotonic() - cached[0]) < cache_ttl:
            return cached[1]
    result = _enumerate_interfaces()
    if cache_ttl:
        _interfaces_cache = (_time.monotonic(), result)
    return result


def clear_interfaces_cache() -> None:
    """Clear the ``get_local_interfaces`` cache. Call this in tests that monkeypatch enumeration."""
    global _interfaces_cache
    _interfaces_cache = None


def get_ip(address: str) -> "_ip.IPv4Address|_ip.IPv6Address|None":
    """Resolve a hostname or literal address to an ip_address, or None."""
    try:
        try:
            return _ip.ip_address(address)
        except ValueError:
            return _ip.ip_address(_socket.gethostbyname(address))
    except (ValueError, OSError):
        return None


_DEFAULT_PORTS = {
    "http": 80,
    "https": 443,
    "ftp": 21,
    "socks": 1080,
    "socks4": 1080,
    "socks5": 1080,
}


def get_default_port(scheme: str) -> "int|None":
    """Return the conventional port for a scheme, or None if unknown."""
    scheme = scheme.lower()
    if scheme in _DEFAULT_PORTS:
        return _DEFAULT_PORTS[scheme]
    try:
        return _socket.getservbyname(scheme)
    except OSError:
        return None


def first_working_proxy(
    proxies: "Iterable[Optional[Proxy]]", timeout: float = 5.0
) -> "Optional[Proxy]":
    """Return the first entry that accepts a TCP connection, in order.

    Failover helper for ``ProxyMap`` results (``PROXY a; PROXY b; DIRECT``
    means "try these in order")::

        proxy = first_working_proxy(proxymap[url])

    A ``None`` entry (DIRECT) is returned immediately -- there's no proxy to
    probe. This only checks TCP reachability of the proxy port, not that the
    proxy will actually serve the request. Raises ``LookupError`` when no
    entry is reachable (``None`` can't signal failure here: it means DIRECT).
    """
    for proxy in proxies:
        if proxy is None:
            return None
        port = proxy.port or get_default_port(proxy.scheme)
        if not port:
            continue
        try:
            sock = _socket.create_connection((proxy.host, port), timeout=timeout)
        except OSError:
            continue
        sock.close()
        return proxy
    raise LookupError("no reachable proxy in the given list")
