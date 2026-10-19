"""``requests`` integration.

``ProxyMapAdapter`` (requires the ``requests`` package -- ``pip install
requests``; there is no proxylib extra for it) is
the recommended way to wire a ``ProxyMap`` into a ``requests.Session`` — it
hooks ``HTTPAdapter.send()``, so it sees the real request URL. For the
simpler proxies-dict style (``requests.get(url, proxies=...)``) use
:class:`proxylib.integrations.dict.ProxyDict`, which isn't requests-specific.
"""

from __future__ import annotations

from collections import ChainMap
from typing import Any, Optional, Tuple
from urllib.parse import urlsplit

from .. import _net
from ..exceptions import MissingExtraError
from ..proxy import _PAC_RESULT, Proxy, ProxyMap, _normalise, lookup
from .dict import ProxyDict

__all__ = ("ProxyMapAdapter",)


# requests is imported when ProxyMapAdapter is first looked up, not when
# proxylib is imported; the class subclasses requests' HTTPAdapter, so it can
# only be built once requests is importable.


def _build_adapter_class() -> type:
    try:
        from requests import PreparedRequest
        from requests.adapters import HTTPAdapter
    except ImportError:

        class ProxyMapAdapter:  # type: ignore[no-redef]
            """Placeholder: ``requests`` is not installed."""

            _placeholder = True

            def __init__(self, *args: Any, **kwargs: Any) -> None:
                raise MissingExtraError("ProxyMapAdapter", name="requests")

        return ProxyMapAdapter

    # send()'s annotation names PreparedRequest; typing.get_type_hints looks
    # names up in this module's globals.
    globals().setdefault("PreparedRequest", PreparedRequest)

    from requests.exceptions import ConnectionError, ConnectTimeout, ProxyError, SSLError
    from requests.utils import select_proxy

    def failed_before_sending(exc: BaseException) -> bool:
        """The request never reached the server: the proxy (or, for DIRECT,
        the server) refused, timed out connecting, or was not reachable."""
        if isinstance(exc, (ProxyError, ConnectTimeout)):
            return True
        if not isinstance(exc, ConnectionError) or isinstance(exc, SSLError):
            return False
        from urllib3.exceptions import ConnectTimeoutError, NewConnectionError
        from urllib3.exceptions import ProxyError as URLLib3ProxyError

        reason = getattr(exc.args[0] if exc.args else None, "reason", None)
        return isinstance(reason, (NewConnectionError, ConnectTimeoutError, URLLib3ProxyError))

    class ProxyMapAdapter(HTTPAdapter):
        """A Transport Adapter that resolves the proxy per-request from a ``ProxyMap``.

        Sees the real ``request.url`` (scheme, host and path), matching what
        a PAC file's ``FindProxyForURL`` is meant to receive::

            session = requests.Session()
            adapter = ProxyMapAdapter(proxymap)
            session.mount("http://", adapter)
            session.mount("https://", adapter)

        With ``failover`` (the default), the answer's entries are tried in
        order, healthy ones first: an entry that fails before the request is
        sent (the proxy refuses or times out connecting) is marked bad for
        ``bad_proxy_ttl`` seconds and the next is tried; the last error is
        raised. DIRECT is an entry like any other. A read or write error never
        fails over, since the server may have received the request.

        When the map has no opinion, ``requests`` decides from the session's,
        the call's and the environment's ``proxies``, as without this adapter
        -- except that a proxylib value there (a PAC result such as ``"PROXY
        a:1; DIRECT"``, a list of proxies, a ``Proxy`` or a ``ProxyDict``) is
        resolved and failed over the same way. A caller's own entry at the
        ``scheme://hostname`` key ``requests`` reads first still wins over the
        map.
        """

        def __init__(
            self,
            proxymap: ProxyMap,
            *args: Any,
            failover: bool = True,
            bad_proxy_ttl: float = 300.0,
            **kwargs: Any,
        ) -> None:
            self.proxymap = proxymap
            self.failover = failover
            self.bad_proxy_ttl = bad_proxy_ttl
            super().__init__(*args, **kwargs)

        def _entries(self, url: str, proxies: Any) -> "Optional[Tuple[Tuple[Optional[Proxy], ...], bool]]":
            """The entries to try and whether they outrank the caller's
            ``proxies``; ``None`` leaves the request to requests."""
            try:
                return lookup(self.proxymap, url), False
            except KeyError:
                pass
            if isinstance(proxies, ProxyDict):
                try:
                    return lookup(proxies.proxymap, url), True
                except KeyError:
                    return None
            value = select_proxy(url, proxies) if proxies else None
            if isinstance(value, str) and not _is_chain(value):
                return None
            return (_normalise(value), True) if value else None

        def send(self, request: "PreparedRequest", **kwargs: Any):
            proxies = kwargs.get("proxies") or {}
            parts = urlsplit(request.url)
            found = self._entries(request.url, proxies) if parts.hostname else None
            if found is None:
                return super().send(request, **kwargs)
            entries, ours_first = found
            # scheme://hostname is the most specific key select_proxy() reads.
            # The caller's proxies may be any mapping (a ProxyDict), so they
            # are layered, not copied.
            key = f"{parts.scheme}://{parts.hostname}"
            candidates = _net.order_by_health(entries) if self.failover else list(entries[:1])
            for index, entry in enumerate(candidates):
                ours = {key: entry.uri() if entry is not None else None}
                kwargs["proxies"] = ChainMap(ours, proxies) if ours_first else ChainMap(proxies, ours)
                try:
                    return super().send(request, **kwargs)
                except Exception as exc:
                    if not (self.failover and failed_before_sending(exc)):
                        raise
                    _net.mark_bad(entry, ttl=self.bad_proxy_ttl)
                    if index == len(candidates) - 1:
                        raise

    return ProxyMapAdapter


def _is_chain(value: str) -> bool:
    """A proxies value that is a PAC result, not a proxy URL."""
    return ";" in value or _PAC_RESULT.match(value) is not None


def __getattr__(name: str) -> Any:
    if name == "ProxyMapAdapter":
        cls = _build_adapter_class()
        # Only the real class is kept: requests may be importable later (it
        # can be mid-import now).
        if not getattr(cls, "_placeholder", False):
            globals()["ProxyMapAdapter"] = cls
        return cls
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
