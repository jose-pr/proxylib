"""Core proxy/URI types: parsing proxy strings and mapping request URLs to proxies.

``Proxy`` models a single ``scheme://[user[:pass]@]host[:port]`` proxy entry
(as found in ``PROXY``/env-var/PAC proxy strings). ``ProxyMap`` is the
protocol every proxy-selection strategy in this library implements
(``EnvProxyConfig``, ``pac.PAC``, ``SimpleProxyMap``): given a request URL it
returns the sequence of ``Proxy`` (or ``None`` for DIRECT) to try, in order.
"""

from __future__ import annotations

import re
import typing
from enum import Enum
from typing import Iterable, NamedTuple, Optional, Protocol, Sequence, Union, runtime_checkable
from urllib.parse import urlsplit

from . import netutils

ALPHA = r"A-Za-z"
DIGIT = r"0-9"
SCHEME = rf"[{ALPHA}][{ALPHA}{DIGIT}+-.]*"
PORT = rf"[{DIGIT}]*"
NON_BREAKING = rf"[^:@/;]"
AUTHORITY = (
    rf"(?:({NON_BREAKING}*)(?::({NON_BREAKING}*))?@)?({NON_BREAKING}+)(?::({PORT}))?"
)
DELIM = r"(?:;|^)\s*"


__all__ = ["Proxy", "ProxyMap", "UriSplit", "SimpleProxyMap"]


class UriSplit(Enum):
    """Regexes for splitting either a plain URI or a PAC ``PROXY ...; ...`` string."""

    Default = re.compile(rf"{DELIM}(?:(?:({SCHEME}):)?(?://{AUTHORITY})?\s*)")
    PAC = re.compile(rf"{DELIM}({SCHEME})(?:\s+(?:{AUTHORITY})?\s*)?")

    def match(self, uri: str):
        return self.value.match(uri)

    def findall(self, uri: str):
        return self.value.findall(uri)


class _URI(NamedTuple):
    scheme: str
    username: str
    password: str
    host: str
    port: Optional[int]

    @property
    def netloc(self) -> str:
        if self.port:
            return f"{self.host}:{self.port}"
        else:
            return self.host

    def resolved(self) -> "_URI":
        """Return a copy with the scheme's conventional port filled in if missing."""
        if self.port:
            return self
        return self.__class__(
            self.scheme,
            self.username,
            self.password,
            self.host,
            netutils.get_default_port(self.scheme),
        )

    def as_uri(self) -> str:
        authority = self.netloc
        userinfo = ""
        if self.username:
            userinfo = self.username
            if self.password:
                userinfo = userinfo + ":" + self.password

        if userinfo:
            authority = userinfo + "@" + self.netloc
        if self.scheme:
            return self.scheme + "://" + authority
        else:
            return "//" + authority

    @classmethod
    def from_str(
        cls,
        uri: str,
        format: UriSplit = UriSplit.Default,
    ) -> "Optional[_URI]":
        if not uri:
            return None
        match = format.match(uri)
        if not match or not any(match.groups()):
            # A bare hostname like "example.com" technically "matches" with
            # every group empty -- reject it clearly instead of building a
            # URI of Nones that crashes later.
            raise ValueError(f"Could not parse {uri!r} as a {format.name} URI")
        return cls(*match.groups())

    @classmethod
    def find_all(cls, uris: str, format: UriSplit = UriSplit.Default) -> "list[_URI]":
        return [cls(*uri) for uri in format.findall(uris)] if uris else []


class URL(_URI):
    _DEFAULT_SCHEME = "http"

    def __new__(
        cls, scheme: str, username: str, password: str, host: str, port: "str|int|None"
    ) -> "URL":
        scheme = (scheme or "").lower()
        if not scheme:
            scheme = cls._DEFAULT_SCHEME

        if port:
            port = int(port)

        return super().__new__(cls, scheme, username, password, host, port)


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
