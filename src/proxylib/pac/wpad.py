"""DNS + HTTP WPAD (Web Proxy Auto-Discovery) fallback, used by ``auto_proxy()``
when no explicit OS/env proxy configuration is found.

DHCP option 252 discovery is intentionally not implemented: it needs raw
access to the OS's DHCP lease data, which has no portable stdlib-only path.
"""

from __future__ import annotations

import socket
from typing import Iterator, Optional
from urllib.error import URLError

from . import PAC, load

__all__ = ("discover",)


def _candidate_domains(fqdn: str) -> Iterator[str]:
    """Parent domains of fqdn, most specific first, per the WPAD draft's search order.

    The final (bare TLD) label is skipped so discovery doesn't try
    ``wpad.com``/``wpad.co.uk``-style public suffixes.
    """
    labels = fqdn.split(".")
    for i in range(1, len(labels) - 1):
        yield ".".join(labels[i:])


def discover(fqdn: "Optional[str]" = None, timeout: float = 3.0, **urllib_kwds) -> "Optional[PAC]":
    """Try each ``http://wpad.<domain>/wpad.dat`` from most to least specific.

    Returns the first successfully loaded PAC, or None if discovery fails.
    """
    fqdn = fqdn or socket.getfqdn()
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
