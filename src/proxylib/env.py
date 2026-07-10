"""Proxy selection from the conventional ``HTTP_PROXY``/``HTTPS_PROXY``/``NO_PROXY`` env vars."""

from __future__ import annotations

import ipaddress as _ip
import os
from typing import Iterable, List, Optional, Tuple, Union

from .netutils import get_ip, get_local_interfaces
from .proxy import URL, Proxy, ProxyMap, SimpleProxyMap

__all__ = ("EnvProxyConfig", "set_default_no_proxy", "get_default_no_proxy")

_NoProxyNetwork = Union["_ip.IPv4Network", "_ip.IPv6Network"]
_NoProxyEntry = Union[Tuple[str, Optional[int]], _NoProxyNetwork, None]

# Org-wide default NO_PROXY rules, consulted by every EnvProxyConfig (and
# ConfigurableProxyMap's own no_proxy=) in addition to whatever's passed
# explicitly -- lets an application set a bypass policy once regardless of
# which map/backend produced the rest of the config.
_default_no_proxy: "List[str]" = []


def set_default_no_proxy(rules: "Iterable[str]|None") -> None:
    """Set the process-wide default ``NO_PROXY`` rules (same entry syntax as the
    env var: hostnames, ``.suffix``, ``<local>``, CIDR). Merged with -- not
    replaced by -- whatever rules each ``EnvProxyConfig``/``ConfigurableProxyMap``
    is given explicitly. Pass ``None`` (or an empty iterable) to clear it."""
    global _default_no_proxy
    _default_no_proxy = list(rules) if rules else []


def get_default_no_proxy() -> "List[str]":
    """Return a copy of the current process-wide default ``NO_PROXY`` rules."""
    return list(_default_no_proxy)


def _parse_no_proxy_entry(entry: str) -> _NoProxyEntry:
    """Parse one NO_PROXY entry: ``None`` for ``<local>``, a network for CIDR
    notation, or (host, port) with a leading '.' stripped otherwise."""
    entry = entry.strip()
    if not entry or entry == "<local>":
        return None
    if "/" in entry:
        # CIDR entry, e.g. "10.0.0.0/8" or "2001:db8::/32" -- parse the "/"
        # before the host:port split below, since IPv6 CIDRs contain ":"
        # and would be mangled by rpartition(":").
        return _ip.ip_network(entry, strict=False)
    host, _, port = entry.rpartition(":")
    if not host:
        host, port = port, ""
    host = host.lstrip(".").lower()
    return host, (int(port) if port.isdigit() else None)


def _no_proxy_matches(host: str, port: "int|None", entry: "Tuple[str, int|None]") -> bool:
    """True if a NO_PROXY entry (host[, port]) covers this request's host/port.

    Follows the common curl/requests convention: an entry matches the
    request host exactly, or as a dot-boundary suffix (so ``example.com``
    matches ``example.com`` and ``api.example.com`` but not
    ``evilexample.com``). If the entry specifies a port, the request's port
    must match too.
    """
    entry_host, entry_port = entry
    host = host.lower()
    if host != entry_host and not host.endswith("." + entry_host):
        return False
    if entry_port is not None and port != entry_port:
        return False
    return True


class EnvProxyConfig(ProxyMap):
    """A ``ProxyMap`` built from ``HTTP_PROXY``/``HTTPS_PROXY``/``NO_PROXY``-style settings."""

    __slots__ = ("http_proxy", "https_proxy", "no_proxy")

    def __init__(
        self,
        http_proxy: "str|Proxy|None",
        https_proxy: "str|Proxy|None",
        no_proxy: "Iterable[str]|None",
    ) -> None:
        # SimpleProxyMap directly, not the ProxyMap factory: proxy env var
        # values are never PAC sources (PROXY_PAC/AutoConfigURL cover that
        # separately in each OS backend), and the factory routing a
        # PAC-looking value to pac.load() would do network I/O from this
        # constructor.
        # None means "no opinion" (KeyError), not "explicitly DIRECT" -- env
        # vars have no way to express DIRECT, only "set" or "absent". Keeping
        # these Optional (instead of always building a SimpleProxyMap) lets
        # __getitem__ raise KeyError for an unconfigured scheme so a
        # ChainProxyMap can fall through to the next map instead of the
        # (wrong) DIRECT result SimpleProxyMap(None) would otherwise give.
        self.http_proxy: "Optional[ProxyMap]" = SimpleProxyMap(http_proxy) if http_proxy else None
        self.https_proxy: "Optional[ProxyMap]" = SimpleProxyMap(https_proxy) if https_proxy else None
        # Explicit rules are deduped-and-checked ahead of the process-wide
        # defaults, but since NO_PROXY rules are purely additive (matching
        # any entry bypasses the proxy) there's no override semantics to get
        # wrong here -- this just controls iteration order.
        merged = dict.fromkeys([*(no_proxy or ()), *get_default_no_proxy()])
        self.no_proxy: "List[_NoProxyEntry]" = [_parse_no_proxy_entry(_no) for _no in merged]

    def __getitem__(self, url: str) -> Iterable[Optional[Proxy]]:
        uri = URL.from_str(url)
        # Resolve DNS lazily: get_ip() is a blocking gethostbyname() call,
        # only needed for "<local>" entries -- don't pay it per lookup when
        # no_proxy has none (the overwhelmingly common case).
        ip_literal: "_ip.IPv4Address|_ip.IPv6Address|None" = None
        ip_literal_checked = False
        for entry in self.no_proxy:
            if entry is None:
                # "<local>": bypass the proxy for loopback and same-subnet addresses.
                ip = get_ip(uri.host)
                if ip is None:
                    continue
                if ip.is_loopback:
                    return [None]
                for _if in get_local_interfaces():
                    if ip in _if.network:
                        return [None]
            elif isinstance(entry, (_ip.IPv4Network, _ip.IPv6Network)):
                # CIDR entries match IP-literal request hosts only (curl
                # semantics) -- resolving hostnames to check membership
                # would reintroduce the per-lookup DNS cost this module
                # otherwise deliberately avoids (see the known-bugs note).
                if not ip_literal_checked:
                    try:
                        ip_literal = _ip.ip_address(uri.host)
                    except ValueError:
                        ip_literal = None
                    ip_literal_checked = True
                if ip_literal is not None and ip_literal in entry:
                    return [None]
            elif _no_proxy_matches(uri.host, uri.port, entry):
                return [None]
        target = self.https_proxy if uri.scheme == "https" else self.http_proxy
        if target is None:
            raise KeyError(url)
        return target[f"{uri.scheme}://{uri.netloc}"]

    @staticmethod
    def from_env() -> "EnvProxyConfig":
        """Build an ``EnvProxyConfig`` from the process environment (upper or lowercase names)."""
        https = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
        http = os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy")
        no_proxy = os.environ.get("NO_PROXY") or os.environ.get("no_proxy")

        return EnvProxyConfig(
            http, https, [_no.strip() for _no in no_proxy.split(",")] if no_proxy else []
        )
