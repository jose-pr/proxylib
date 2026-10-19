"""Proxy maps that wrap another proxy map and change its answers."""

from __future__ import annotations

from typing import Iterable, Optional, Tuple, Union

from .bypass import BypassRules
from .proxy import Proxy, ProxyMap, lookup

__all__ = ("Bypass",)


class Bypass:
    """Answers DIRECT for every URL ``rules`` match, and asks ``inner`` for
    the rest. ``rules`` is :class:`BypassRules` or ``NO_PROXY`` text (or its
    entries); loopback is bypassed unless the rules say ``<-loopback>``."""

    __slots__ = ("inner", "rules")

    def __init__(self, inner: ProxyMap, rules: "Union[BypassRules, str, Iterable[str]]") -> None:
        self.inner = inner
        self.rules = rules if isinstance(rules, BypassRules) else BypassRules.parse(rules)

    def __repr__(self) -> str:
        return f"Bypass({self.inner!r}, {self.rules!r})"

    def __getitem__(self, url: str) -> "Tuple[Optional[Proxy], ...]":
        if self.rules.matches(url):
            return (None,)
        return lookup(self.inner, url)
