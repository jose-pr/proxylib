"""DNS + HTTP WPAD (Web Proxy Auto-Discovery) fallback, used by ``auto_proxy()``
when no explicit OS/env proxy configuration is found.

DHCP option 252 discovery is intentionally not implemented: it needs raw
access to the OS's DHCP lease data, which has no portable stdlib-only path.
"""

from __future__ import annotations

import socket
import time
from typing import Dict, Iterator, Optional, Tuple
from urllib.error import URLError

from . import PAC, load

__all__ = ("discover",)

# Discovery results memoized per fqdn: (monotonic timestamp, result).
# Negative results (None) are cached too -- that's the case that matters
# most, since "auto-detect on, but no WPAD server" would otherwise re-walk
# DNS lookups and HTTP probes with multi-second timeouts on every call.
_cache: "Dict[str, Tuple[float, Optional[PAC]]]" = {}


def _candidate_domains(fqdn: str) -> Iterator[str]:
    """Parent domains of fqdn, most specific first, per the WPAD draft's search order.

    The final (bare TLD) label is skipped so discovery doesn't try
    ``wpad.com``/``wpad.co.uk``-style public suffixes.
    """
    labels = fqdn.split(".")
    for i in range(1, len(labels) - 1):
        yield ".".join(labels[i:])


def _discover(fqdn: str, timeout: float, **urllib_kwds) -> "Optional[PAC]":
    for domain in _candidate_domains(fqdn):
        host = f"wpad.{domain}"
        try:
            socket.gethostbyname(host)
        except OSError:
            continue
        try:
            return load(f"http://{host}/wpad.dat", timeout=timeout, **urllib_kwds)
        except (URLError, OSError, ValueError):
            continue
    return None


def discover(
    fqdn: "Optional[str]" = None,
    timeout: float = 3.0,
    cache_ttl: "float|None" = 300.0,
    **urllib_kwds,
) -> "Optional[PAC]":
    """Try each ``http://wpad.<domain>/wpad.dat`` from most to least specific.

    Returns the first successfully loaded PAC, or None if discovery fails.
    Results (including failures) are cached per fqdn for ``cache_ttl``
    seconds; pass ``cache_ttl=0`` (or ``None``) to force a fresh probe.
    """
    fqdn = fqdn or socket.getfqdn()
    if cache_ttl:
        cached = _cache.get(fqdn)
        if cached is not None and (time.monotonic() - cached[0]) < cache_ttl:
            return cached[1]
    result = _discover(fqdn, timeout, **urllib_kwds)
    if cache_ttl:
        _cache[fqdn] = (time.monotonic(), result)
    return result
