"""Proxy maps that wrap another proxy map and change its answers.

Each wrapper reads the inner map with :func:`~proxylib.lookup`, so any proxy
map works inside one (a ``dict`` included), and a ``KeyError`` from the inner
map (no opinion) passes through. Write them in the order you mean:
``RoundRobin(Cached(m, ttl=60))`` rotates the cached answer;
:func:`configure` composes them in one fixed order.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from typing import Iterable, Optional, Tuple, Union

from . import _net
from .bypass import BypassRules
from .proxy import Proxy, ProxyMap, _close, lookup

__all__ = ("Bypass", "Cached", "Probed", "RoundRobin", "configure")

_Answer = Tuple[Optional[Proxy], ...]


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

    def close(self) -> None:
        """Close the inner map."""
        _close(self.inner)

    def __getitem__(self, url: str) -> _Answer:
        if self.rules.matches(url):
            return (None,)
        return lookup(self.inner, url)


class Cached:
    """Keeps ``inner``'s answer per URL for ``ttl`` seconds, for at most
    ``maxsize`` URLs (the least recently used is dropped first). "No opinion"
    is not cached. Safe to share between threads; :meth:`clear` empties it."""

    __slots__ = ("inner", "ttl", "maxsize", "_entries", "_lock")

    def __init__(self, inner: ProxyMap, *, ttl: float, maxsize: int = 1024) -> None:
        if ttl <= 0 or maxsize < 1:
            raise ValueError("ttl must be positive and maxsize at least 1")
        self.inner = inner
        self.ttl = ttl
        self.maxsize = maxsize
        self._entries: "OrderedDict[str, Tuple[float, _Answer]]" = OrderedDict()
        self._lock = threading.Lock()

    def __repr__(self) -> str:
        return f"Cached({self.inner!r}, ttl={self.ttl!r}, maxsize={self.maxsize!r})"

    def close(self) -> None:
        """Close the inner map."""
        _close(self.inner)

    def __len__(self) -> int:
        return len(self._entries)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def __getitem__(self, url: str) -> _Answer:
        now = time.monotonic()
        with self._lock:
            entry = self._entries.get(url)
            if entry is not None and now - entry[0] < self.ttl:
                self._entries.move_to_end(url)
                return entry[1]
        answer = lookup(self.inner, url)
        with self._lock:
            self._entries[url] = (now, answer)
            self._entries.move_to_end(url)
            while len(self._entries) > self.maxsize:
                self._entries.popitem(last=False)
        return answer


class RoundRobin:
    """Rotates ``inner``'s answer one place on every lookup, so successive
    requests lead with a different entry and keep the rest as fallbacks.

    The position is kept per distinct answer, for the 1024 most recent ones,
    so every URL the same proxy list serves shares one rotation.
    """

    __slots__ = ("inner", "_positions", "_lock")

    _MAX_ANSWERS = 1024

    def __init__(self, inner: ProxyMap) -> None:
        self.inner = inner
        self._positions: "OrderedDict[_Answer, int]" = OrderedDict()
        self._lock = threading.Lock()

    def __repr__(self) -> str:
        return f"RoundRobin({self.inner!r})"

    def close(self) -> None:
        """Close the inner map."""
        _close(self.inner)

    def __getitem__(self, url: str) -> _Answer:
        answer = lookup(self.inner, url)
        if len(answer) < 2:
            return answer
        with self._lock:
            position = self._positions.pop(answer, 0)
            self._positions[answer] = (position + 1) % len(answer)
            while len(self._positions) > self._MAX_ANSWERS:
                self._positions.popitem(last=False)
        return answer[position:] + answer[:position]


class Probed:
    """Answers the first entry of ``inner``'s answer whose port accepts a TCP
    connection within ``timeout`` seconds (DIRECT counts as reachable). A
    proxy that failed is skipped for 30 s. When none is reachable it raises
    :class:`~proxylib.NoReachableProxyError` (a ``LookupError``, not a
    ``KeyError``: the inner map did have an opinion)."""

    __slots__ = ("inner", "timeout")

    def __init__(self, inner: ProxyMap, *, timeout: float = 5.0) -> None:
        self.inner = inner
        self.timeout = timeout

    def __repr__(self) -> str:
        return f"Probed({self.inner!r}, timeout={self.timeout!r})"

    def close(self) -> None:
        """Close the inner map."""
        _close(self.inner)

    def __getitem__(self, url: str) -> _Answer:
        return (_net.first_working_proxy(lookup(self.inner, url), timeout=self.timeout),)


def configure(
    inner: ProxyMap,
    *,
    bypass: "Union[BypassRules, str, Iterable[str], None]" = None,
    cache_ttl: "Optional[float]" = None,
    round_robin: bool = False,
    probe: bool = False,
    probe_timeout: float = 5.0,
) -> ProxyMap:
    """``inner`` with the asked-for wrappers, in one fixed order.

    Outermost first: ``Bypass``, then ``Probed`` over ``RoundRobin`` over
    ``Cached`` when rotating (each lookup probes the rotated answer), else
    ``Cached`` over ``Probed`` (the probed answer is what is cached, so a
    reachable proxy is not probed again until the entry expires).
    """
    proxymap: ProxyMap = inner
    if round_robin:
        if cache_ttl:
            proxymap = Cached(proxymap, ttl=cache_ttl)
        proxymap = RoundRobin(proxymap)
        if probe:
            proxymap = Probed(proxymap, timeout=probe_timeout)
    else:
        if probe:
            proxymap = Probed(proxymap, timeout=probe_timeout)
        if cache_ttl:
            proxymap = Cached(proxymap, ttl=cache_ttl)
    if bypass is not None:
        proxymap = Bypass(proxymap, bypass)
    return proxymap
