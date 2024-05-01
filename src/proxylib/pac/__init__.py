import datetime as _datetime
import ipaddress as _ip
import socket as _socket
from fnmatch import fnmatch as _shexpmatch
from pathlib import Path
from typing import Iterable as _Iter
from typing import Literal as _Literal
from typing import cast as _cast
from typing import get_args as _args
from typing import overload as _overload
from urllib.parse import urlparse
from urllib.request import urlopen as _urlopen
from warnings import warn as _warn

from ..netutils import get_ip
from ..proxy import Proxy, UriSplit

_WEEKDAY = _Literal["SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"]
_WEEKDAYS = ("SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT")

__all__ = ("PAC", "load")


class PAC(object):

    #### UTILITY FUNCTIONS ####
    @staticmethod
    def dnsResolve(host: str, /):
        ip = get_ip(host)
        if ip:
            return ip.exploded

    @staticmethod
    def myIpAddress():
        return _socket.gethostbyname(_socket.gethostname())

    @staticmethod
    def dnsDomainLevels(host: str, /):
        return len(host.split("."))

    @staticmethod
    def convert_addr(ipaddr: str, /):
        return int(_ip.ip_address(ipaddr))

    @staticmethod
    def shExpMatch(test: str, shexp: str, /):
        return _shexpmatch(test, shexp)

    #### TIME FUNCTIONS ####
    @_overload
    def weekdayRange(wd1: _WEEKDAY, gmt: 'None|_Literal["GMT"]' = None, /): ...

    @_overload
    def weekdayRange(
        wd1: _WEEKDAY, wd2: _WEEKDAY, gmt: 'None|_Literal["GMT"]' = None, /
    ): ...

    @staticmethod
    def weekdayRange(wd1: _WEEKDAY, /, *args: '_WEEKDAY|_Literal["GMT"]'):
        start = _WEEKDAYS.index(wd1.upper())
        if args:
            wd2 = args[0].upper()
            if len(args) == 2:
                gmt = args[1].upper() == "GMT"
                end = _WEEKDAYS[wd2]
            elif wd2 == "GMT":
                gmt = True
                end = start
            else:
                end = _WEEKDAYS[wd2]

        else:
            end = start

        today = (
            _datetime.datetime.utcnow() if gmt else _datetime.datetime.now()
        ).isoweekday()
        if today == 7:
            today = 0
        return start <= today <= end

    @staticmethod
    def dateRange(*args):
        return False

    @staticmethod
    def timeRange(*args):
        return False

    #### HOSTNAME FUNCTIONS ####

    @staticmethod
    def isPlainHostName(host: str):
        return "." not in host

    @staticmethod
    def dnsDomainIs(host: str, domain: str):
        return host.endswith(domain)

    @staticmethod
    def localHostOrDomainIs(host: str, hostdom: str):
        return "." not in host and hostdom.startswith(host) or hostdom == host

    @staticmethod
    def isResolvable(host: str):
        try:
            _socket.gethostbyname(host)
            return True
        except:
            return False

    @staticmethod
    def isInNet(host: str, pattern: str, mask: str):
        try:
            ip = _ip.IPv4Address(host)
        except:
            try:
                ip = _ip.IPv4Address(PAC.dnsResolve(host))
            except:
                return False
        net = _ip.IPv4Network(f"{pattern}/{mask}", strict=False)
        return ip in net

    @staticmethod
    def FindProxyForURL(url: str, host: str, /) -> str:
        return "DIRECT"

    def __getitem__(self, url: str) -> _Iter[Proxy]:
        parsed = urlparse(url)
        pac_proxies = self.FindProxyForURL(
            f"{parsed.scheme}://{parsed.netloc}", parsed.hostname or ""
        )
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

    class JSProxyAutoConfig(PAC, JSContext): ...

    _jspac = True
except ImportError:

    _jspac = False
    JSProxyAutoConfig = None


def load(url: str, **urllib_kwds):
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
        raise Exception("Not FindProxyForURL found int response from: " + url)
    if not _jspac:
        _warn(f"Can not load js from: {url} as pac. Install proxylib[pac]")
        return PAC()
    else:
        return JSProxyAutoConfig(js)
