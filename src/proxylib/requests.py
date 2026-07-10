"""``requests`` integration.

``ProxyMapAdapter`` (needs the ``requests`` extra: ``proxylib[requests]``) is
the recommended way to wire a ``ProxyMap`` into a ``requests.Session`` — it
hooks ``HTTPAdapter.send()``, so it sees the real request URL. For the
simpler proxies-dict style (``requests.get(url, proxies=...)``) use
:class:`proxylib.proxy.ProxyDict`, which isn't requests-specific;
``RequestsProxies`` remains as its backward-compatible alias.
"""

from __future__ import annotations

from typing import Any

from .proxy import ProxyDict, ProxyMap

__all__ = ("RequestsProxies", "ProxyMapAdapter")

# Backward-compatible alias: this class predates the rename to the
# library-agnostic ProxyDict (it never actually depended on requests).
RequestsProxies = ProxyDict


try:
    from requests import PreparedRequest
    from requests.adapters import HTTPAdapter

    class ProxyMapAdapter(HTTPAdapter):
        """A Transport Adapter that resolves the proxy per-request from a ``ProxyMap``.

        Sees the real ``request.url`` (scheme, host and path), matching what
        a PAC file's ``FindProxyForURL`` is meant to receive::

            session = requests.Session()
            adapter = ProxyMapAdapter(proxymap)
            session.mount("http://", adapter)
            session.mount("https://", adapter)

        Proxies explicitly passed to ``Session.proxies``/``request(proxies=...)``
        still take precedence over the ``ProxyMap`` result.
        """

        def __init__(self, proxymap: ProxyMap, *args: Any, **kwargs: Any) -> None:
            self.proxymap = proxymap
            super().__init__(*args, **kwargs)

        def send(self, request: "PreparedRequest", **kwargs: Any):
            proxies = dict(kwargs.get("proxies") or {})
            resolved = next(iter(self.proxymap.get(request.url, ()) or ()), None)
            if resolved is not None:
                proxies.setdefault(resolved.scheme, resolved.as_uri())
                proxies.setdefault("all", resolved.as_uri())
            kwargs["proxies"] = proxies
            return super().send(request, **kwargs)

except ImportError:
    ProxyMapAdapter = None
