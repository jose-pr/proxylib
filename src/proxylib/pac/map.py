"""``PacProxyMap``: a proxy map answered by a PAC script or a Python function."""

from __future__ import annotations

from typing import Callable, Optional, Tuple, Union
from urllib.parse import urlsplit, urlunsplit

from ..proxy import Proxy
from .script import PacScript

__all__ = ("PacProxyMap",)

FindProxyForURL = Callable[[str, str], str]


class PacProxyMap:
    """A proxy map that asks ``FindProxyForURL(url, host)`` for every URL.

    ``script`` is a :class:`PacScript` or a Python callable with the same
    signature, which takes the place of subclassing. ``host`` is the URL's
    host, lower-cased. The result string is read with
    :meth:`Proxy.parse_pac_result`; a PAC always answers, so this map never
    raises ``KeyError``.

    ``browser_compatibility=True`` passes an ``https`` URL without its path and
    query, as Chrome and Firefox do so a PAC server cannot see them.
    """

    __slots__ = ("script", "browser_compatibility")

    def __init__(
        self, script: "Union[PacScript, FindProxyForURL]", *, browser_compatibility: bool = False
    ) -> None:
        self.script = script
        self.browser_compatibility = browser_compatibility

    def __repr__(self) -> str:
        return f"PacProxyMap({self.script!r})"

    def __getitem__(self, url: str) -> "Tuple[Optional[Proxy], ...]":
        parts = urlsplit(url)
        if self.browser_compatibility and parts.scheme.lower() == "https":
            url = urlunsplit((parts.scheme, parts.netloc, "/", "", ""))
        host = parts.hostname or ""
        if isinstance(self.script, PacScript):
            result = self.script.find_proxy_for_url(url, host)
        else:
            result = self.script(url, host)
        if not isinstance(result, str):
            return (None,)
        return Proxy.parse_pac_result(result)
