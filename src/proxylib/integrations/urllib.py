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

from ..proxy import ProxyMap, lookup

__all__ = ("ProxyMapHandler",)


class ProxyMapHandler(urllib_request.ProxyHandler):
    """A ``urllib.request`` handler that resolves proxies per-request from a ``ProxyMap``::

        opener = urllib.request.build_opener(ProxyMapHandler(proxymap))
        opener.open("https://example.com")

        # or, to affect every urllib.request.urlopen() call:
        urllib.request.install_opener(opener)

    When the map has no opinion (``KeyError``), the request uses the proxy
    ``urllib.request.getproxies()`` names for its scheme, as the standard
    ``ProxyHandler`` would.
    """

    def __init__(self, proxymap: ProxyMap) -> None:
        # proxies={}: skip ProxyHandler.__init__'s per-protocol setattr(), which
        # would otherwise shadow the http_open/https_open/ftp_open methods
        # below with static, env-derived ones (its default when proxies=None).
        super().__init__(proxies={})
        self.proxymap = proxymap

    def _resolve(self, req: Any):
        try:
            proxy = lookup(self.proxymap, req.full_url)[0]
        except KeyError:
            # No opinion: urllib's own choice, from the environment (and, on
            # Windows and macOS, the system settings urllib reads).
            fallback = urllib_request.getproxies().get(req.type)
            return self.proxy_open(req, fallback, req.type) if fallback else None
        if proxy is None:
            return None  # DIRECT: fall through to the default (non-proxying) handler.
        return self.proxy_open(req, proxy.uri(), req.type)

    http_open = _resolve
    https_open = _resolve
    ftp_open = _resolve
