"""``requests`` integration.

``ProxyMapAdapter`` (needs the ``requests`` extra: ``proxylib[requests]``) is
the recommended way to wire a ``ProxyMap`` into a ``requests.Session`` — it
hooks ``HTTPAdapter.send()``, so it sees the real request URL. ``RequestsProxies``
is kept for backward compatibility as a ``Session.proxies``-dict shim.
"""

from __future__ import annotations

from typing import Any

from .proxy import ProxyMap

__all__ = ("RequestsProxies", "ProxyMapAdapter")


class RequestsProxies(ProxyMap):
    """Duck-types as a ``requests.Session.proxies`` dict.

    Caveat: ``requests.utils.select_proxy`` looks entries up by
    ``"{scheme}://{host}"`` / ``"{scheme}"`` / ``"all"``, not by the full
    request URL, so this never sees the request path — any ``ProxyMap`` rule
    that depends on it (most PAC scripts, some NO_PROXY setups) won't behave
    correctly. Prefer :class:`ProxyMapAdapter`.
    """

    __slots__ = ("proxymap",)

    def __init__(self, proxymap: ProxyMap) -> None:
        self.proxymap = proxymap

    def __getitem__(self, uri: str) -> str:
        try:
            proxy = next(iter(self.proxymap[uri]))
            if proxy is None:
                raise KeyError(uri)
            return proxy.as_uri()
        except StopIteration:
            raise KeyError(uri)

    def copy(self) -> "RequestsProxies":
        return RequestsProxies(self.proxymap)

    def setdefault(self, url: str, value: str) -> None:
        pass


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
