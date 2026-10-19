"""Which proxies each client integration can use.

An answer may hold entries a client cannot use: a URL-prefix gateway or a SOCKS
proxy for a client without them, or a proxy header a client would leak to the
server. Those entries are skipped and the rest tried in order; an answer with
none left raises :class:`~proxylib.UnsupportedProxyError`.
"""

from __future__ import annotations

import base64
import logging
from typing import Callable, Iterable, List, Optional, Tuple
from urllib.parse import urlsplit

from ..exceptions import UnsupportedProxyError
from ..proxy import Proxy

_log = logging.getLogger("proxylib.integrations")

# (proxy, request URL) -> why the client cannot use it, or None.
Reason = Callable[[Proxy, str], Optional[str]]


def usable(entries: "Iterable[Optional[Proxy]]", client: str, url: str, reason: Reason) -> "List[Optional[Proxy]]":
    """The entries ``client`` can use for ``url``, in order; DIRECT always can."""
    kept: "List[Optional[Proxy]]" = []
    refused: "List[Tuple[Proxy, str]]" = []
    for entry in entries:
        why = None if entry is None else reason(entry, url)
        if why is None:
            kept.append(entry)
        else:
            refused.append((entry, why))  # type: ignore[arg-type]
    if refused and not kept:
        raise UnsupportedProxyError(client, refused)
    for entry, why in refused:
        _log.debug("%s skips %s: %s", client, entry.url, why)
    return kept


def no_gateway_or_socks(client: str) -> Reason:
    """For a client that speaks HTTP proxies only."""

    def reason(proxy: Proxy, url: str) -> Optional[str]:
        if proxy.is_gateway:
            return f"{client} cannot send through a URL-prefix gateway"
        if proxy.scheme.startswith("socks"):
            return f"{client} speaks HTTP proxies only"
        return None

    return reason


def urllib_reason(proxy: Proxy, url: str) -> Optional[str]:
    if proxy.is_gateway:
        return None
    why = no_gateway_or_socks("urllib")(proxy, url)
    if why is None and urlsplit(url).scheme.lower() == "https":
        # urllib moves only Proxy-Authorization into the CONNECT; any other
        # header would travel through the tunnel to the server.
        if any(name.lower() != "proxy-authorization" for name, _ in proxy._headers):
            return "urllib sends only Proxy-Authorization to a tunnelling proxy"
    return why


def proxy_url_reason(proxy: Proxy, url: str) -> Optional[str]:
    """For a consumer that takes a proxy URL string and nothing else."""
    if proxy.is_gateway:
        return "a proxy URL string cannot name a URL-prefix gateway"
    if proxy._headers:
        return "a proxy URL string cannot carry proxy headers"
    return None


def gateway_headers(gateway: Proxy) -> "List[Tuple[str, str]]":
    """The headers a gateway request carries: the gateway's own, plus Basic
    ``Proxy-Authorization`` from its credentials unless one is given."""
    headers = list(gateway._headers)
    if gateway.username is not None and not any(n.lower() == "proxy-authorization" for n, _ in headers):
        token = f"{gateway.username}:{gateway.password or ''}".encode("utf-8")
        headers.append(("Proxy-Authorization", "Basic " + base64.b64encode(token).decode("ascii")))
    return headers
