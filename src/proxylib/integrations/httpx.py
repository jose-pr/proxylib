"""``httpx`` integration (needs ``httpx``; there is no proxylib extra for it).

``ProxyTransport`` and ``AsyncProxyTransport`` resolve the proxy for every
request from a proxy map and fail over along its answer. httpx has no global
hook, so a client opts in::

    client = httpx.Client(transport=ProxyTransport(proxymap))
    client = httpx.AsyncClient(transport=AsyncProxyTransport(proxymap))
"""

from __future__ import annotations

import threading
from typing import Any, Dict, Optional

from .. import _net
from ..exceptions import MissingExtraError
from ..proxy import Proxy, ProxyMap, alookup, lookup
from ._support import gateway_headers

__all__ = ("AsyncProxyTransport", "ProxyTransport")

# Built when first looked up, so importing proxylib never imports httpx; the
# classes subclass httpx's transports.


def _placeholder(name: str) -> type:
    class Placeholder:
        _placeholder = True

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            raise MissingExtraError(name, name="httpx")

    Placeholder.__name__ = Placeholder.__qualname__ = name
    return Placeholder


def _build() -> "Dict[str, type]":
    try:
        import httpx
    except ImportError:
        return {name: _placeholder(name) for name in __all__}

    # Errors raised before the request reached the server; a read or write
    # error is never retried elsewhere.
    failover_errors = (httpx.ProxyError, httpx.ConnectError, httpx.ConnectTimeout)

    class _Transports:
        """One inner transport per proxy URL and headers (``None`` for
        DIRECT, which also carries gateway requests), made on first use."""

        def __init__(self, factory: Any, kwargs: "Dict[str, Any]") -> None:
            self._factory = factory
            self._kwargs = kwargs
            self._by_proxy: "Dict[Any, Any]" = {}
            self._lock = threading.Lock()

        def get(self, proxy: "Optional[Proxy]") -> Any:
            if proxy is None or proxy.is_gateway:
                key: Any = None
                target: Any = None
            else:
                key = (proxy.uri(), proxy._headers)
                target = httpx.Proxy(proxy.uri(), headers=proxy.headers) if proxy._headers else proxy.uri()
            with self._lock:
                transport = self._by_proxy.get(key)
                if transport is None:
                    transport = self._factory(proxy=target, **self._kwargs)
                    self._by_proxy[key] = transport
                return transport

        def pop_all(self) -> "list":
            with self._lock:
                transports = list(self._by_proxy.values())
                self._by_proxy.clear()
            return transports

    def outgoing(request: "httpx.Request", entry: "Optional[Proxy]") -> "httpx.Request":
        """``request``, or for a gateway the request to send it: the gateway
        URL, a Host header of its own, the gateway's headers, the same body.
        The client gives the response the original request, so cookies and
        redirects belong to the target."""
        if entry is None or not entry.is_gateway:
            return request
        url = httpx.URL(entry.gateway_url(str(request.url)))
        headers = [("Host", url.netloc.decode("ascii"))]
        headers += [(k, v) for k, v in request.headers.multi_items() if k.lower() != "host"]
        headers += gateway_headers(entry)
        return httpx.Request(request.method, url, headers=headers, stream=request.stream, extensions=request.extensions)

    class ProxyTransport(httpx.BaseTransport):
        """An httpx transport that asks ``proxymap`` for every request.

        The answer's entries are tried in order, healthy ones first; with
        ``failover`` (the default), an entry that raises ``httpx.ProxyError``,
        ``ConnectError`` or ``ConnectTimeout`` is marked bad for
        ``bad_proxy_ttl`` seconds and the next is tried, and the last error
        is raised. A map with no opinion means DIRECT: chain an
        :class:`~proxylib.EnvProxyConfig` in front to honour the environment.
        ``transport_kwargs`` go to every inner ``httpx.HTTPTransport``.

        A proxy's ``headers`` go to that proxy only; a URL-prefix gateway gets
        the request at ``<gateway><URL>``, and the response keeps the original
        request, so cookies and redirects belong to the target.
        """

        def __init__(
            self,
            proxymap: ProxyMap,
            *,
            failover: bool = True,
            bad_proxy_ttl: float = 300.0,
            **transport_kwargs: Any,
        ) -> None:
            self.proxymap = proxymap
            self.failover = failover
            self.bad_proxy_ttl = bad_proxy_ttl
            self._transports = _Transports(httpx.HTTPTransport, transport_kwargs)

        def handle_request(self, request: "httpx.Request") -> "httpx.Response":
            try:
                entries = lookup(self.proxymap, str(request.url))
            except KeyError:
                entries = (None,)
            candidates = _net.order_by_health(entries) if self.failover else list(entries[:1])
            for index, entry in enumerate(candidates):
                try:
                    return self._transports.get(entry).handle_request(outgoing(request, entry))
                except failover_errors:
                    if not self.failover:
                        raise
                    _net.mark_bad(entry, ttl=self.bad_proxy_ttl)
                    if index == len(candidates) - 1:
                        raise
            raise RuntimeError("unreachable")

        def close(self) -> None:
            for transport in self._transports.pop_all():
                transport.close()

    class AsyncProxyTransport(httpx.AsyncBaseTransport):
        """:class:`ProxyTransport` for ``httpx.AsyncClient``; the map is read
        with :func:`~proxylib.alookup`, in a worker thread."""

        def __init__(
            self,
            proxymap: ProxyMap,
            *,
            failover: bool = True,
            bad_proxy_ttl: float = 300.0,
            **transport_kwargs: Any,
        ) -> None:
            self.proxymap = proxymap
            self.failover = failover
            self.bad_proxy_ttl = bad_proxy_ttl
            self._transports = _Transports(httpx.AsyncHTTPTransport, transport_kwargs)

        async def handle_async_request(self, request: "httpx.Request") -> "httpx.Response":
            try:
                entries = await alookup(self.proxymap, str(request.url))
            except KeyError:
                entries = (None,)
            candidates = _net.order_by_health(entries) if self.failover else list(entries[:1])
            for index, entry in enumerate(candidates):
                try:
                    return await self._transports.get(entry).handle_async_request(outgoing(request, entry))
                except failover_errors:
                    if not self.failover:
                        raise
                    _net.mark_bad(entry, ttl=self.bad_proxy_ttl)
                    if index == len(candidates) - 1:
                        raise
            raise RuntimeError("unreachable")

        async def aclose(self) -> None:
            for transport in self._transports.pop_all():
                await transport.aclose()

    return {"ProxyTransport": ProxyTransport, "AsyncProxyTransport": AsyncProxyTransport}


def __getattr__(name: str) -> Any:
    if name in __all__:
        classes = _build()
        if not getattr(classes[name], "_placeholder", False):
            globals().update(classes)
        return classes[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
