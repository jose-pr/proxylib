"""The exceptions proxylib raises.

Every library error derives from :class:`ProxylibError`. None of them derives
from ``KeyError``: a proxy map raises ``KeyError`` to mean "no opinion, ask the
next map", and an error must never be mistaken for that.
"""

from __future__ import annotations

from typing import Any, Iterable, Optional, Tuple

__all__ = (
    "ProxylibError",
    "ProxyParseError",
    "PACError",
    "NoReachableProxyError",
    "MissingExtraError",
    "UnsupportedProxyError",
)


class ProxylibError(Exception):
    """Base class of every error proxylib raises."""


class ProxyParseError(ProxylibError, ValueError):
    """Text that should name a proxy, or a PAC result, could not be parsed."""


class PACError(ProxylibError):
    """A PAC script failed: it raised, returned no usable answer in time, or
    could not be loaded as a script."""


class NoReachableProxyError(ProxylibError, LookupError):
    """None of the proxies offered for a request accepted a connection."""


class MissingExtraError(ProxylibError, ImportError):
    """An optional dependency is not installed.

    ``extra`` is the proxylib extra that installs it, or ``None`` when the
    dependency is a client library proxylib integrates with and has no extra
    for (``requests``); ``name`` is the module that failed to import. The
    message names the ``pip install`` line.
    """

    def __init__(self, feature: str, *, name: str, extra: "Optional[str]" = None) -> None:
        self.feature = feature
        self.extra = extra
        target = f'"proxylib[{extra}]"' if extra else name
        super().__init__(f"{feature} needs {name}: pip install {target}", name=name)


class UnsupportedProxyError(ProxylibError):
    """A client was offered only proxies it cannot use: a URL-prefix gateway
    or a SOCKS proxy for a client without them, or a proxy header the client
    cannot keep from the server. Entries it can use are tried instead when the
    answer has any.

    ``client`` names the client; ``proxies`` are the entries offered, and
    ``reasons`` says why each was refused.
    """

    # refused: (Proxy, reason) pairs; Proxy is not importable here (proxy imports this module).
    def __init__(self, client: str, refused: "Iterable[Tuple[Any, str]]") -> None:
        refused = tuple(refused)
        self.client = client
        self.proxies = tuple(proxy for proxy, _ in refused)
        self.reasons = tuple(reason for _, reason in refused)
        detail = "; ".join(f"{proxy.url} ({reason})" for proxy, reason in refused)
        super().__init__(f"{client} cannot use any proxy offered: {detail}")
