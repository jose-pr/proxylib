"""PAC (Proxy Auto-Config) support: the standard Netscape utility functions a
PAC script's ``FindProxyForURL`` relies on, plus the common Microsoft
``*Ex``/IPv6-aware extensions, and loading PAC scripts (as plain Python via
subclassing, or as real JS via an optional engine backend -- ``proxylib[jspac]``
(dukpy) or ``proxylib[quickjs]``, see :mod:`proxylib.pac.engines`).
"""

from __future__ import annotations

import datetime as _datetime
import ipaddress as _ip
import re as _re
import socket as _socket
import time as _time
from functools import lru_cache as _lru_cache
from pathlib import Path
from typing import Dict as _Dict
from typing import Iterable as _Iter
from typing import Literal as _Literal
from typing import Optional as _Optional
from typing import Tuple as _Tuple
from typing import cast as _cast
from typing import overload as _overload
from urllib.parse import urlparse
from urllib.request import ProxyHandler as _ProxyHandler
from urllib.request import build_opener as _build_opener
from warnings import warn as _warn

from ..netutils import get_ip
from ..proxy import Proxy, ProxyMap, UriSplit

_WEEKDAY = _Literal["SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"]
_WEEKDAYS = ("SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT")
_MONTH = _Literal[
    "JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"
]
_MONTHS = (
    "JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC",
)

__all__ = ("PAC", "load", "clear_download_cache", "clear_dns_cache")

# Fetching a PAC/WPAD script must never itself go through a configured HTTP
# proxy -- browsers fetch PAC config bypassing proxy settings for the same
# chicken-and-egg reason, and it's a hard prerequisite for LocalProxyServer
# (companion plan), where env vars point at ourselves and a proxied PAC
# fetch would recurse. ProxyHandler({}) with no entries beats the default
# opener's env-var-honoring behavior.
_urlopen = _build_opener(_ProxyHandler({})).open

# (monotonic timestamp, result) per host, for PAC.dnsResolve. Short TTL
# (~30s): a PAC script commonly calls dnsResolve on the same host many times
# across a session's FindProxyForURL calls (isInNet(myIpAddress(), ...)-style
# checks especially). True per-instance/per-__getitem__ scoping would need
# contextvars since dnsResolve is a staticmethod exported straight into the
# JS engine (no `self` available, and isInNet calls PAC.dnsResolve(host)
# unbound too) -- a short module-level TTL is simpler and nearly equivalent.
# clear_dns_cache() is the seam tests use.
_dns_cache: "_Dict[str, _Tuple[float, _Optional[str]]]" = {}


def clear_dns_cache() -> None:
    _dns_cache.clear()


@_lru_cache(maxsize=256)
def _shexp_regex(shexp: str) -> "_re.Pattern[str]":
    # Netscape shell expressions: "*" and "?" are the only wildcards; "[" and
    # every other character are literal, matched case-sensitively, as in the
    # Mozilla and Chromium PAC runtimes.
    parts = (".*" if c == "*" else "." if c == "?" else _re.escape(c) for c in shexp)
    return _re.compile("".join(parts), _re.DOTALL)


# Result keywords a PAC script may return; anything else is skipped.
_PAC_SCHEMES = frozenset(("http", "https", "socks4", "socks5"))


class PAC(ProxyMap):
    """Base implementation of the PAC utility-function namespace.

    ``FindProxyForURL`` here always returns ``"DIRECT"``; subclass and
    override it (or use :class:`JSProxyAutoConfig` to run a real PAC script)
    to actually select proxies.
    """

    # ProxyMap methods that are not PAC functions: kept out of the JS scope so
    # a JSProxyAutoConfig still answers them in Python.
    _JSCONTEXT_EXCLUDE = ["get"]

    def __init__(self, *_args, **_kwargs) -> None:
        # Takes no configuration. Arguments are accepted because the
        # ProxyMap(src) factory may return a PAC, and Python then calls
        # __init__ on it with the factory's arguments.
        pass

    #### UTILITY FUNCTIONS ####
    @staticmethod
    def dnsResolve(host: str, /, cache_ttl: float = 30.0) -> "str|None":
        """Resolve host to a single IPv4/IPv6 address string, or None.

        Cached per host for ``cache_ttl`` seconds (default 30); pass
        ``cache_ttl=0``/``None`` to force a fresh resolution.
        """
        if cache_ttl:
            cached = _dns_cache.get(host)
            if cached is not None and (_time.monotonic() - cached[0]) < cache_ttl:
                return cached[1]
        ip = get_ip(host)
        result = ip.exploded if ip else None
        if cache_ttl:
            _dns_cache[host] = (_time.monotonic(), result)
        return result

    @staticmethod
    def dnsResolveEx(host: str, /) -> str:
        """Resolve host to all of its addresses (IPv4 and IPv6), '; '-separated."""
        try:
            infos = _socket.getaddrinfo(host, None)
        except OSError:
            return ""
        seen: "list[str]" = []
        for info in infos:
            addr = info[4][0]
            if addr not in seen:
                seen.append(addr)
        return "; ".join(seen)

    @staticmethod
    def myIpAddress() -> str:
        try:
            return _socket.gethostbyname(_socket.gethostname())
        except OSError:
            return "127.0.0.1"

    @staticmethod
    def myIpAddressEx() -> str:
        """All local addresses (IPv4 and IPv6), '; '-separated."""
        return PAC.dnsResolveEx(_socket.gethostname()) or PAC.myIpAddress()

    @staticmethod
    def dnsDomainLevels(host: str, /) -> int:
        """Number of dots in ``host`` (the PAC spec's definition), e.g. 2 for ``sub.example.com``."""
        return host.count(".")

    @staticmethod
    def convert_addr(ipaddr: str, /) -> int:
        return int(_ip.ip_address(ipaddr))

    @staticmethod
    def shExpMatch(test: str, shexp: str, /) -> bool:
        return _shexp_regex(shexp).fullmatch(test) is not None

    #### TIME FUNCTIONS ####
    @_overload
    def weekdayRange(wd1: _WEEKDAY, gmt: 'None|_Literal["GMT"]' = None, /) -> bool: ...

    @_overload
    def weekdayRange(
        wd1: _WEEKDAY, wd2: _WEEKDAY, gmt: 'None|_Literal["GMT"]' = None, /
    ) -> bool: ...

    @staticmethod
    def weekdayRange(wd1: _WEEKDAY, /, *args: '_WEEKDAY|_Literal["GMT"]') -> bool:
        args = list(args)
        gmt = bool(args) and args[-1].upper() == "GMT"
        if gmt:
            args = args[:-1]
        wd2 = args[0] if args else wd1

        start = _WEEKDAYS.index(wd1.upper())
        end = _WEEKDAYS.index(wd2.upper())
        now = _datetime.datetime.now(_datetime.timezone.utc) if gmt else _datetime.datetime.now()
        today = now.isoweekday() % 7

        if start <= end:
            return start <= today <= end
        return today >= start or today <= end

    @staticmethod
    def dateRange(*args) -> bool:
        """Best-effort implementation of the PAC ``dateRange`` overload set.

        Supports the documented call shapes: a single day/month/year, a
        day/month/year range, ``(day1, month1, day2, month2)``,
        ``(month1, year1, month2, year2)`` and
        ``(day1, month1, year1, day2, month2, year2)``, each optionally
        followed by ``"GMT"``.
        """
        args = list(args)
        gmt = bool(args) and isinstance(args[-1], str) and args[-1].upper() == "GMT"
        if gmt:
            args = args[:-1]
        now = _datetime.datetime.now(_datetime.timezone.utc) if gmt else _datetime.datetime.now()

        def classify(value):
            if isinstance(value, str):
                return "month", _MONTHS.index(value.upper()) + 1
            value = int(value)
            return ("year", value) if value > 31 else ("day", value)

        parts = [classify(a) for a in args]
        current = {"day": now.day, "month": now.month, "year": now.year}
        today = (now.year, now.month, now.day)

        if len(parts) == 1:
            kind, val = parts[0]
            return current[kind] == val

        if len(parts) == 2 and parts[0][0] == parts[1][0]:
            kind = parts[0][0]
            lo, hi = parts[0][1], parts[1][1]
            value = current[kind]
            return lo <= value <= hi if lo <= hi else (value >= lo or value <= hi)

        if len(parts) == 4:
            kinds = [p[0] for p in parts]
            if kinds == ["day", "month", "day", "month"]:
                day1, month1, day2, month2 = (p[1] for p in parts)
                start, end = (now.year, month1, day1), (now.year, month2, day2)
            elif kinds == ["month", "year", "month", "year"]:
                month1, year1, month2, year2 = (p[1] for p in parts)
                start, end = (year1, month1, 1), (year2, month2, 31)
            else:
                return False
            return start <= today <= end if start <= end else (today >= start or today <= end)

        if len(parts) == 6:
            day1, month1, year1, day2, month2, year2 = (p[1] for p in parts)
            start, end = (year1, month1, day1), (year2, month2, day2)
            return start <= today <= end if start <= end else (today >= start or today <= end)

        return False

    @staticmethod
    def timeRange(*args) -> bool:
        """PAC ``timeRange``: hour, hour-hour, hour:min-hour:min, or hour:min:sec range, +GMT."""
        args = list(args)
        gmt = bool(args) and isinstance(args[-1], str) and args[-1].upper() == "GMT"
        if gmt:
            args = args[:-1]
        args = [int(a) for a in args]
        now = _datetime.datetime.now(_datetime.timezone.utc) if gmt else _datetime.datetime.now()

        def in_range(start, end, value):
            return start <= value <= end if start <= end else (value >= start or value <= end)

        if len(args) == 1:
            return now.hour == args[0]
        if len(args) == 2:
            return in_range(args[0], args[1], now.hour)
        if len(args) == 4:
            h1, m1, h2, m2 = args
            return in_range((h1, m1), (h2, m2), (now.hour, now.minute))
        if len(args) == 6:
            h1, m1, s1, h2, m2, s2 = args
            return in_range((h1, m1, s1), (h2, m2, s2), (now.hour, now.minute, now.second))
        return False

    #### HOSTNAME FUNCTIONS ####

    @staticmethod
    def isPlainHostName(host: str) -> bool:
        return "." not in host

    @staticmethod
    def dnsDomainIs(host: str, domain: str) -> bool:
        return host.endswith(domain)

    @staticmethod
    def localHostOrDomainIs(host: str, hostdom: str) -> bool:
        """True if ``host`` is either the bare hostname or the full host+domain of ``hostdom``.

        Compares the *host part* of ``hostdom`` exactly (not a prefix check)
        so e.g. ``"ww"`` does not wrongly match ``"www.example.com"``.
        """
        if "." not in host:
            return hostdom.partition(".")[0] == host
        return hostdom == host

    @staticmethod
    def isResolvable(host: str) -> bool:
        try:
            _socket.gethostbyname(host)
            return True
        except OSError:
            return False

    @staticmethod
    def isResolvableEx(host: str) -> bool:
        return bool(PAC.dnsResolveEx(host))

    @staticmethod
    def isInNet(host: str, pattern: str, mask: str) -> bool:
        """IPv4 (spec) net-membership check, tolerant of IPv6 host/pattern too."""
        try:
            ip = _ip.ip_address(host)
        except ValueError:
            resolved = PAC.dnsResolve(host)
            if resolved is None:
                return False
            try:
                ip = _ip.ip_address(resolved)
            except ValueError:
                return False
        try:
            net = _ip.ip_network(f"{pattern}/{mask}", strict=False)
        except ValueError:
            return False
        return ip in net

    @staticmethod
    def isInNetEx(ip_address: str, ip_prefix: str) -> bool:
        """Microsoft extension: CIDR-notation net check, IPv4 or IPv6."""
        try:
            ip = _ip.ip_address(ip_address)
            net = _ip.ip_network(ip_prefix, strict=False)
        except ValueError:
            return False
        return ip in net

    @staticmethod
    def sortIpAddressList(ip_address_list: str) -> str:
        """Microsoft extension: sort a '; '-separated address list numerically."""
        addrs = [a.strip() for a in ip_address_list.split(";") if a.strip()]
        try:
            addrs.sort(key=_ip.ip_address)
        except ValueError:
            addrs.sort()
        return "; ".join(addrs)

    @staticmethod
    def getClientVersion() -> str:
        """Microsoft extension: PAC engine version string."""
        return "1.0"

    @staticmethod
    def FindProxyForURL(url: str, host: str, /) -> str:
        return "DIRECT"

    def __getitem__(self, url: str) -> _Iter[_Optional[Proxy]]:
        # Pass the full URL (path and query included) -- that's what the PAC
        # spec's FindProxyForURL receives, and the whole reason the
        # requests/urllib integrations resolve per-request instead of
        # per-scheme. (Browsers strip https paths for privacy; a PAC file
        # you configure yourself is trusted with your own URLs.)
        parsed = urlparse(url)
        pac_proxies = self.FindProxyForURL(url, parsed.hostname or "")
        if not isinstance(pac_proxies, str):
            pac_proxies = ""
        # Entries with an unknown keyword or no host are skipped and a result
        # with nothing usable left means DIRECT, as browsers treat it.
        proxies = [
            proxy
            for proxy in Proxy.find_all(pac_proxies, UriSplit.PAC)
            if proxy is None or (proxy.scheme in _PAC_SCHEMES and proxy.host)
        ]
        return proxies or [None]


try:
    from .engines import get_engine_class
    from .javascript import JSContext

    # Importing javascript.py always succeeds now (it no longer imports a
    # specific engine directly) -- _jspac must instead reflect whether any
    # engine (dukpy, quickjs, ...) is actually installed.
    _jspac = get_engine_class() is not None

    if _jspac:

        class _JSProxyAutoConfigMeta(type(JSContext), type(PAC)):  # type: ignore[misc]
            """Joins JSContext's export-collecting metaclass with the Protocol
            metaclass PAC inherits from ProxyMap."""

        class JSProxyAutoConfig(PAC, JSContext, metaclass=_JSProxyAutoConfigMeta):
            """A PAC whose `FindProxyForURL` (and the utility functions above) run as real JS."""

            def __init__(self, *args, **kwargs) -> None:
                # Explicit, since PAC.__init__ would otherwise shadow
                # JSContext.__init__. Skipped when already built: the
                # ProxyMap(src) factory returns a loaded instance and Python
                # then calls __init__ on it again with the factory's arguments.
                if "_jsengine" not in object.__getattribute__(self, "__dict__"):
                    JSContext.__init__(self, *args, **kwargs)

    else:
        JSProxyAutoConfig = None
except ImportError:

    _jspac = False
    JSProxyAutoConfig = None


# (monotonic timestamp, result) per URL, for genuine network downloads only
# (never for file:/inline-JS sources -- those are free to re-read/re-parse).
# clear_download_cache() is the seam tests use, same shape as pac.wpad's
# _cache and netutils' interfaces cache.
_download_cache: "_Dict[str, _Tuple[float, PAC]]" = {}

# Seconds, applied when the caller passes no timeout= of its own.
_DEFAULT_TIMEOUT = 10.0
# Chromium's PAC fetcher limit; a larger body is refused rather than run.
_MAX_PAC_BYTES = 1024 * 1024


def clear_download_cache() -> None:
    _download_cache.clear()


def load(url: str, cache_ttl: "float|None" = 300.0, **urllib_kwds) -> PAC:
    """Load a PAC script from a URL, a ``file:`` path, or inline JS source.

    Requires a JS engine -- ``proxylib[jspac]`` (dukpy) or
    ``proxylib[quickjs]`` -- to actually execute the script; without one, a
    warning is issued and an always-DIRECT :class:`PAC` is returned instead.

    Genuine network downloads (not ``file:`` paths or inline JS) are cached
    per URL for ``cache_ttl`` seconds (default 5 minutes); pass
    ``cache_ttl=0``/``None`` to force a fresh fetch. A download times out
    after 10 seconds unless ``timeout=`` is passed, and a body over 1 MiB
    raises ``ValueError``.
    """
    js = None
    from_network = False
    if "FindProxyForURL(" in url:
        js = url
    elif "://" not in url:
        if url.startswith("file:"):
            js = Path(url.removeprefix("file:")).read_text()
        else:
            url = "https://" + url

    if js is None:
        from_network = True
        if cache_ttl:
            cached = _download_cache.get(url)
            if cached is not None and (_time.monotonic() - cached[0]) < cache_ttl:
                return cached[1]
        urllib_kwds.setdefault("timeout", _DEFAULT_TIMEOUT)
        with _urlopen(url, **urllib_kwds) as resp:
            body = _cast(bytes, resp.read(_MAX_PAC_BYTES + 1))
        if len(body) > _MAX_PAC_BYTES:
            raise ValueError(f"PAC script from {url} is larger than {_MAX_PAC_BYTES} bytes")
        try:
            js = body.decode("utf-8")
        except UnicodeDecodeError:
            # Latin-1 maps every byte, so a legacy-encoded script still loads.
            js = body.decode("latin-1")

    if "FindProxyForURL" not in js:
        raise ValueError(f"No FindProxyForURL found in response from: {url}")
    if not _jspac:
        _warn(f"Cannot load js from: {url} as pac. Install proxylib[jspac]")
        result = PAC()
    else:
        result = JSProxyAutoConfig(js)

    if from_network and cache_ttl:
        _download_cache[url] = (_time.monotonic(), result)
    return result
