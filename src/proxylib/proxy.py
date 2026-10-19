"""Core types: ``Proxy`` (one proxy), the ``ProxyMap`` protocol (request URL to
the proxies to try) and ``lookup()``, which reads any proxy map's answer.

A proxy map is anything indexable by request URL -- a plain ``dict`` included.
``proxymap[url]`` answers ``None`` (DIRECT), one proxy, or an iterable of them
to try in order, where a ``None`` entry means DIRECT; a proxy is a ``Proxy``,
a URL string, a PAC result string, or any object with a ``url`` attribute.
``KeyError`` means the map has no opinion. :func:`lookup` turns every one of
those answers into a tuple of ``Proxy | None``.
"""

from __future__ import annotations

import re
import threading
import warnings
from collections.abc import Iterable as _AbcIterable
from collections.abc import Mapping
from typing import Any, Iterable, Optional, Protocol, Tuple, Union, runtime_checkable
from urllib.parse import quote, unquote, urlsplit

from . import _net
from .exceptions import ProxyParseError

__all__ = [
    "Proxy",
    "ProxyLike",
    "ProxyAnswer",
    "ProxyMap",
    "lookup",
    "SimpleProxyMap",
    "ChainProxyMap",
]

# Scheme aliases accepted in proxy URLs and PAC results: "proxy" is the PAC
# keyword for an HTTP proxy, and a bare "socks" is SOCKS v4 (Netscape PAC).
_SCHEME_ALIASES = {"proxy": "http", "socks": "socks4"}

# PAC result keywords (case-insensitive) and the proxy scheme each names.
_PAC_KEYWORDS = {
    "PROXY": "http",
    "HTTP": "http",
    "HTTPS": "https",
    "SOCKS": "socks4",
    "SOCKS4": "socks4",
    "SOCKS5": "socks5",
}
_PAC_RESULT = re.compile(r"\s*(DIRECT|PROXY|HTTPS?|SOCKS[45]?)(\s|;|$)", re.IGNORECASE)


class Proxy:
    """One proxy: ``scheme://[username[:password]@]host[:port]``. Immutable.

    ``url`` is the address without credentials (what logs and pathapi-style
    consumers read); ``uri()`` adds the credentials, percent-encoded. The
    password never appears in ``repr()`` or ``str()``.
    """

    __slots__ = ("scheme", "host", "port", "username", "password")

    scheme: str
    host: str
    port: Optional[int]
    username: Optional[str]
    password: Optional[str]

    def __init__(
        self,
        scheme: str,
        host: str,
        port: Optional[int] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
    ) -> None:
        scheme = (scheme or "").lower()
        scheme = _SCHEME_ALIASES.get(scheme, scheme)
        if not scheme:
            raise ProxyParseError("a proxy needs a scheme")
        if not host:
            raise ProxyParseError(f"a {scheme} proxy needs a host")
        if port is not None and not (isinstance(port, int) and 0 < port < 65536):
            raise ProxyParseError(f"invalid proxy port {port!r}")
        for name, value in (
            ("scheme", scheme),
            ("host", host.lower()),
            ("port", port),
            ("username", username or None),
            ("password", password or None),
        ):
            object.__setattr__(self, name, value)

    def __setattr__(self, name: str, value: Any) -> None:
        raise AttributeError(f"{type(self).__name__} is immutable")

    def __delattr__(self, name: str) -> None:
        raise AttributeError(f"{type(self).__name__} is immutable")

    def _key(self) -> tuple:
        return (self.scheme, self.host, self.port, self.username, self.password)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Proxy):
            return NotImplemented
        return self._key() == other._key()

    def __hash__(self) -> int:
        return hash(self._key())

    def __repr__(self) -> str:
        parts = [f"scheme={self.scheme!r}", f"host={self.host!r}"]
        if self.port is not None:
            parts.append(f"port={self.port!r}")
        if self.username is not None:
            parts.append(f"username={self.username!r}")
        if self.password is not None:
            parts.append("password='***'")
        return f"Proxy({', '.join(parts)})"

    def __str__(self) -> str:
        return self.url

    def __reduce__(self) -> tuple:
        return (type(self), self._key())

    @property
    def url(self) -> str:
        """``scheme://host[:port]``, no credentials; an IPv6 host is bracketed."""
        return f"{self.scheme}://{_net.join_host(self.host, self.port)}"

    def uri(self) -> str:
        """``url`` with the credentials, percent-encoded, for a client to connect with."""
        if self.username is None:
            return self.url
        userinfo = quote(self.username, safe="")
        if self.password is not None:
            userinfo += ":" + quote(self.password, safe="")
        return f"{self.scheme}://{userinfo}@{_net.join_host(self.host, self.port)}"

    @classmethod
    def parse(cls, text: str) -> "Proxy":
        """Parse a proxy URL (``http://user:pass@host:3128``). A missing scheme
        means ``http``; an IPv6 host is written in brackets. A path other than
        ``/`` is refused: that is a PAC location, not a proxy."""
        text = text.strip()
        if "://" not in text:
            text = "http://" + text
        try:
            parts = urlsplit(text)
            port = parts.port
        except ValueError as exc:
            raise ProxyParseError(f"invalid proxy URL {text!r}: {exc}") from None
        if parts.path not in ("", "/") or parts.query or parts.fragment:
            raise ProxyParseError(f"proxy URL {text!r} has a path; a PAC location is not a proxy")
        if not parts.hostname:
            raise ProxyParseError(f"proxy URL {text!r} has no host")
        return cls(
            parts.scheme,
            parts.hostname,
            port,
            unquote(parts.username) if parts.username else None,
            unquote(parts.password) if parts.password else None,
        )

    @classmethod
    def parse_pac_result(cls, text: str) -> "Tuple[Optional[Proxy], ...]":
        """Parse a PAC ``FindProxyForURL`` result (``"PROXY a:1; SOCKS5 b:2; DIRECT"``).

        Keywords are case-insensitive; ``DIRECT`` is ``None``. An entry with an
        unknown keyword or no usable host is dropped with a warning, and a
        result with nothing usable left is ``(None,)``, as browsers treat it.
        """
        entries: "list[Optional[Proxy]]" = []
        dropped: "list[str]" = []
        for raw in text.split(";"):
            entry = raw.strip()
            if not entry:
                continue
            keyword, *rest_parts = entry.split(None, 1)
            keyword = keyword.upper()
            rest = rest_parts[0] if rest_parts else ""
            if keyword == "DIRECT":
                entries.append(None)
                continue
            scheme = _PAC_KEYWORDS.get(keyword)
            host_port = _net.split_host_port(rest.strip()) if scheme and rest.strip() else None
            if scheme is None or host_port is None or not host_port[0]:
                dropped.append(entry)
                continue
            try:
                entries.append(cls(scheme, host_port[0], host_port[1]))
            except ProxyParseError:
                dropped.append(entry)
        if dropped:
            warnings.warn(f"ignoring unusable PAC result entries: {dropped!r}", stacklevel=2)
        return tuple(entries) or (None,)


ProxyLike = Union[Proxy, str, Any]
"""A ``Proxy``, a proxy URL or PAC result string, or any object with a ``url``
attribute (credentials from the URL, else its ``username``/``password``)."""

ProxyAnswer = Union[None, ProxyLike, Iterable[Optional[ProxyLike]]]
"""What ``proxymap[url]`` may return."""


class _ProxyMapMeta(type(Protocol)):  # type: ignore[misc]
    """Makes ``ProxyMap(src)`` build a map instead of failing as a Protocol.

    Intercepting the call here, rather than in ``ProxyMap.__new__``, means a
    map handed back by the factory is never run through ``__init__`` again.
    Subclasses are constructed as usual.
    """

    def __call__(cls, *args: Any, **kwargs: Any) -> Any:
        if cls is ProxyMap:
            return _from_source(*args, **kwargs)
        return super().__call__(*args, **kwargs)


@runtime_checkable
class ProxyMap(Protocol, metaclass=_ProxyMapMeta):
    """Anything indexable by request URL: ``proxymap[url]`` returns a
    :data:`ProxyAnswer` or raises ``KeyError`` for "no opinion".

    Structural: a ``dict`` and any class with ``__getitem__`` qualify without
    importing proxylib. Read an answer with :func:`lookup`.

    Calling it builds a map from a configured value, with no I/O:
    ``ProxyMap(None)``, a proxy URL, a PAC result string, a ``Proxy`` or a
    list/tuple of them gives a :class:`SimpleProxyMap`; a PAC location
    (``file:`` URL, inline script, or an ``http(s)`` URL with a path) gives a
    map that loads the PAC on its first lookup; anything else with
    ``__getitem__`` is returned as is.
    """

    def __getitem__(self, url: str, /) -> ProxyAnswer: ...


def _parse_text(text: str) -> "Tuple[Optional[Proxy], ...]":
    """A proxy string: a PAC result when it starts with a PAC keyword, else a
    proxy URL. Empty means DIRECT."""
    if not text.strip():
        return (None,)
    if "://" not in text and _PAC_RESULT.match(text):
        return Proxy.parse_pac_result(text)
    return (Proxy.parse(text),)


def _with_attribute_credentials(proxy: Proxy, source: Any) -> Proxy:
    if proxy.username is not None:
        return proxy
    username = getattr(source, "username", None)
    if not username:
        return proxy
    return Proxy(proxy.scheme, proxy.host, proxy.port, username, getattr(source, "password", None))


def _normalise_one(item: Any) -> "Tuple[Optional[Proxy], ...]":
    if item is None:
        return (None,)
    if isinstance(item, Proxy):
        return (item,)
    if isinstance(item, str):
        return _parse_text(item)
    url = getattr(item, "url", None)
    if isinstance(url, str):
        return tuple(
            p if p is None else _with_attribute_credentials(p, item) for p in _parse_text(url)
        )
    raise TypeError(f"cannot read a proxy from a {type(item).__name__}")


def _normalise(answer: Any) -> "Tuple[Optional[Proxy], ...]":
    if answer is None or isinstance(answer, (str, Proxy)) or isinstance(getattr(answer, "url", None), str):
        return _normalise_one(answer)
    if isinstance(answer, (bytes, Mapping)) or not isinstance(answer, _AbcIterable):
        raise TypeError(f"cannot read a proxy answer from a {type(answer).__name__}")
    entries: "list[Optional[Proxy]]" = []
    for item in answer:
        entries.extend(_normalise_one(item))
    return tuple(entries) or (None,)


def _requests_keys(url: str) -> "list[str]":
    # The keys requests.utils.select_proxy tries, most specific first.
    parts = urlsplit(url)
    scheme, host = parts.scheme, parts.hostname
    keys = [f"{scheme}://{host}", scheme, f"all://{host}", "all"] if host else [scheme, "all"]
    return [key for key in keys if key]


def lookup(proxymap: ProxyMap, url: str) -> "Tuple[Optional[Proxy], ...]":
    """The proxies ``proxymap`` says to try for ``url``, in order; ``None``
    means DIRECT. Never empty.

    A plain mapping that has no entry for the full URL is also asked with the
    keys ``requests`` uses (``scheme://host``, ``scheme``, ``all://host``,
    ``all``). Raises ``KeyError`` when the map has no opinion, and
    ``TypeError`` for an answer that names no proxy.
    """
    try:
        answer = proxymap[url]
    except KeyError:
        if not isinstance(proxymap, Mapping):
            raise KeyError(url) from None
        for key in _requests_keys(url):
            if key in proxymap:
                answer = proxymap[key]
                break
        else:
            raise KeyError(url) from None
    return _normalise(answer)


def _is_pac_location(text: str) -> bool:
    """A ``file:`` URL, inline PAC source, or an ``http(s)`` URL with a path
    beyond ``/`` (``http://wpad.corp/proxy.pac``); ``http://proxy:3128/`` is a
    proxy."""
    if "FindProxyForURL" in text:
        return True
    lowered = text.strip().lower()
    if lowered.startswith("file:"):
        return True
    if not lowered.startswith(("http://", "https://")):
        return False
    parts = urlsplit(text.strip())
    return parts.path not in ("", "/") or bool(parts.query)


class _LazyPacMap:
    """A PAC location, loaded on first lookup rather than when the map is made."""

    __slots__ = ("source", "_pac", "_lock")

    def __init__(self, source: str) -> None:
        self.source = source
        self._pac: Any = None
        self._lock = threading.Lock()

    def __repr__(self) -> str:
        return f"<PAC map for {self.source!r}>"

    def __getitem__(self, url: str) -> "Tuple[Optional[Proxy], ...]":
        if self._pac is None:
            with self._lock:
                if self._pac is None:
                    from . import pac

                    self._pac = pac._load_any(self.source)
        return lookup(self._pac, url)


def _from_source(src: Any = None) -> ProxyMap:
    """``ProxyMap(src)``; see :class:`ProxyMap`."""
    if isinstance(src, str) and _is_pac_location(src):
        return _LazyPacMap(src)
    if src is None or isinstance(src, (str, Proxy)):
        return SimpleProxyMap(src)
    if hasattr(src, "__getitem__") and not isinstance(src, (list, tuple)):
        return src
    return SimpleProxyMap(src)


class SimpleProxyMap(ProxyMap):
    """A proxy map with one fixed answer for every URL.

    Takes anything :func:`lookup` reads: ``None`` (DIRECT), a ``Proxy``, a
    proxy URL, a PAC result string (``"PROXY a:1; DIRECT"``) or an iterable of
    those. An empty iterable is DIRECT.
    """

    __slots__ = ("proxies",)

    def __init__(self, proxy: ProxyAnswer = None) -> None:
        self.proxies: "Tuple[Optional[Proxy], ...]" = _normalise(proxy)

    def __repr__(self) -> str:
        return f"SimpleProxyMap({self.proxies!r})"

    def __getitem__(self, url: str) -> "Tuple[Optional[Proxy], ...]":
        return self.proxies


class ChainProxyMap(ProxyMap):
    """Asks each map in order; the first with an opinion answers.

    A map's ``KeyError`` passes to the next one; any answer, DIRECT included,
    ends the chain. If every map has no opinion, neither does the chain, so a
    chain can be a link in a larger chain. Links can be any proxy map,
    ``dict``s included.
    """

    __slots__ = ("maps",)

    def __init__(self, *maps: ProxyMap) -> None:
        self.maps = maps

    def __repr__(self) -> str:
        return f"ChainProxyMap({', '.join(map(repr, self.maps))})"

    def __getitem__(self, url: str) -> "Tuple[Optional[Proxy], ...]":
        for proxymap in self.maps:
            try:
                return lookup(proxymap, url)
            except KeyError:
                continue
        raise KeyError(url)
