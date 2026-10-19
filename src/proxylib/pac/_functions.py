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
from typing import Any as _Any
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

# Seconds any one name lookup a builtin makes may take: a script's own time
# budget (PacScript timeout) must not be spent waiting on DNS.
_DNS_TIMEOUT = 2.0

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
    ip = _net.resolve_ip(host, timeout=_DNS_TIMEOUT)
    result = ip.exploded if ip else None
    if cache_ttl:
        _dns_cache[host] = (_time.monotonic(), result)
    return result


def dnsResolveEx(host: str, /) -> str:
    """Resolve host to all of its addresses (IPv4 and IPv6), '; '-separated."""
    seen: "list[str]" = []
    for address in _net.resolve_all(host, timeout=_DNS_TIMEOUT):
        if str(address) not in seen:
            seen.append(str(address))
    return "; ".join(seen)


def myIpAddress() -> str:
    ip = _net.resolve_ip(_socket.gethostname(), timeout=_DNS_TIMEOUT)
    return str(ip) if ip is not None else "127.0.0.1"


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


def _now(gmt: bool) -> "_datetime.datetime":
    """The current time: UTC for a PAC ``"GMT"`` argument, else local."""
    return _datetime.datetime.now(_datetime.timezone.utc) if gmt else _datetime.datetime.now()


def _split_gmt(args: tuple) -> "_Tuple[list, bool]":
    values = list(args)
    gmt = bool(values) and isinstance(values[-1], str) and values[-1].upper() == "GMT"
    return (values[:-1] if gmt else values), gmt


# weekdayRange, dateRange and timeRange follow Chromium's PAC library (which
# Firefox shares), so a PAC gives the answer it gives in a browser.


def weekdayRange(wd1: _WEEKDAY, /, *args: "_Union[_WEEKDAY, _Literal['GMT']]") -> bool:
    """True on ``wd1`` (through ``wd2``, wrapping past Saturday); an unknown
    day name is false."""
    values, gmt = _split_gmt((wd1, *args))
    names = [str(v).upper() for v in values[:2]]
    if not names or any(name not in _WEEKDAYS for name in names):
        return False
    start = _WEEKDAYS.index(names[0])
    end = _WEEKDAYS.index(names[-1])
    today = _now(gmt).isoweekday() % 7
    return start <= today <= end if start <= end else (today >= start or today <= end)


def dateRange(*args) -> bool:
    """PAC ``dateRange``: a day, month or year, or a range of them, optionally
    followed by ``"GMT"``.

    A number below 32 is a day of the month, a larger one a year, a name a
    month. One value matches that day, month or year. Otherwise the first half
    of the values sets the start (from 1 January, 00:00:00, this year) and the
    second half the end (from 31 December, 23:59:59), and a range whose start
    is after its end wraps; with two values, a day keeps both ends in the
    current month. ``dateRange(1, "JUN", 15, "AUG")``, ``dateRange("OCT", 1995,
    "MAR", 1996)``. An unknown month name is false.
    """
    values, gmt = _split_gmt(args)
    if not values:
        return False
    now = _now(gmt)
    try:
        parts = [_date_part(value) for value in values]
    except ValueError:
        return False
    if len(parts) == 1:
        kind, value = parts[0]
        return {"day": now.day, "month": now.month, "year": now.year}[kind] == value
    start = [now.year, 1, 1, 0, 0, 0]
    end = [now.year, 12, 31, 23, 59, 59]
    index = {"year": 0, "month": 1, "day": 2}
    half = len(parts) // 2
    current_month = False
    for kind, value in parts[:half]:
        start[index[kind]] = value
        current_month = current_month or (kind == "day" and len(parts) <= 2)
    for kind, value in parts[half:]:
        end[index[kind]] = value
    if current_month:
        start[1] = end[1] = now.month
    moment = [now.year, now.month, now.day, now.hour, now.minute, now.second]
    if start <= end:
        return start <= moment <= end
    return moment >= start or moment <= end


def _date_part(value: _Any) -> "_Tuple[str, int]":
    """``("day" | "month" | "year", value)`` for one ``dateRange`` argument;
    ``ValueError`` for an unknown month name."""
    if isinstance(value, str) and not value.strip().isdigit():
        return "month", _MONTHS.index(value.strip().upper()) + 1
    number = int(value)
    return ("day", number) if number < 32 else ("year", number)


def timeRange(*args) -> bool:
    """PAC ``timeRange``: an hour, or a range of hours, of hour:minute or of
    hour:minute:second, optionally followed by ``"GMT"``.

    ``timeRange(9, 17)`` is true from 9:00:00 to 17:59:59 and does not wrap
    (``timeRange(22, 6)`` is never true); ``timeRange(22, 0, 6, 0)`` wraps past
    midnight and ends at 6:00:59.
    """
    values, gmt = _split_gmt(args)
    numbers = [int(v) for v in values]
    now = _now(gmt)
    if len(numbers) == 1:
        return now.hour == numbers[0]
    if len(numbers) == 2:
        return numbers[0] <= now.hour <= numbers[1]
    if len(numbers) == 4:
        start, end = (numbers[0], numbers[1], 0), (numbers[2], numbers[3], 59)
    elif len(numbers) == 6:
        start, end = tuple(numbers[:3]), tuple(numbers[3:])
    else:
        return False
    moment = (now.hour, now.minute, now.second)
    return start <= moment <= end if start <= end else (moment >= start or moment <= end)


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
    return _net.resolve_ip(host, timeout=_DNS_TIMEOUT) is not None


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
