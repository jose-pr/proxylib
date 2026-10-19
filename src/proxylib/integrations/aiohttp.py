"""``aiohttp`` integration (needs ``aiohttp``; there is no proxylib extra for it).

aiohttp has no transport to plug a resolver into, so :class:`ProxySession`
wraps a ``ClientSession``: every request asks the proxy map and is sent with
``proxy=`` set to the chosen entry, failing over along the answer::

    async with ProxySession(proxymap) as session:
        async with session.get("https://example.com") as response:
            body = await response.text()
"""

from __future__ import annotations

import contextvars
from typing import Any, Awaitable, Callable, Optional, Tuple

from .. import _net
from ..exceptions import MissingExtraError
from ..proxy import Proxy, ProxyMap, _is_chain, _normalise, alookup

__all__ = ("ProxySession",)


def _aiohttp() -> Any:
    try:
        import aiohttp
    except ImportError:
        raise MissingExtraError("ProxySession", name="aiohttp") from None
    return aiohttp


# Set while a request is sent on a proxy proxylib chose, so the aiohttp patch
# target does not route it again (DIRECT is proxy=None to aiohttp).
_ROUTED: "contextvars.ContextVar[bool]" = contextvars.ContextVar("proxylib_aiohttp_routed", default=False)


def _failover_errors() -> tuple:
    aiohttp = _aiohttp()
    errors = [aiohttp.ClientConnectorError]
    if hasattr(aiohttp, "ConnectionTimeoutError"):
        errors.append(aiohttp.ConnectionTimeoutError)
    return tuple(errors)


async def _routed(
    send: "Callable[..., Awaitable[Any]]",
    proxymap: ProxyMap,
    url: str,
    proxy: Any,
    *,
    failover: bool = True,
    bad_proxy_ttl: float = 300.0,
) -> Any:
    """``send(proxy=...)`` with the proxy chosen for ``url``: from ``proxy``
    when it is a proxylib value, else from ``proxymap``; failing over along
    the answer. A plain proxy URL, no opinion, or a request already routed
    is sent with ``proxy`` as given."""
    if _ROUTED.get():
        return await send(proxy=proxy)
    entries: "Optional[Tuple[Optional[Proxy], ...]]"
    if proxy is not None:
        entries = None if isinstance(proxy, str) and not _is_chain(proxy) else _normalise(proxy)
    else:
        try:
            entries = await alookup(proxymap, url)
        except KeyError:
            entries = None
    if entries is None:
        return await send(proxy=proxy)
    errors = _failover_errors()
    candidates = _net.order_by_health(entries) if failover else list(entries[:1])
    for index, entry in enumerate(candidates):
        token = _ROUTED.set(True)
        try:
            return await send(proxy=entry.uri() if entry is not None else None)
        except errors:
            if not failover:
                raise
            _net.mark_bad(entry, ttl=bad_proxy_ttl)
            if index == len(candidates) - 1:
                raise
        finally:
            _ROUTED.reset(token)
    raise RuntimeError("unreachable")


class _Request:
    """The result of :meth:`ProxySession.request`: await it for the response,
    or use it in ``async with`` to release the response on exit."""

    __slots__ = ("_coro", "_response")

    def __init__(self, coro: Any) -> None:
        self._coro = coro
        self._response: Any = None

    def __await__(self):
        return self._coro.__await__()

    async def __aenter__(self) -> Any:
        self._response = await self._coro
        return self._response

    async def __aexit__(self, *exc_info: object) -> None:
        self._response.release()


class ProxySession:
    """An ``aiohttp.ClientSession`` whose requests take their proxy from
    ``proxymap`` (read with :func:`~proxylib.alookup`).

    ``session`` is the session to send through; by default one is made, with
    ``session_kwargs``, on the first request and closed by :meth:`close`. A
    session passed in is not closed. ``request(method, url, **kwargs)`` and
    ``get``/``post``/``put``/``patch``/``delete``/``head``/``options`` take
    ``ClientSession.request``'s arguments.

    The answer's entries are tried in order, healthy ones first; with
    ``failover`` (the default), one that fails to connect
    (``aiohttp.ClientConnectorError``, which includes
    ``ClientProxyConnectionError``, or a connect timeout) is marked bad for
    ``bad_proxy_ttl`` seconds and the next is tried, and the last error is
    raised. When the map has no opinion the request goes as aiohttp would
    send it. A ``proxy=`` argument that is a proxylib value (a PAC result such
    as ``"PROXY a:1; DIRECT"``, a list of proxies, a ``Proxy``) is resolved
    and failed over instead of the map; a plain proxy URL is aiohttp's own.

    aiohttp speaks HTTP proxies only (no SOCKS), and a session made with
    ``trust_env=True`` uses the environment's proxy for a DIRECT entry, so
    leave that off when the map decides.
    """

    def __init__(
        self,
        proxymap: ProxyMap,
        session: Any = None,
        *,
        failover: bool = True,
        bad_proxy_ttl: float = 300.0,
        **session_kwargs: Any,
    ) -> None:
        _aiohttp()
        if session is not None and session_kwargs:
            raise TypeError("pass either a session or ClientSession arguments, not both")
        self.proxymap = proxymap
        self.failover = failover
        self.bad_proxy_ttl = bad_proxy_ttl
        self._session = session
        self._owns = session is None
        self._session_kwargs = session_kwargs

    @property
    def session(self) -> Any:
        """The ``aiohttp.ClientSession``, made on first use."""
        if self._session is None:
            self._session = _aiohttp().ClientSession(**self._session_kwargs)
        return self._session

    async def close(self) -> None:
        """Close the session this wrapper made; a session passed in stays open."""
        if self._owns and self._session is not None:
            await self._session.close()

    async def __aenter__(self) -> "ProxySession":
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.close()

    def request(self, method: str, url: Any, **kwargs: Any) -> _Request:
        return _Request(self._request(method, url, **kwargs))

    def get(self, url: Any, **kwargs: Any) -> _Request:
        return self.request("GET", url, **kwargs)

    def post(self, url: Any, **kwargs: Any) -> _Request:
        return self.request("POST", url, **kwargs)

    def put(self, url: Any, **kwargs: Any) -> _Request:
        return self.request("PUT", url, **kwargs)

    def patch(self, url: Any, **kwargs: Any) -> _Request:
        return self.request("PATCH", url, **kwargs)

    def delete(self, url: Any, **kwargs: Any) -> _Request:
        return self.request("DELETE", url, **kwargs)

    def head(self, url: Any, **kwargs: Any) -> _Request:
        return self.request("HEAD", url, **kwargs)

    def options(self, url: Any, **kwargs: Any) -> _Request:
        return self.request("OPTIONS", url, **kwargs)

    async def _request(self, method: str, url: Any, **kwargs: Any) -> Any:
        proxy = kwargs.pop("proxy", None)

        async def send(**proxy_kwargs: Any) -> Any:
            return await self.session.request(method, url, **kwargs, **proxy_kwargs)

        return await _routed(
            send, self.proxymap, str(url), proxy, failover=self.failover, bad_proxy_ttl=self.bad_proxy_ttl
        )
