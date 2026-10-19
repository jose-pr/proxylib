"""Private network helpers, built on netimps.

netimps is imported inside each function: on Windows importing it adds
``recvmsg``/``sendmsg`` to the ``socket`` module, and ``import proxylib``
should not have that side effect before any network work is done.
"""

from __future__ import annotations

import ipaddress as _ip
import sys
import time as _time
from typing import TYPE_CHECKING, Callable, Dict, Iterable, List, Optional, Tuple, Union

if TYPE_CHECKING:
    # proxy.py imports this module, so Proxy is named for type checkers only.
    from .proxy import Proxy

from .exceptions import NoReachableProxyError

IPAddress = Union[_ip.IPv4Address, _ip.IPv6Address]
IPInterface = Union[_ip.IPv4Interface, _ip.IPv6Interface]

# Seconds a local interface enumeration is reused; the <local> bypass rule
# asks for it on every lookup.
INTERFACE_CACHE_TTL = 10.0

_cache_clearers: "List[Callable[[], None]]" = []


def register_cache(clear: "Callable[[], None]") -> "Callable[[], None]":
    """Add a module's cache-clearing function to :func:`clear_caches`."""
    _cache_clearers.append(clear)
    return clear


def clear_caches() -> None:
    """Drop every cache proxylib keeps: downloaded PAC scripts, WPAD and DNS
    answers, desktop settings, local interfaces and unreachable proxies."""
    for clear in _cache_clearers:
        clear()


def join_host(host: str, port: "Optional[int]") -> str:
    """``host:port`` with an IPv6 literal bracketed; no port when ``port`` is
    ``None`` or ``0``."""
    import netimps

    return netimps.join_host(host, port or None)


def split_host_port(text: str) -> "Optional[Tuple[str, Optional[int]]]":
    """Split ``host[:port]`` (IPv6 bracketed), or ``None`` when the port is
    not a number in range or the text has stray colons."""
    import netimps

    try:
        return netimps.split_host(text)
    except ValueError:
        return None


def _enumerate_interfaces() -> "List[IPInterface]":
    import netimps

    return [ip for iface in netimps.get_interfaces(cache=INTERFACE_CACHE_TTL) for ip in iface.ips]


def local_networks() -> "List[IPInterface]":
    """This host's addresses with their real prefix lengths, loopback included."""
    return _enumerate_interfaces()


@register_cache
def _clear_interface_cache() -> None:
    if "netimps" in sys.modules:
        import netimps

        netimps.clear_interface_cache()


def resolve_ip(host: str, *, ipv6: "Optional[bool]" = False, timeout: float = 5.0) -> "Optional[IPAddress]":
    """The address ``host`` names (a literal is returned as is), or ``None``.

    ``ipv6=False`` asks for IPv4 only, ``True`` for IPv6 only and ``None`` for
    whichever the OS resolver answers first. The OS resolver is used (hosts
    file and DNS, as ``getaddrinfo`` sees them), bounded by ``timeout``.
    """
    import netimps

    if not host:
        return None
    try:
        return netimps.Host(host).ip(ipv6=ipv6, timeout=timeout, backends="system")
    except (OSError, ValueError):
        return None


def resolve_all(host: str, *, timeout: float = 5.0) -> "List[IPAddress]":
    """Every IPv4 and IPv6 address ``host`` names, through the OS resolver,
    bounded by ``timeout``; ``[]`` when it names none or the lookup fails."""
    import netimps

    if not host:
        return []
    try:
        return list(netimps.resolve_system(host, ("a", "aaaa"), timeout=timeout))
    except (OSError, ValueError):
        return []


def default_port(scheme: str) -> "Optional[int]":
    """The conventional port for a URL or proxy scheme, or ``None``."""
    import netimps

    try:
        return netimps.get_default_port(scheme)
    except (TypeError, ValueError):
        return None


def is_link_scoped(ip: IPAddress) -> bool:
    """Loopback or link-local: an address no proxy can usefully reach."""
    import netimps

    return netimps.is_link_scoped(ip)


def _tcp_check(host: str, port: int, timeout: float) -> bool:
    import netimps

    try:
        return netimps.tcp_check(host, port, timeout=timeout)
    except (TypeError, ValueError):
        return False


# (host, port) -> monotonic time its blacklisting ends. A proxy that failed a
# probe is skipped without probing until then.
_circuit_breaker: "Dict[Tuple[str, int], float]" = {}


@register_cache
def _clear_circuit_breaker() -> None:
    _circuit_breaker.clear()


def _health_key(proxy: "Proxy") -> "Tuple[str, int]":
    return (proxy.host, proxy.port or default_port(proxy.scheme) or 0)


def mark_bad(proxy: "Optional[Proxy]", *, ttl: float = 300.0) -> None:
    """Remember that ``proxy`` failed: :func:`order_by_health` puts it last,
    and :func:`first_working_proxy` skips it, for ``ttl`` seconds. DIRECT
    (``None``) is never marked."""
    if proxy is not None and ttl > 0:
        _circuit_breaker[_health_key(proxy)] = _time.monotonic() + ttl


def order_by_health(entries: "Iterable[Optional[Proxy]]") -> "List[Optional[Proxy]]":
    """``entries`` with the ones marked bad moved to the end, each group in
    its original order."""
    now = _time.monotonic()
    good: "List[Optional[Proxy]]" = []
    bad: "List[Optional[Proxy]]" = []
    for entry in entries:
        until = _circuit_breaker.get(_health_key(entry)) if entry is not None else None
        (bad if until is not None and now < until else good).append(entry)
    return good + bad


def first_working_proxy(
    proxies: "Iterable[Optional[Proxy]]",
    *,
    timeout: float = 5.0,
    circuit_breaker_ttl: "Optional[float]" = 30.0,
    clock: "Callable[[], float]" = _time.monotonic,
) -> "Optional[Proxy]":
    """The first entry that accepts a TCP connection, in order; a ``None``
    entry (DIRECT) is returned at once. Only reachability of the proxy port
    is checked. Raises :class:`NoReachableProxyError` when nothing answers.
    """
    now = clock()
    for proxy in proxies:
        if proxy is None:
            return None
        port = proxy.port or default_port(proxy.scheme)
        if not port:
            continue
        key = (proxy.host, port)
        if circuit_breaker_ttl:
            blacklisted_until = _circuit_breaker.get(key)
            if blacklisted_until is not None and now < blacklisted_until:
                continue
        if _tcp_check(proxy.host, port, timeout):
            return proxy
        if circuit_breaker_ttl:
            _circuit_breaker[key] = now + circuit_breaker_ttl
    raise NoReachableProxyError("no reachable proxy in the given list")
