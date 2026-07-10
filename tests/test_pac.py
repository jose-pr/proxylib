import datetime

from proxylib import PAC, Proxy, load_pac

pac = PAC()
_WEEKDAYS = ("SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT")


def test_pac_isPlainHostname():
    assert not pac.isPlainHostName("google.com")
    assert pac.isPlainHostName("google")


def test_pac_dnsDomainIs():
    assert pac.dnsDomainIs("host.example.com", ".example.com")
    assert not pac.dnsDomainIs("host.example.com", ".other.com")


def test_pac_localHostOrDomainIs():
    assert pac.localHostOrDomainIs("host", "host.example.com")
    assert pac.localHostOrDomainIs("host.example.com", "host.example.com")
    assert not pac.localHostOrDomainIs("other", "host.example.com")


def test_pac_shExpMatch():
    assert pac.shExpMatch("www.example.com", "*.example.com")
    assert not pac.shExpMatch("www.example.org", "*.example.com")


def test_pac_isInNet_v4():
    assert pac.isInNet("10.1.2.3", "10.0.0.0", "255.0.0.0")
    assert not pac.isInNet("8.8.8.8", "10.0.0.0", "255.0.0.0")


def test_pac_isInNet_v6():
    assert pac.isInNet("2001:db8::1", "2001:db8::", "32")
    assert not pac.isInNet("2001:db9::1", "2001:db8::", "32")


def test_pac_isInNetEx():
    assert pac.isInNetEx("10.1.2.3", "10.0.0.0/8")
    assert pac.isInNetEx("2001:db8::1", "2001:db8::/32")
    assert not pac.isInNetEx("8.8.8.8", "10.0.0.0/8")


def test_pac_sortIpAddressList():
    assert pac.sortIpAddressList("10.0.0.2; 10.0.0.1") == "10.0.0.1; 10.0.0.2"


def test_pac_getClientVersion():
    assert isinstance(pac.getClientVersion(), str)


def test_pac_weekdayRange_single_day():
    today_index = datetime.datetime.now().isoweekday() % 7
    assert pac.weekdayRange(_WEEKDAYS[today_index])
    assert not pac.weekdayRange(_WEEKDAYS[(today_index + 1) % 7])


def test_pac_weekdayRange_full_week_range():
    assert pac.weekdayRange("SUN", "SAT")


def test_pac_dateRange_year():
    year = datetime.datetime.now().year
    assert pac.dateRange(year)
    assert not pac.dateRange(year + 1)


def test_pac_timeRange_full_day():
    assert pac.timeRange(0, 23)


def test_pac_FindProxyForURL_default_direct():
    assert pac.FindProxyForURL("http://example.com", "example.com") == "DIRECT"
    assert pac["http://example.com"] == [None]


def test_pac_findproxyforurl_receives_full_url():
    # The PAC spec passes the complete URL (path/query included) -- that's
    # the whole point of resolving per-request in the adapters. It used to
    # be truncated to scheme://netloc.
    seen = {}

    class Spy(PAC):
        @staticmethod
        def FindProxyForURL(url, host, /):
            seen["url"] = url
            seen["host"] = host
            return "DIRECT"

    Spy()["https://example.com/some/path?q=1"]
    assert seen["url"] == "https://example.com/some/path?q=1"
    assert seen["host"] == "example.com"


def test_example_pac_file():
    proxies = load_pac("file:examples/example.pac")
    assert proxies["http://plain/test"] == [None]
    for dom in [1, 2, 3]:
        assert proxies[f"example{dom}.com"] == [None]
        assert proxies[f"host.example{dom}.com"] == [None]

    assert proxies["https://wustat.windows.com"] == [None]

    assert proxies["https://127.1.1.1/testing"] == [None]
    assert proxies["https://test.site"] == [
        Proxy.from_str("http://wcg1.example.com:8080")
    ]
    assert proxies["nfs://127.1.1.1/testing"] == [None]
