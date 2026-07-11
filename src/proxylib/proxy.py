"""Core proxy/URI types: parsing proxy strings and mapping request URLs to proxies.

``Proxy`` models a single ``scheme://[user[:pass]@]host[:port]`` proxy entry
(as found in ``PROXY``/env-var/PAC proxy strings). ``ProxyMap`` is the
protocol every proxy-selection strategy in this library implements
(``EnvProxyConfig``, ``pac.PAC``, ``SimpleProxyMap``): given a request URL it
returns the sequence of ``Proxy`` (or ``None`` for DIRECT) to try, in order.
"""

from __future__ import annotations

import threading
import time
import typing
from typing import Dict, Iterable, Optional, Protocol, Sequence, Tuple, Union, runtime_checkable
from urllib.parse import urlsplit, urlunsplit

from ._uri import URL, UriSplit, _URI
from .netutils import first_working_proxy

__all__ = [
    "Proxy",
    "ProxyMap",
    "UriSplit",
    "SimpleProxyMap",
    "ChainProxyMap",
    "ConfigurableProxyMap",
]


class Proxy(_URI):
    """A single proxy authority, e.g. ``http://user:pass@proxy.example.com:8080``.

    ``Proxy("direct", ...)`` returns ``None`` (the sentinel used everywhere in
    this library to mean "connect without a proxy") rather than an instance.
    """

    _DEFAULT_SCHEME = "http"

    def __new__(
        cls,
        scheme: str,
        username: "str|None",
        password: "str|None",
        host: "str|None",
        port: "str|int|None",
    ) -> "Optional[Proxy]":
        scheme = (scheme or "").lower()
        if scheme == "direct":
            return None
        elif scheme == "proxy":
            scheme = "http"
        elif scheme == "socks":
            scheme = "socks4"
        elif not scheme:
            scheme = cls._DEFAULT_SCHEME

        if port:
            port = int(port)

        return super().__new__(
            cls, scheme, username or "", password or "", host or "", port or 0
        )

    @property
    def url(self) -> str:
        return f"{self.scheme}://{self.netloc}"


@runtime_checkable
class ProxyMap(Protocol):
    """Protocol for "given a request URL, which proxies should I try?".

    Calling ``ProxyMap(src)`` is a small factory: a plain proxy-authority
    string builds a ``SimpleProxyMap``, but a string that looks like a URL to
    a PAC file/script is loaded as one (see :mod:`proxylib.pac`).

    **Result contract** (every implementation must follow this so chaining
    multiple maps together is meaningful):

    - ``__getitem__`` **raises** ``KeyError`` to mean *no decision* -- this
      map has no opinion on the request, distinct from an explicit answer.
      A fallback/chain should try the next map.
    - ``__getitem__`` **yields** ``None`` as an entry to mean *DIRECT* (no
      proxy) -- an explicit, definitive answer, not "no opinion".
    - ``__getitem__`` **yields** a ``Proxy`` entry to mean *use this proxy*.

    Per-implementation notes: ``SimpleProxyMap`` and ``pac.PAC`` are always
    definitive (constructed with, or computed, an explicit answer) and never
    raise ``KeyError``. ``EnvProxyConfig`` raises ``KeyError`` for a scheme
    with no configured env proxy (env vars can't express "explicitly
    DIRECT", only "set" or "absent").
    """

    def __new__(cls, *args, **kwargs):
        src: "str|Proxy|None" = args[0] if args else None
        if cls is ProxyMap:
            if isinstance(src, str):
                looks_like_pac_source = _looks_like_pac_source(src)
                if looks_like_pac_source:
                    from . import pac

                    return pac.load(src)
            return object.__new__(SimpleProxyMap)

        return object.__new__(cls)

    def __getitem__(self, uri: str) -> Iterable[Optional[Proxy]]:
        raise NotImplementedError()

    def get(self, uri: str, default=None):
        try:
            return self[uri]
        except KeyError:
            return default

    def __contains__(self, key: object) -> bool:
        try:
            self[key]
            return True
        except KeyError:
            return False

    def __enter__(self):
        # Local import: patching.py imports proxy.py, so a top-level import
        # here would be circular (same reason ProxyMap.__new__ locally
        # imports `pac`).
        from . import patching

        patching.patch(self)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        from . import patching

        patching.unpatch()
        return False


def _looks_like_pac_source(src: str) -> bool:
    """Heuristic: does this string point at a PAC file/URL rather than name a single proxy authority?

    A bare authority like ``http://proxy:8080`` parses as exactly one
    ``Proxy`` whose ``netloc`` is the whole (non-scheme) part of ``src``. If
    ``src`` has more to it than that authority (a path, e.g.
    ``http://internal/proxy.pac``), or it's a ``file:`` reference, treat it
    as a PAC source instead.
    """
    try:
        proxies = Proxy.find_all(src)
    except Exception:
        return False
    if len(proxies) != 1:
        return False
    proxy = proxies[0]
    netloc = proxy.netloc
    # A single trailing "/" is not a path: HTTP_PROXY-style values are very
    # commonly written "http://proxy:8080/", and treating that as a PAC URL
    # meant the factory tried to fetch the proxy itself as a PAC script.
    stripped = src[:-1] if src.endswith("/") else src
    has_path_beyond_authority = proxy.scheme in ("http", "https", "file") and netloc and (
        not stripped.endswith(netloc)
    )
    is_bare_file_authority = proxy.scheme == "file" and not netloc
    return bool(has_path_beyond_authority) or is_bare_file_authority


class SimpleProxyMap(ProxyMap):
    """A ``ProxyMap`` that always returns the same fixed proxy (or list of proxies)."""

    def __init__(self, proxy: "Proxy|Sequence[Optional[Proxy]]|str|None" = None) -> None:
        if isinstance(proxy, str):
            # PAC-style strings ("DIRECT", "PROXY host:port; DIRECT") have no
            # "://"; URL-style strings ("http://host:port", the conventional
            # HTTP_PROXY/HTTPS_PROXY env var format) do.
            fmt = UriSplit.Default if "://" in proxy else UriSplit.PAC
            proxy = Proxy.find_all(proxy, fmt)
        if proxy is None or isinstance(proxy, Proxy):
            self.proxies: Sequence[Optional[Proxy]] = (proxy,)
        elif isinstance(proxy, typing.Sequence):
            self.proxies = proxy
        else:
            self.proxies = (proxy,)

    def __getitem__(self, uri: str) -> Sequence[Optional[Proxy]]:
        return self.proxies


class ChainProxyMap(ProxyMap):
    """Tries each ``ProxyMap`` in order; the first one with an opinion wins.

    Works *because of* the codified result contract (see ``ProxyMap``'s
    docstring): a constituent map's ``KeyError`` means "no opinion, try the
    next one", while a ``[None]``/``[Proxy]`` result is definitive and
    stops the chain immediately -- e.g. ``ChainProxyMap(EnvProxyConfig(...),
    pac_map)`` falls through to the PAC map only when the env config has no
    proxy configured for that scheme, not merely when it resolves to DIRECT.

    If every constituent map raises ``KeyError``, the chain does too --
    "no opinion" composes, so a ``ChainProxyMap`` can itself be one link in
    a larger chain.
    """

    __slots__ = ("maps",)

    def __init__(self, *maps: ProxyMap) -> None:
        self.maps = maps

    def __getitem__(self, uri: str) -> Iterable[Optional[Proxy]]:
        for proxymap in self.maps:
            try:
                return proxymap[uri]
            except KeyError:
                continue
        raise KeyError(uri)


class ConfigurableProxyMap(ProxyMap):
    """Decorates any ``ProxyMap`` with caching, active probing, round-robin
    selection, browser-style privacy stripping, and an implicit local bypass.

    All features are opt-in and independent; the decorated map's own result
    contract (``KeyError``/``[None]``/``[Proxy]``) is preserved throughout.
    """

    def __init__(
        self,
        proxymap: ProxyMap,
        *,
        cache_ttl: "float|None" = None,
        probe: bool = False,
        probe_timeout: float = 5.0,
        round_robin: bool = False,
        browser_compatibility: bool = False,
        bypass_local: bool = False,
        no_proxy: "Iterable[str]|None" = None,
    ) -> None:
        self.proxymap = proxymap
        self.cache_ttl = cache_ttl
        self.probe = probe
        self.probe_timeout = probe_timeout
        self.round_robin = round_robin
        self.browser_compatibility = browser_compatibility

        # Local import: env.py imports proxy.py, so importing it back at
        # module level here would be circular (same reason ProxyMap.__new__
        # locally imports `pac`). Reused rather than reimplemented: an
        # EnvProxyConfig(None, None, rules) has no configured http/https
        # proxy, so it raises KeyError for anything NOT matched by `rules`
        # and returns [None] for anything that is -- exactly the "bypass
        # check" primitive this class needs, complete with CIDR/<local>
        # matching and the Phase 2 global no_proxy defaults, for free.
        bypass_rules = list(no_proxy or ())
        if bypass_local:
            # <local> already covers loopback + link-local (env.py shares
            # netutils.is_loopback_or_link_local for that) plus same-subnet
            # addresses -- a superset of what bypass_local asks for.
            bypass_rules.append("<local>")
        self._bypass_checker: "Optional[ProxyMap]" = None
        if bypass_rules:
            from .env import EnvProxyConfig

            self._bypass_checker = EnvProxyConfig(None, None, bypass_rules)

        self._cache: "Dict[str, Tuple[float, tuple]]" = {}
        self._round_robin_index = 0
        self._lock = threading.Lock()

    def clear_cache(self) -> None:
        self._cache.clear()

    def _effective_url(self, url: str) -> str:
        """Apply browser-style privacy stripping: for HTTPS, strip the
        path/query/fragment before delegating (matches Chrome 52+/Firefox
        53+ behavior toward PAC scripts -- HTTPS request details are
        considered sensitive to leak to a PAC server)."""
        if not self.browser_compatibility:
            return url
        parsed = urlsplit(url)
        if parsed.scheme != "https":
            return url
        return urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))

    def __getitem__(self, url: str) -> Iterable[Optional[Proxy]]:
        if self._bypass_checker is not None:
            try:
                return self._bypass_checker[url]
            except KeyError:
                pass  # not bypassed -- fall through to normal resolution

        effective_url = self._effective_url(url)

        if self.cache_ttl:
            cached = self._cache.get(effective_url)
            if cached is not None and (time.monotonic() - cached[0]) < self.cache_ttl:
                return cached[1]

        result: tuple = tuple(self.proxymap[effective_url])

        if self.round_robin and len(result) > 1:
            with self._lock:
                index = self._round_robin_index % len(result)
                self._round_robin_index += 1
            result = result[index:] + result[:index]

        if self.probe:
            try:
                result = (first_working_proxy(result, timeout=self.probe_timeout),)
            except LookupError:
                # No candidate was reachable -- a resolution failure, not a
                # DIRECT decision (same reasoning as LibProxyMap/
                # CFNetworkProxyMap's timeout/failure handling).
                raise KeyError(url)

        if self.cache_ttl:
            self._cache[effective_url] = (time.monotonic(), result)

        return result
