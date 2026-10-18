"""DNS + HTTP WPAD (Web Proxy Auto-Discovery) fallback, used by ``auto_proxy()``
when no explicit OS/env proxy configuration is found.

DHCP option 252 discovery is intentionally not implemented: it needs raw
access to the OS's DHCP lease data, which has no portable stdlib-only path.
"""

from __future__ import annotations

import socket
import time
from typing import Dict, Iterator, List, Optional, Tuple
from urllib.error import URLError

from .. import _net
from ..exceptions import PACError
from . import PacProxyMap, load

__all__ = ("discover",)

# Discovery results memoized per fqdn: (monotonic timestamp, result).
# Negative results (None) are cached too -- that's the case that matters
# most, since "auto-detect on, but no WPAD server" would otherwise re-walk
# DNS lookups and HTTP probes with multi-second timeouts on every call.
_cache: "Dict[str, Tuple[float, Optional[PacProxyMap]]]" = {}


@_net.register_cache
def _clear_cache() -> None:
    _cache.clear()


def _resolve_with_timeout(host: str, timeout: float) -> "Optional[str]":
    ip = _net.resolve_ip(host, timeout=timeout)
    return str(ip) if ip is not None else None


# Second-level labels that country-code registries sell names under
# (example.co.uk, example.com.au, example.ne.jp). Anyone can register
# wpad.<label>.<cc> there, so devolution must stop above them.
_CC_SECOND_LEVEL = frozenset(
    (
        "ac", "ad", "asn", "biz", "co", "com", "ed", "edu", "firm", "gen", "go",
        "gob", "gov", "govt", "gr", "id", "idv", "ind", "info", "lg", "ltd", "me",
        "mil", "muni", "ne", "net", "nhs", "nom", "or", "org", "pe", "per", "plc",
        "police", "re", "res", "sch", "school", "web",
    )
)  # fmt: skip


def _is_public_suffix(labels: "List[str]") -> bool:
    if len(labels) < 2:
        return True
    return len(labels) == 2 and len(labels[1]) == 2 and labels[0].lower() in _CC_SECOND_LEVEL


def _candidate_domains(fqdn: str) -> Iterator[str]:
    """Parent domains of fqdn, most specific first, per the WPAD draft's search order.

    Stops before a public suffix -- a bare TLD or a ccTLD registry level such
    as ``co.uk`` -- since ``wpad.co.uk`` belongs to whoever registered it.
    """
    labels = fqdn.rstrip(".").split(".")
    for i in range(1, len(labels)):
        if _is_public_suffix(labels[i:]):
            return
        yield ".".join(labels[i:])


def _discover(fqdn: str, timeout: float, on_missing_engine: str) -> "Optional[PacProxyMap]":
    for domain in _candidate_domains(fqdn):
        host = f"wpad.{domain}"
        if _resolve_with_timeout(host, timeout) is None:
            continue
        try:
            return load(
                f"http://{host}/wpad.dat", timeout=timeout, on_missing_engine=on_missing_engine
            )
        except (URLError, OSError, ValueError, PACError):
            continue
    return None


def discover(
    fqdn: "Optional[str]" = None,
    *,
    timeout: float = 3.0,
    cache_ttl: "Optional[float]" = 300.0,
    on_missing_engine: str = "raise",
) -> "Optional[PacProxyMap]":
    """Try each ``http://wpad.<domain>/wpad.dat`` from most to least specific.

    Returns a :class:`PacProxyMap` for the first PAC that loads, or ``None``.
    A domain whose PAC fails to download or to run is skipped; with no JS
    engine installed, :class:`MissingExtraError` is raised unless
    ``on_missing_engine="direct"``. Results, failures included, are cached
    per fqdn for ``cache_ttl`` seconds (``0``/``None``: probe afresh).
    """
    fqdn = fqdn or socket.getfqdn()
    if cache_ttl:
        cached = _cache.get(fqdn)
        if cached is not None and (time.monotonic() - cached[0]) < cache_ttl:
            return cached[1]
    result = _discover(fqdn, timeout, on_missing_engine)
    if cache_ttl:
        _cache[fqdn] = (time.monotonic(), result)
    return result
