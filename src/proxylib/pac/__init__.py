"""PAC (Proxy Auto-Config) support: the standard Netscape utility functions a
PAC script's ``FindProxyForURL`` relies on, plus the common Microsoft
``*Ex``/IPv6-aware extensions, and loading PAC scripts (as plain Python via
subclassing, or as real JS via the optional ``dukpy`` backend).
"""

from __future__ import annotations

import datetime as _datetime
import ipaddress as _ip
import socket as _socket
from fnmatch import fnmatch as _shexpmatch
from pathlib import Path
from typing import Iterable as _Iter
from typing import Literal as _Literal
from typing import Optional as _Optional
from typing import cast as _cast
from typing import overload as _overload
from urllib.parse import urlparse
from urllib.request import urlopen as _urlopen
from warnings import warn as _warn

from ..netutils import get_ip
from ..proxy import Proxy, UriSplit

_WEEKDAY = _Literal["SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"]
_WEEKDAYS = ("SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT")
_MONTH = _Literal[
    "JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"
]
_MONTHS = (
    "JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC",
)

__all__ = ("PAC", "load")


class PAC(object):
    """Base implementation of the PAC utility-function namespace.

    ``FindProxyForURL`` here always returns ``"DIRECT"``; subclass and
    override it (or use :class:`JSProxyAutoConfig` to run a real PAC script)
    to actually select proxies.
    """

    #### UTILITY FUNCTIONS ####
    @staticmethod
    def dnsResolve(host: str, /) -> "str|None":
        """Resolve host to a single IPv4/IPv6 address string, or None."""
        ip = get_ip(host)
        if ip:
            return ip.exploded
        return None

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
        return len(host.split("."))

    @staticmethod
    def convert_addr(ipaddr: str, /) -> int:
        return int(_ip.ip_address(ipaddr))

    @staticmethod
    def shExpMatch(test: str, shexp: str, /) -> bool:
        return _shexpmatch(test, shexp)

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
        return "." not in host and hostdom.startswith(host) or hostdom == host

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
        return Proxy.find_all(pac_proxies, UriSplit.PAC)

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


try:
    from .javascript import JSContext

    class JSProxyAutoConfig(PAC, JSContext):
        """A PAC whose `FindProxyForURL` (and the utility functions above) run as real JS."""

    _jspac = True
except ImportError:

    _jspac = False
    JSProxyAutoConfig = None


def load(url: str, **urllib_kwds) -> PAC:
    """Load a PAC script from a URL, a ``file:`` path, or inline JS source.

    Requires the ``dukpy`` extra (``proxylib[jspac]``) to actually execute
    the script; without it, a warning is issued and an always-DIRECT
    :class:`PAC` is returned instead.
    """
    js = None
    if "FindProxyForURL(" in url:
        js = url
    elif "://" not in url:
        if url.startswith("file:"):
            js = Path(url.removeprefix("file:")).read_text()
        else:
            url = "https://" + url
    if js is None:
        with _urlopen(url, **urllib_kwds) as resp:
            js = _cast(bytes, resp.read()).decode()

    if "FindProxyForURL" not in js:
        raise ValueError(f"No FindProxyForURL found in response from: {url}")
    if not _jspac:
        _warn(f"Cannot load js from: {url} as pac. Install proxylib[jspac]")
        return PAC()
    else:
        return JSProxyAutoConfig(js)
