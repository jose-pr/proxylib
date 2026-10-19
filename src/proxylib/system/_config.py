"""``ProxyConfig``: an OS's proxy settings as data, and the proxy map that
carries them out."""

from __future__ import annotations

import functools
import threading
import time
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Callable, Dict, List, Literal, Mapping, Optional, Tuple, Union
from urllib.parse import urlsplit

from .. import _net
from ..bypass import BypassRules
from ..exceptions import PACError, ProxyParseError
from ..proxy import ChainProxyMap, Proxy, ProxyMap, SimpleProxyMap, lookup
from ..wrappers import Bypass
from ._run import log

__all__ = ("ProxyConfig",)

_STATES = ("direct", "configured", "unset")

# A websocket URL uses the proxy of the HTTP scheme it upgrades from.
_SCHEME_FALLBACK = {"ws": "http", "wss": "https"}

# Seconds before a PAC or WPAD source that failed is tried again; until then
# the next source answers.
_RETRY_AFTER = 30.0


@dataclass(frozen=True)
class ProxyConfig:
    """This machine's proxy settings, as one OS or desktop stores them.

    ``source`` names where they were read: ``"windows"``, ``"macos"``,
    ``"gnome"``, ``"mate"``, ``"kde"``, ``"networkmanager"``, or ``"none"``.
    ``state`` is ``"direct"`` when the settings say to use no proxy,
    ``"configured"`` when they name auto-detection, a PAC or a proxy, and
    ``"unset"`` when there were no settings to read.

    ``proxies`` maps a request scheme (``http``, ``https``, ``ftp``) to the
    proxy for it, and ``"socks"`` to the proxy for every scheme without its
    own entry; a string value is parsed with :meth:`Proxy.parse`. ``bypass``
    applies to those proxies only, as it does on every OS.
    """

    source: str = "none"
    state: Literal["direct", "configured", "unset"] = "unset"
    auto_detect: bool = False
    pac_url: "Optional[str]" = None
    pac_script: "Optional[str]" = None
    proxies: "Mapping[str, Proxy]" = field(default_factory=dict)
    bypass: BypassRules = BypassRules.NONE

    def __post_init__(self) -> None:
        if self.state not in _STATES:
            raise ValueError(f"state must be one of {_STATES}, not {self.state!r}")
        proxies = {
            key.lower(): value if isinstance(value, Proxy) else Proxy.parse(value)
            for key, value in self.proxies.items()
        }
        object.__setattr__(self, "proxies", MappingProxyType(proxies))

    def to_proxymap(
        self, *, wpad: bool = False, timeout: float = 10.0, on_missing_engine: str = "raise"
    ) -> ProxyMap:
        """The proxy map these settings describe.

        Sources are asked in the order browsers use: auto-detection (WPAD),
        the PAC, then the proxies. A source that fails -- no WPAD server, a
        PAC that does not download or run -- passes to the next and is tried
        again after 30 s; when none answers, the answer is DIRECT. WPAD runs
        only when ``auto_detect`` is set, or when ``wpad`` is true and the
        state is ``"unset"``; a ``"direct"`` state is DIRECT for every URL.
        Nothing is fetched until the first lookup.

        ``timeout`` bounds each WPAD probe and PAC download.
        ``on_missing_engine`` is as for :class:`~proxylib.PacScript`.
        """
        if self.state == "direct":
            return SimpleProxyMap()
        maps: "List[ProxyMap]" = []
        if self.auto_detect or (wpad and self.state == "unset"):
            from ..pac import wpad as _wpad

            maps.append(
                _Deferred(
                    "WPAD",
                    functools.partial(_wpad.discover, timeout=timeout, on_missing_engine=on_missing_engine),
                )
            )
        if self.pac_url:
            from .. import pac

            maps.append(
                _Deferred(
                    self.pac_url,
                    functools.partial(pac.load, self.pac_url, timeout=timeout, on_missing_engine=on_missing_engine),
                )
            )
        if self.pac_script:
            from .. import pac

            maps.append(
                _Deferred(
                    "the PAC script", functools.partial(pac.loads, self.pac_script, on_missing_engine=on_missing_engine)
                )
            )
        maps.append(manual_map(self.proxies, self.bypass))
        return maps[0] if len(maps) == 1 else ChainProxyMap(*maps)


def manual_map(proxies: "Mapping[str, Proxy]", bypass: BypassRules) -> ProxyMap:
    """The proxy map for manually configured ``proxies`` (keyed as in
    :class:`ProxyConfig`): DIRECT for what ``bypass`` matches and for a
    scheme with no proxy."""
    if not proxies:
        return SimpleProxyMap()
    return Bypass(_ManualMap(proxies), bypass)


class _ManualMap:
    __slots__ = ("proxies",)

    def __init__(self, proxies: "Mapping[str, Proxy]") -> None:
        self.proxies = proxies

    def __repr__(self) -> str:
        return f"<manual proxies {dict(self.proxies)!r}>"

    def __getitem__(self, url: str) -> "Tuple[Optional[Proxy], ...]":
        scheme = urlsplit(url).scheme.lower()
        for key in (scheme, _SCHEME_FALLBACK.get(scheme), "socks"):
            if key and key in self.proxies:
                return (self.proxies[key],)
        return (None,)


class _Deferred:
    """A proxy map ``load`` builds on the first lookup. While ``load`` fails
    or finds nothing (returns ``None``), and while the map it built raises
    :class:`PACError`, lookups have no opinion (``KeyError``); a failed
    ``load`` is retried after ``_RETRY_AFTER`` seconds."""

    __slots__ = ("name", "_load", "_map", "_failed_at", "_lock")

    def __init__(self, name: str, load: "Callable[[], Optional[ProxyMap]]") -> None:
        self.name = name
        self._load = load
        self._map: "Optional[ProxyMap]" = None
        self._failed_at: "Optional[float]" = None
        self._lock = threading.Lock()

    def __repr__(self) -> str:
        return f"<deferred {self.name}>"

    def _get(self) -> "Optional[ProxyMap]":
        with self._lock:
            if self._map is None and (
                self._failed_at is None or time.monotonic() - self._failed_at >= _RETRY_AFTER
            ):
                try:
                    self._map = self._load()
                except (OSError, ValueError, PACError) as exc:
                    log.debug("%s failed to load: %s", self.name, exc)
                if self._map is None:
                    self._failed_at = time.monotonic()
            return self._map

    def __getitem__(self, url: str) -> "Tuple[Optional[Proxy], ...]":
        proxymap = self._get()
        if proxymap is None:
            raise KeyError(url)
        try:
            return lookup(proxymap, url)
        except PACError as exc:
            log.debug("%s failed for %s: %s", self.name, url, exc)
            raise KeyError(url) from None


def proxy_from(value: "Optional[str]", scheme: str) -> "Optional[Proxy]":
    """The proxy a setting names as ``host[:port]`` or ``scheme://host[:port]``.

    ``scheme`` applies when the setting has none, or names a bare ``socks``
    (whose version the OS fixes). ``None`` when the setting is blank or
    unusable.
    """
    value = (value or "").strip().rstrip("/")
    if not value:
        return None
    given, sep, rest = value.partition("://")
    if sep:
        value = rest
        if given.lower() != "socks":
            scheme = given.lower()
    try:
        return Proxy.parse(f"{scheme}://{value}")
    except ProxyParseError as exc:
        log.debug("ignoring proxy setting %r: %s", value, exc)
        return None


def proxy_at(host: "Optional[str]", port: "Union[str, int, None]", scheme: str) -> "Optional[Proxy]":
    """The proxy named by separate host and port settings. A port that is
    missing, ``0`` or not a number means the scheme's default."""
    host = (host or "").strip()
    if not host:
        return None
    prefix, sep, bare = host.rpartition("://")
    port_text = str(port if port is not None else "").strip()
    number = int(port_text) if port_text.isdigit() else None
    return proxy_from(f"{prefix}{sep}{_net.join_host(bare.strip('[]'), number or None)}", scheme)


def parse_proxy_list(text: str, socks_scheme: str) -> "Dict[str, Proxy]":
    """Proxies from ``host:port`` (every scheme) or ``scheme=host:port``
    entries separated by ``;`` or spaces -- the Windows ``ProxyServer`` form.
    An ``https=`` or ``ftp=`` entry is an HTTP proxy for that scheme; a
    ``socks=`` entry is a SOCKS proxy of ``socks_scheme``."""
    proxies: "Dict[str, Proxy]" = {}
    for token in text.replace(";", " ").split():
        protocol, sep, server = token.partition("=")
        if not sep:
            proxy = proxy_from(token, "http")
            for key in ("http", "https", "ftp"):
                if proxy is not None:
                    proxies.setdefault(key, proxy)
            continue
        protocol = protocol.strip().lower()
        if protocol not in ("http", "https", "ftp", "socks"):
            log.debug("ignoring proxy entry %r", token)
            continue
        proxy = proxy_from(server, socks_scheme if protocol == "socks" else "http")
        if proxy is not None:
            proxies[protocol] = proxy
    return proxies
