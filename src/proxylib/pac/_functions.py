"""The PAC builtins: the Netscape functions a ``FindProxyForURL`` script may
call, plus Microsoft's ``*Ex`` extensions.

:data:`functions` maps each name, as the PAC reference spells it, to its Python
implementation; :class:`~proxylib.pac.PacScript` exports them into the JS
engine. ``shExpMatch`` treats only ``*`` and ``?`` as wildcards and matches
case-sensitively, as the Mozilla and Chromium runtimes do.
"""

from __future__ import annotations

import datetime as _datetime
import ipaddress as _ip
import re as _re
import socket as _socket
import time as _time
from functools import lru_cache as _lru_cache
from types import MappingProxyType as _MappingProxyType
from typing import Callable as _Callable
from typing import Dict as _Dict
from typing import Literal as _Literal
from typing import Mapping as _Mapping
from typing import Optional as _Optional
from typing import Tuple as _Tuple
from typing import Union as _Union

from .. import _net

__all__ = ("functions",)

_WEEKDAY = _Literal["SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"]
_WEEKDAYS = ("SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT")
_MONTHS = (
    "JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC",
)

# host -> (monotonic timestamp, address or None) for dnsResolve. A script
# asks for the same host many times across lookups, and netimps does not
# keep failed answers, so failures are remembered here too.
_dns_cache: "_Dict[str, _Tuple[float, _Optional[str]]]" = {}


@_net.register_cache
def _clear_dns_cache() -> None:
    _dns_cache.clear()


@_lru_cache(maxsize=256)
def _shexp_regex(shexp: str) -> "_re.Pattern[str]":
    parts = (".*" if c == "*" else "." if c == "?" else _re.escape(c) for c in shexp)
    return _re.compile("".join(parts), _re.DOTALL)


def dnsResolve(host: str, /, cache_ttl: float = 30.0) -> "_Optional[str]":
    """Resolve host to a single IPv4/IPv6 address string, or None.

    Cached per host for ``cache_ttl`` seconds (default 30); pass
    ``cache_ttl=0``/``None`` to force a fresh resolution.
    """
    if cache_ttl:
        cached = _dns_cache.get(host)
        if cached is not None and (_time.monotonic() - cached[0]) < cache_ttl:
            return cached[1]
    ip = _net.resolve_ip(host)
    result = ip.exploded if ip else None
    if cache_ttl:
        _dns_cache[host] = (_time.monotonic(), result)
    return result


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


def myIpAddress() -> str:
    try:
        return _socket.gethostbyname(_socket.gethostname())
    except OSError:
        return "127.0.0.1"


def myIpAddressEx() -> str:
    """All local addresses (IPv4 and IPv6), '; '-separated."""
    return dnsResolveEx(_socket.gethostname()) or myIpAddress()


def dnsDomainLevels(host: str, /) -> int:
    """Number of dots in ``host`` (the PAC spec's definition), e.g. 2 for ``sub.example.com``."""
    return host.count(".")


def convert_addr(ipaddr: str, /) -> int:
    return int(_ip.ip_address(ipaddr))


def shExpMatch(test: str, shexp: str, /) -> bool:
    return _shexp_regex(shexp).fullmatch(test) is not None


def weekdayRange(wd1: _WEEKDAY, /, *args: "_Union[_WEEKDAY, _Literal['GMT']]") -> bool:
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


def isPlainHostName(host: str) -> bool:
    return "." not in host


def dnsDomainIs(host: str, domain: str) -> bool:
    return host.endswith(domain)


def localHostOrDomainIs(host: str, hostdom: str) -> bool:
    """True if ``host`` is either the bare hostname or the full host+domain of ``hostdom``.

    Compares the *host part* of ``hostdom`` exactly (not a prefix check)
    so e.g. ``"ww"`` does not wrongly match ``"www.example.com"``.
    """
    if "." not in host:
        return hostdom.partition(".")[0] == host
    return hostdom == host


def isResolvable(host: str) -> bool:
    try:
        _socket.gethostbyname(host)
        return True
    except OSError:
        return False


def isResolvableEx(host: str) -> bool:
    return bool(dnsResolveEx(host))


def isInNet(host: str, pattern: str, mask: str) -> bool:
    """IPv4 (spec) net-membership check, tolerant of IPv6 host/pattern too."""
    try:
        ip = _ip.ip_address(host)
    except ValueError:
        resolved = dnsResolve(host)
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


def isInNetEx(ip_address: str, ip_prefix: str) -> bool:
    """Microsoft extension: CIDR-notation net check, IPv4 or IPv6."""
    try:
        ip = _ip.ip_address(ip_address)
        net = _ip.ip_network(ip_prefix, strict=False)
    except ValueError:
        return False
    return ip in net


def sortIpAddressList(ip_address_list: str) -> str:
    """Microsoft extension: sort a '; '-separated address list numerically."""
    addrs = [a.strip() for a in ip_address_list.split(";") if a.strip()]
    try:
        addrs.sort(key=_ip.ip_address)
    except ValueError:
        addrs.sort()
    return "; ".join(addrs)


def getClientVersion() -> str:
    """Microsoft extension: PAC engine version string."""
    return "1.0"


functions: "_Mapping[str, _Callable[..., object]]" = _MappingProxyType(
    {
        "dnsResolve": dnsResolve,
        "dnsResolveEx": dnsResolveEx,
        "myIpAddress": myIpAddress,
        "myIpAddressEx": myIpAddressEx,
        "dnsDomainLevels": dnsDomainLevels,
        "convert_addr": convert_addr,
        "shExpMatch": shExpMatch,
        "weekdayRange": weekdayRange,
        "dateRange": dateRange,
        "timeRange": timeRange,
        "isPlainHostName": isPlainHostName,
        "dnsDomainIs": dnsDomainIs,
        "localHostOrDomainIs": localHostOrDomainIs,
        "isResolvable": isResolvable,
        "isResolvableEx": isResolvableEx,
        "isInNet": isInNet,
        "isInNetEx": isInNetEx,
        "sortIpAddressList": sortIpAddressList,
        "getClientVersion": getClientVersion,
    }
)
"""Every PAC builtin by its PAC name; read-only."""
