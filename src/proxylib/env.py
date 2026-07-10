"""Proxy selection from the conventional ``HTTP_PROXY``/``HTTPS_PROXY``/``NO_PROXY`` env vars."""

from __future__ import annotations

import os
from typing import Iterable, List, Optional, Tuple

from .netutils import get_ip, get_local_interfaces
from .proxy import URL, Proxy, ProxyMap

__all__ = ("EnvProxyConfig",)


def _parse_no_proxy_entry(entry: str) -> "Tuple[str, Optional[int]]|None":
    """Split a NO_PROXY entry into (host, port) with a leading '.' stripped, or None for ``<local>``."""
    entry = entry.strip()
    if not entry or entry == "<local>":
        return None
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
        self.http_proxy = ProxyMap(http_proxy)
        self.https_proxy = ProxyMap(https_proxy)
        self.no_proxy: "List[Tuple[str, int|None]|None]" = (
            [_parse_no_proxy_entry(_no) for _no in dict.fromkeys(no_proxy)]
            if no_proxy
            else []
        )

    def __getitem__(self, url: str) -> Iterable[Optional[Proxy]]:
        uri = URL.from_str(url)
        ip = get_ip(uri.host)
        for entry in self.no_proxy:
            if entry is None:
                # "<local>": bypass the proxy for loopback and same-subnet addresses.
                if ip is not None and ip.is_loopback:
                    return [None]
                for _if in get_local_interfaces():
                    if ip is not None and ip in _if.network:
                        return [None]
            elif _no_proxy_matches(uri.host, uri.port, entry):
                return [None]
        return (
            self.https_proxy[f"{uri.scheme}://{uri.netloc}"]
            if uri.scheme == "https"
            else self.http_proxy[f"{uri.scheme}://{uri.netloc}"]
        )

    @staticmethod
    def from_env() -> "EnvProxyConfig":
        """Build an ``EnvProxyConfig`` from the process environment (upper or lowercase names)."""
        https = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
        http = os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy")
        no_proxy = os.environ.get("NO_PROXY") or os.environ.get("no_proxy")

        return EnvProxyConfig(
            http, https, [_no.strip() for _no in no_proxy.split(",")] if no_proxy else []
        )
