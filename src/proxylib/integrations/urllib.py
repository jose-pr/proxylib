"""``urllib.request`` integration.

``ProxyMapHandler`` resolves the proxy per-request from a ``ProxyMap``,
rather than a static ``{scheme: proxy_url}`` dict like the stdlib
``urllib.request.ProxyHandler`` normally uses -- the same upgrade
:class:`proxylib.integrations.requests.ProxyMapAdapter` is over a plain
proxies dict, and for the same reason: a static dict can't see the request's
host/path, which most ``ProxyMap`` rules (PAC scripts, path-dependent
NO_PROXY) need.
"""

from __future__ import annotations

# The alias form reads sys.modules, so this module imports even while
# urllib.request is still being bound on its package (proxylib imported from
# a post-import hook of urllib.request).
import urllib.request as urllib_request
from typing import Any

from urllib.error import URLError

from .. import _net
from ..proxy import Proxy, ProxyMap, _is_chain, _normalise, lookup
from ._support import gateway_headers, urllib_reason, usable

__all__ = ("ProxyMapHandler",)


class ProxyMapHandler(urllib_request.ProxyHandler):
    """A ``urllib.request`` handler that resolves proxies per-request from a ``ProxyMap``::

        opener = urllib.request.build_opener(ProxyMapHandler(proxymap))
        opener.open("https://example.com")

        # or, to affect every urllib.request.urlopen() call:
        urllib.request.install_opener(opener)

    When the map has no opinion (``KeyError``), the request uses the proxy
    ``urllib.request.getproxies()`` names for its scheme, as the standard
    ``ProxyHandler`` would -- read by proxylib when it is a PAC result or a
    gateway, which urllib cannot use itself.

    A URL-prefix gateway gets the request at ``<gateway><URL>`` through the
    opener's own HTTP(S) handler, and the response keeps the target URL, so
    the cookie processor and the redirect handler see the target.

    urllib speaks HTTP proxies only, and sends a proxy's headers through a
    tunnel unless they are ``Proxy-Authorization``: SOCKS proxies, and (for an
    https URL) proxies with other headers, are skipped, and an answer with
    nothing else raises :class:`~proxylib.UnsupportedProxyError`.
    """

    def __init__(self, proxymap: ProxyMap) -> None:
        # proxies={}: skip ProxyHandler.__init__'s per-protocol setattr(), which
        # would otherwise shadow the http_open/https_open/ftp_open methods
        # below with static, env-derived ones (its default when proxies=None).
        super().__init__(proxies={})
        self.proxymap = proxymap

    def _resolve(self, req: Any):
        try:
            # urllib cannot re-send through another proxy, so the healthiest
            # entry is the one used.
            entries = lookup(self.proxymap, req.full_url)
        except KeyError:
            # No opinion: urllib's own choice, from the environment (and, on
            # Windows and macOS, the system settings urllib reads).
            fallback = urllib_request.getproxies().get(req.type)
            if not fallback:
                return None
            if not _is_chain(fallback):
                return self.proxy_open(req, fallback, req.type)
            if req.host and urllib_request.proxy_bypass(req.host):
                return None
            entries = _normalise(fallback)
        proxy = _net.order_by_health(usable(entries, "urllib", req.full_url, urllib_reason))[0]
        if proxy is None:
            return None  # DIRECT: fall through to the default (non-proxying) handler.
        if proxy.is_gateway:
            return self._open_gateway(req, proxy)
        # Before proxy_open, which may open the request at once; unredirected,
        # so a redirect to another host does not carry them.
        for name, value in proxy._headers:
            req.add_unredirected_header(name, value)
        return self.proxy_open(req, proxy.uri(), req.type)

    def _open_gateway(self, req: Any, gateway: Proxy) -> Any:
        """Send ``req`` to ``gateway`` and return the response as the target's.

        The request's headers come along (the cookie processor has already
        added the target's cookies) except ``Host``, which becomes the
        gateway's."""
        target = req.full_url
        sent = urllib_request.Request(gateway.gateway_url(target), data=req.data, method=req.get_method())
        sent.headers = dict(req.headers)
        sent.unredirected_hdrs = {k: v for k, v in req.unredirected_hdrs.items() if k.lower() != "host"}
        for name, value in gateway_headers(gateway):
            sent.add_unredirected_header(name, value)
        sent.timeout = req.timeout
        kind = getattr(urllib_request, "HTTPSHandler", None) if sent.type == "https" else urllib_request.HTTPHandler
        handler = next((h for h in self.parent.handlers if kind is not None and isinstance(h, kind)), None)
        if handler is None:
            raise URLError(f"the opener has no handler for the gateway's {sent.type} scheme")
        response = getattr(handler, f"{sent.type}_open")(sent)
        response.url = target
        return response

    http_open = _resolve
    https_open = _resolve
    ftp_open = _resolve
