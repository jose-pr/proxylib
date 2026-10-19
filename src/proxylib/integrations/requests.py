"""``requests`` integration.

``ProxyMapAdapter`` (requires the ``requests`` package -- ``pip install
requests``; there is no proxylib extra for it) is
the recommended way to wire a ``ProxyMap`` into a ``requests.Session`` — it
hooks ``HTTPAdapter.send()``, so it sees the real request URL. For the
simpler proxies-dict style (``requests.get(url, proxies=...)``) use
:class:`proxylib.integrations.dict.ProxyDict`, which isn't requests-specific.
"""

from __future__ import annotations

import contextvars
import functools
import importlib
import inspect
from collections import ChainMap
from types import SimpleNamespace
from typing import Any, Callable, Optional, Tuple
from urllib.parse import urlsplit

from .. import _net
from ..exceptions import MissingExtraError
from ..proxy import Proxy, ProxyMap, _is_chain, _normalise, lookup
from ._support import gateway_headers
from .dict import ProxyDict

__all__ = ("ProxyMapAdapter",)

# (proxy URL as requests normalises it, headers) of the entry being sent, so
# proxy_manager_for() gives that proxy, and no other, its headers.
_CHOSEN: "contextvars.ContextVar[Optional[Tuple[str, tuple]]]" = contextvars.ContextVar(
    "proxylib_requests_proxy_headers", default=None
)

# HTTPAdapter.send(request, stream, timeout, verify, cert, proxies): callers
# such as cachecontrol's adapter pass these positionally.
_SEND_ARGS = ("stream", "timeout", "verify", "cert", "proxies")


def _send_kwargs(args: tuple, kwargs: "dict") -> "dict":
    """``HTTPAdapter.send``'s arguments after the request, all by name."""
    if len(args) > len(_SEND_ARGS):
        raise TypeError(f"send() takes at most {len(_SEND_ARGS) + 1} positional arguments after self")
    return {**dict(zip(_SEND_ARGS, args)), **kwargs}


# (trust_env, the caller's own proxies) of the session request being sent,
# recorded before requests merges the environment's proxies into them; None
# when the adapter is used outside a session _record_caller() wrapped.
_CALLER: "contextvars.ContextVar[Optional[Tuple[bool, Any]]]" = contextvars.ContextVar(
    "proxylib_requests_caller", default=None
)


def _record_caller(sessions: Any) -> "Callable[[], None]":
    """Wrap ``sessions.Session.request`` and ``send`` (``requests.sessions``, or
    a vendored copy) to record each request's ``trust_env`` and the proxies
    its caller gave (``proxies=`` over ``session.proxies``), so the adapter
    can tell them from the environment's. Returns the undo."""
    session_class = sessions.Session
    original_request, original_send = session_class.request, session_class.send
    signature = inspect.signature(original_request)

    def caller(session: Any, proxies: Any) -> "Tuple[bool, Any]":
        return bool(session.trust_env), sessions.merge_setting(proxies, session.proxies)

    def request(self: Any, *args: Any, **kwargs: Any) -> Any:
        try:
            proxies = signature.bind_partial(self, *args, **kwargs).arguments.get("proxies")
        except TypeError:
            proxies = None
        token = _CALLER.set(caller(self, proxies))
        try:
            return original_request(self, *args, **kwargs)
        finally:
            _CALLER.reset(token)

    def send(self: Any, request: Any, **kwargs: Any) -> Any:
        if _CALLER.get() is not None:
            return original_send(self, request, **kwargs)
        token = _CALLER.set(caller(self, kwargs.get("proxies")))
        try:
            return original_send(self, request, **kwargs)
        finally:
            _CALLER.reset(token)

    request.__wrapped__ = original_request  # type: ignore[attr-defined]
    send.__wrapped__ = original_send  # type: ignore[attr-defined]
    session_class.request = request
    session_class.send = send

    def undo() -> None:
        session_class.request = original_request
        session_class.send = original_send

    return undo


@functools.lru_cache(maxsize=None)
def _toolkit(package: str) -> Any:
    """The routing ``ProxyMapAdapter`` does, built over ``package`` --
    ``"requests"``, or a vendored copy such as ``"pip._vendor.requests"`` --
    and the urllib3 beside it. ``ImportError`` when it is not installed."""
    adapters = importlib.import_module(f"{package}.adapters")
    exceptions = importlib.import_module(f"{package}.exceptions")
    utils = importlib.import_module(f"{package}.utils")
    urllib3 = package[: -len("requests")] + "urllib3"
    poolmanager = importlib.import_module(f"{urllib3}.poolmanager")
    urllib3_errors = importlib.import_module(f"{urllib3}.exceptions")

    def failed_before_sending(exc: BaseException) -> bool:
        """The request never reached the server: the proxy (or, for DIRECT,
        the server) refused, timed out connecting, or was not reachable."""
        if isinstance(exc, (exceptions.ProxyError, exceptions.ConnectTimeout)):
            return True
        if not isinstance(exc, exceptions.ConnectionError) or isinstance(exc, exceptions.SSLError):
            return False
        reason = getattr(exc.args[0] if exc.args else None, "reason", None)
        return isinstance(
            reason,
            (urllib3_errors.NewConnectionError, urllib3_errors.ConnectTimeoutError, urllib3_errors.ProxyError),
        )

    def entries(
        proxymap: ProxyMap, url: str, proxies: Any, patched: bool
    ) -> "Optional[Tuple[Tuple[Optional[Proxy], ...], bool]]":
        """The entries to try and whether they outrank the caller's
        ``proxies``; ``None`` leaves the request to requests. ``patched``: the
        adapter a patch target installed, whose map a session that does not
        trust the environment ignores."""
        if isinstance(proxies, ProxyDict):
            try:
                return lookup(proxies.proxymap, url), True
            except KeyError:
                pass
        caller = _CALLER.get()
        if caller is not None and not isinstance(proxies, ProxyDict):
            trust_env, explicit = caller
            mine = utils.select_proxy(url, explicit) if explicit and not isinstance(explicit, ProxyDict) else None
            if mine is not None or (patched and not trust_env):
                # The caller's own proxy, or a session that ignores the
                # environment: requests decides, and proxylib reads only a
                # value requests cannot.
                value = mine if mine is not None else (utils.select_proxy(url, proxies) if proxies else None)
                if isinstance(value, str) and not _is_chain(value):
                    return None
                return (_normalise(value), True) if value else None
        try:
            return lookup(proxymap, url), False
        except KeyError:
            pass
        if isinstance(proxies, ProxyDict):
            return None
        value = utils.select_proxy(url, proxies) if proxies else None
        if isinstance(value, str) and not _is_chain(value):
            return None
        return (_normalise(value), True) if value else None

    def proxy_manager_for(adapter: Any, base: "Callable[..., Any]", proxy: str, proxy_kwargs: Any) -> Any:
        chosen = _CHOSEN.get()
        if chosen is None or chosen[0] != proxy:
            return base(proxy, **proxy_kwargs)
        # Keyed by the headers too, and kept in proxy_manager so close()
        # clears it.
        manager = adapter.proxy_manager.get(chosen)
        if manager is None:
            headers = adapter.proxy_headers(proxy)
            headers.update(chosen[1])
            manager = adapter.proxy_manager[chosen] = poolmanager.proxy_from_url(
                proxy,
                proxy_headers=headers,
                num_pools=adapter._pool_connections,
                maxsize=adapter._pool_maxsize,
                block=adapter._pool_block,
                **proxy_kwargs,
            )
        return manager

    def send_to_gateway(base: "Callable[..., Any]", request: Any, gateway: Proxy, kwargs: Any) -> Any:
        sent = request.copy()
        sent.url = gateway.gateway_url(request.url)
        for name, value in gateway_headers(gateway):
            sent.headers[name] = value
        response = base(sent, **{**kwargs, "proxies": {}})
        response.request = request
        response.url = request.url
        return response

    def send(
        base: "Callable[..., Any]",
        request: Any,
        kwargs: Any,
        proxymap: ProxyMap,
        *,
        failover: bool,
        bad_proxy_ttl: float,
        patched: bool = False,
    ) -> Any:
        """``base(request, **kwargs)`` -- the adapter's own send -- through
        the entries ``proxymap`` (or the caller's ``proxies``) gives."""
        proxies = kwargs.get("proxies") or {}
        parts = urlsplit(request.url)
        found = entries(proxymap, request.url, proxies, patched) if parts.hostname else None
        if found is None:
            return base(request, **kwargs)
        answer, ours_first = found
        # scheme://hostname is the most specific key select_proxy() reads.
        # The caller's proxies may be any mapping, so they are layered, not
        # copied.
        key = f"{parts.scheme}://{parts.hostname}"
        if not ours_first and getattr(proxies, "get", lambda _: None)(key) is not None:
            return base(request, **kwargs)
        candidates = _net.order_by_health(answer) if failover else list(answer[:1])
        for index, entry in enumerate(candidates):
            try:
                if entry is not None and entry.is_gateway:
                    return send_to_gateway(base, request, entry, kwargs)
                uri = entry.uri() if entry is not None else None
                ours = {key: uri}
                kwargs["proxies"] = ChainMap(ours, proxies) if ours_first else ChainMap(proxies, ours)
                chosen = (utils.prepend_scheme_if_needed(uri, "http"), entry._headers) if entry and entry._headers else None
                token = _CHOSEN.set(chosen)
                try:
                    return base(request, **kwargs)
                finally:
                    _CHOSEN.reset(token)
            except Exception as exc:
                if not (failover and failed_before_sending(exc)):
                    raise
                _net.mark_bad(entry, ttl=bad_proxy_ttl)
                if index == len(candidates) - 1:
                    raise
        raise RuntimeError("unreachable")

    return SimpleNamespace(HTTPAdapter=adapters.HTTPAdapter, send=send, proxy_manager_for=proxy_manager_for)


# requests is imported when ProxyMapAdapter is first looked up, not when
# proxylib is imported; the class subclasses requests' HTTPAdapter, so it can
# only be built once requests is importable.


def _build_adapter_class() -> type:
    try:
        from requests import PreparedRequest

        kit = _toolkit("requests")
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

    class ProxyMapAdapter(kit.HTTPAdapter):  # type: ignore[name-defined]
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

        A proxy's ``headers`` go to that proxy only (the ``CONNECT``, or the
        plain-http request to it). A URL-prefix gateway gets the request at
        ``<gateway><URL>``; the response keeps the original request and URL,
        so cookies and redirects belong to the target.

        When the map has no opinion, ``requests`` decides from the session's,
        the call's and the environment's ``proxies``, as without this adapter
        -- except that a proxylib value there (a PAC result such as ``"PROXY
        a:1; DIRECT"``, a list of proxies, a ``Proxy`` or a ``ProxyDict``) is
        resolved and failed over the same way. The caller's own proxies win
        over the map: a ``ProxyDict``, or an entry for the URL in the call's or
        the session's ``proxies`` (any key requests reads) when the session is
        wrapped by the requests patch target, else an entry at the
        ``scheme://hostname`` key; entries requests takes from the environment
        do not.
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
            # Set by the requests patch target on the adapters it mounts.
            self._patched = False
            super().__init__(*args, **kwargs)

        def proxy_manager_for(self, proxy: str, **proxy_kwargs: Any) -> Any:
            return kit.proxy_manager_for(self, super().proxy_manager_for, proxy, proxy_kwargs)

        def send(self, request: "PreparedRequest", *args: Any, **kwargs: Any):
            return kit.send(
                super().send,
                request,
                _send_kwargs(args, kwargs),
                self.proxymap,
                failover=self.failover,
                bad_proxy_ttl=self.bad_proxy_ttl,
                patched=self._patched,
            )

    return ProxyMapAdapter



def __getattr__(name: str) -> Any:
    if name == "ProxyMapAdapter":
        cls = _build_adapter_class()
        # Only the real class is kept: requests may be importable later (it
        # can be mid-import now).
        if not getattr(cls, "_placeholder", False):
            globals()["ProxyMapAdapter"] = cls
        return cls
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
