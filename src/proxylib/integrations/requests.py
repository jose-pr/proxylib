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
from typing import Any
from urllib.parse import urlsplit

from ..exceptions import MissingExtraError
from ..proxy import ProxyMap, lookup

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

    class ProxyMapAdapter(HTTPAdapter):
        """A Transport Adapter that resolves the proxy per-request from a ``ProxyMap``.

        Sees the real ``request.url`` (scheme, host and path), matching what
        a PAC file's ``FindProxyForURL`` is meant to receive::

            session = requests.Session()
            adapter = ProxyMapAdapter(proxymap)
            session.mount("http://", adapter)
            session.mount("https://", adapter)

        Proxies explicitly passed to ``Session.proxies``/``request(proxies=...)``
        at the same ``scheme://hostname`` key ``requests`` itself resolves by
        (see ``requests.utils.select_proxy``) still take precedence over the
        ``ProxyMap`` result; a less-specific key (e.g. a bare ``"http"``
        entry, or an env-var-injected one when ``trust_env=True``) does not,
        since a per-request ``ProxyMap`` decision is more specific by
        definition -- that's the reason this adapter exists over a plain
        proxies dict.
        """

        def __init__(self, proxymap: ProxyMap, *args: Any, **kwargs: Any) -> None:
            self.proxymap = proxymap
            super().__init__(*args, **kwargs)

        def send(self, request: "PreparedRequest", **kwargs: Any):
            try:
                entries = lookup(self.proxymap, request.url)
            except KeyError:
                # No opinion: requests decides from `proxies` (the session's,
                # the call's and the environment's), untouched.
                return super().send(request, **kwargs)
            parts = urlsplit(request.url)
            if parts.hostname:
                resolved = entries[0]
                # scheme://hostname is the most specific key select_proxy()
                # reads, so it outranks the scheme-level keys requests adds
                # from the environment; a caller's own entry for that key
                # still wins. None means DIRECT. The caller's proxies may be
                # any mapping (a ProxyDict), so they are layered, not copied.
                ours = {f"{parts.scheme}://{parts.hostname}": resolved.uri() if resolved is not None else None}
                kwargs["proxies"] = ChainMap(kwargs.get("proxies") or {}, ours)
            return super().send(request, **kwargs)

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
