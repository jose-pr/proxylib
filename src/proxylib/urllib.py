"""``urllib.request`` integration.

``ProxyMapHandler`` resolves the proxy per-request from a ``ProxyMap``,
rather than a static ``{scheme: proxy_url}`` dict like the stdlib
``urllib.request.ProxyHandler`` normally uses -- the same upgrade
:class:`proxylib.requests.ProxyMapAdapter` is over a plain proxies dict, and
for the same reason: a static dict can't see the request's host/path, which
most ``ProxyMap`` rules (PAC scripts, path-dependent NO_PROXY) need.
"""

from __future__ import annotations

import urllib.request
from typing import Any

from .proxy import ProxyMap

__all__ = ("ProxyMapHandler",)


class ProxyMapHandler(urllib.request.ProxyHandler):
    """A ``urllib.request`` handler that resolves proxies per-request from a ``ProxyMap``::

        opener = urllib.request.build_opener(ProxyMapHandler(proxymap))
        opener.open("https://example.com")

        # or, to affect every urllib.request.urlopen() call:
        urllib.request.install_opener(opener)
    """

    def __init__(self, proxymap: ProxyMap) -> None:
        # proxies={}: skip ProxyHandler.__init__'s per-protocol setattr(), which
        # would otherwise shadow the http_open/https_open/ftp_open methods
        # below with static, env-derived ones (its default when proxies=None).
        super().__init__(proxies={})
        self.proxymap = proxymap

    def _resolve(self, req: Any):
        proxy = next(iter(self.proxymap.get(req.full_url, ()) or ()), None)
        if proxy is None:
            return None  # DIRECT: fall through to the default (non-proxying) handler.
        return self.proxy_open(req, proxy.as_uri(), req.type)

    http_open = _resolve
    https_open = _resolve
    ftp_open = _resolve
