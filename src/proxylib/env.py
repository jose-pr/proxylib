"""Proxy configuration from ``*_proxy`` environment variables.

:class:`EnvProxyConfig` reads a proxy per scheme plus bypass rules from an
environment mapping -- the process environment by default -- the way curl and
Go's ``httpproxy`` do.
"""

from __future__ import annotations

import os
from typing import Dict, Iterable, Mapping, Optional, Tuple, Union
from urllib.parse import urlsplit

from .bypass import BypassRules
from .exceptions import ProxyParseError
from .proxy import Proxy, ProxyMap, lookup

__all__ = ("EnvProxyConfig",)

# A websocket URL uses the proxy of the HTTP scheme it upgrades from (curl).
_SCHEME_FALLBACK = {"ws": "http", "wss": "https"}


class EnvProxyConfig:
    """A proxy map from ``*_proxy`` environment variables.

    ``env`` is the environment to read: ``None`` (the default) reads
    ``os.environ``, any other mapping is read instead (``{}`` reads nothing).
    It supplies every ``<scheme>_proxy``, ``all_proxy`` and ``no_proxy``; a
    lowercase name wins over its uppercase form. Inside a CGI request
    (``REQUEST_METHOD`` set) an uppercase ``HTTP_PROXY`` is ignored, since a
    client's ``Proxy:`` header can set it (httpoxy); with ``os.environ`` on
    Windows, whose names are case-insensitive, ``http_proxy`` is then ignored
    too.

    ``proxies`` and ``no_proxy``, when given, are applied over what ``env``
    supplied. ``proxies`` maps a URL scheme, or ``"all"``, to a proxy: a
    ``Proxy``, a proxy URL (scheme-less means ``http``), or a PAC location (a
    ``file:`` URL, or an ``http(s)`` URL with a path), which is loaded on the
    first lookup that needs it. ``no_proxy`` is :class:`BypassRules` or
    ``NO_PROXY`` text, and replaces the environment's.

    A lookup answers DIRECT for a bypassed URL, else the proxy for the URL's
    scheme (``ws``/``wss`` fall back to ``http``/``https``), else the ``"all"``
    proxy; with none of those it raises ``KeyError`` (no opinion), since the
    environment cannot say "DIRECT".
    """

    __slots__ = ("proxies", "no_proxy", "_maps")

    def __init__(
        self,
        env: "Optional[Mapping[str, str]]" = None,
        *,
        proxies: "Optional[Mapping[str, Union[str, Proxy]]]" = None,
        no_proxy: "Union[BypassRules, str, Iterable[str], None]" = None,
    ) -> None:
        env_proxies, env_no_proxy = _read_env(os.environ if env is None else env)
        merged: "Dict[str, Union[str, Proxy]]" = dict(env_proxies)
        merged.update({k.lower(): v for k, v in (proxies or {}).items()})
        self.proxies: "Dict[str, Union[str, Proxy]]" = {k: v for k, v in merged.items() if v}
        if no_proxy is None:
            no_proxy = env_no_proxy
        self.no_proxy: BypassRules = (
            no_proxy if isinstance(no_proxy, BypassRules) else BypassRules.parse(no_proxy)
        )
        self._maps: "Dict[str, ProxyMap]" = {
            scheme: ProxyMap(value) for scheme, value in self.proxies.items()
        }

    def __repr__(self) -> str:
        shown = {k: (v.url if isinstance(v, Proxy) else _redact(v)) for k, v in self.proxies.items()}
        return f"EnvProxyConfig(proxies={shown!r}, no_proxy={self.no_proxy!r})"

    def __getitem__(self, url: str) -> "Tuple[Optional[Proxy], ...]":
        scheme = _request_scheme(url)
        if self.no_proxy.matches(url):
            return (None,)
        for key in (scheme, _SCHEME_FALLBACK.get(scheme), "all"):
            if key and key in self._maps:
                return lookup(self._maps[key], url)
        raise KeyError(url)


def _read_env(env: "Mapping[str, str]") -> "Tuple[Dict[str, str], Optional[str]]":
    """(scheme -> proxy, NO_PROXY text) from an environment mapping."""
    cgi = "REQUEST_METHOD" in env
    case_insensitive = env is os.environ and os.name == "nt"
    proxies: "Dict[str, str]" = {}
    no_proxy: "Optional[str]" = None
    # Uppercase names first, so the lowercase pass overwrites them.
    for lowercase_pass in (False, True):
        for name, value in env.items():
            if (name == name.lower()) != lowercase_pass:
                continue
            key = name.lower()
            if not key.endswith("_proxy"):
                continue
            if key == "no_proxy":
                no_proxy = value
                continue
            if cgi and key == "http_proxy" and (not lowercase_pass or case_insensitive):
                continue
            proxies[key[: -len("_proxy")]] = value
    return proxies, no_proxy


def _request_scheme(url: str) -> str:
    parts = urlsplit(url)
    if not parts.scheme or not parts.netloc:
        raise ProxyParseError(f"{url!r} is not a URL with a scheme and a host")
    return parts.scheme.lower()


def _redact(value: str) -> str:
    parts = urlsplit(value if "://" in value else "http://" + value)
    if parts.password:
        return value.replace(parts.password, "***", 1)
    return value
