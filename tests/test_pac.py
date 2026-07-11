import datetime

import pytest

from proxylib import PAC, Proxy, load_pac

pac = PAC()
_WEEKDAYS = ("SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT")


@pytest.fixture(autouse=True)
def clear_dns_cache():
    import proxylib.pac as pac_module

    pac_module.clear_dns_cache()
    yield
    pac_module.clear_dns_cache()


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


def test_pac_localHostOrDomainIs_rejects_partial_prefix():
    # Regression: a naive `hostdom.startswith(host)` check would wrongly
    # match "ww" against "www.example.com" -- the host part must match
    # exactly, not just be a string prefix.
    assert not pac.localHostOrDomainIs("ww", "www.example.com")


def test_pac_dnsDomainLevels():
    # Spec: number of dots, not split-length (sub.example.com has 2 dots).
    assert pac.dnsDomainLevels("sub.example.com") == 2
    assert pac.dnsDomainLevels("example.com") == 1
    assert pac.dnsDomainLevels("localhost") == 0


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


def test_findproxyforurl_receives_lowercased_host():
    # Regression only (already correct, via urlparse(url).hostname): a
    # mixed-case host in the request URL must reach FindProxyForURL
    # lowercased, matching PAC scripts' usual assumption.
    seen = {}

    class Spy(PAC):
        @staticmethod
        def FindProxyForURL(url, host, /):
            seen["host"] = host
            return "DIRECT"

    Spy()["https://EXAMPLE.Com/path"]
    assert seen["host"] == "example.com"


def test_load_caches_network_downloads(monkeypatch):
    import proxylib.pac as pac

    pac.clear_download_cache()
    calls = []

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b"function FindProxyForURL(url, host) { return 'DIRECT'; }"

    def fake_urlopen(url, **kwargs):
        calls.append(url)
        return FakeResponse()

    monkeypatch.setattr(pac, "_urlopen", fake_urlopen)

    pac.load("http://internal/proxy.pac")
    pac.load("http://internal/proxy.pac")

    assert len(calls) == 1


def test_load_cache_ttl_zero_bypasses_cache(monkeypatch):
    import proxylib.pac as pac

    pac.clear_download_cache()
    calls = []

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b"function FindProxyForURL(url, host) { return 'DIRECT'; }"

    def fake_urlopen(url, **kwargs):
        calls.append(url)
        return FakeResponse()

    monkeypatch.setattr(pac, "_urlopen", fake_urlopen)

    pac.load("http://internal/proxy.pac", cache_ttl=0)
    pac.load("http://internal/proxy.pac", cache_ttl=0)

    assert len(calls) == 2


def test_load_does_not_cache_file_or_inline_sources(monkeypatch):
    import proxylib.pac as pac

    pac.clear_download_cache()

    def boom(url, **kwargs):
        raise AssertionError("file:/inline-JS sources must never hit _urlopen")

    monkeypatch.setattr(pac, "_urlopen", boom)

    pac.load("file:examples/example.pac")
    pac.load("function FindProxyForURL(url, host) { return 'DIRECT'; }")
    assert pac._download_cache == {}


def test_load_urlopen_bypasses_env_proxy(monkeypatch):
    # PAC/WPAD fetches must bypass configured HTTP(S) proxies (see the
    # module comment) -- if they didn't, ProxyHandler.proxy_open() would
    # rewrite the request's host to the (bogus) configured proxy before it
    # ever reaches the HTTP handler that actually opens the connection.
    import urllib.request

    import proxylib.pac as pac

    monkeypatch.setenv("HTTP_PROXY", "http://bogus-proxy-should-not-be-used:9999")
    captured = {}

    class FakeResponse:
        code = 200
        msg = "OK"

        def info(self):
            return {}

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b""

    def fake_do_open(self, http_class, req, **kwargs):
        captured["host"] = req.host
        return FakeResponse()

    monkeypatch.setattr(urllib.request.AbstractHTTPHandler, "do_open", fake_do_open)

    pac._urlopen("http://real-target.example/pac.js")
    assert captured["host"] == "real-target.example"


def test_dns_resolve_caches_within_ttl(monkeypatch):
    import proxylib.pac as pac_module

    calls = []

    def fake_get_ip(host):
        calls.append(host)
        import ipaddress

        return ipaddress.ip_address("1.2.3.4")

    monkeypatch.setattr(pac_module, "get_ip", fake_get_ip)

    assert pac_module.PAC.dnsResolve("example.com") == "1.2.3.4"
    assert pac_module.PAC.dnsResolve("example.com") == "1.2.3.4"
    assert calls == ["example.com"]


def test_dns_resolve_cache_ttl_zero_bypasses_cache(monkeypatch):
    import proxylib.pac as pac_module

    calls = []

    def fake_get_ip(host):
        calls.append(host)
        return None

    monkeypatch.setattr(pac_module, "get_ip", fake_get_ip)

    pac_module.PAC.dnsResolve("example.com", cache_ttl=0)
    pac_module.PAC.dnsResolve("example.com", cache_ttl=0)
    assert calls == ["example.com", "example.com"]


def test_dns_resolve_caches_negative_results(monkeypatch):
    import proxylib.pac as pac_module

    calls = []

    def fake_get_ip(host):
        calls.append(host)
        return None

    monkeypatch.setattr(pac_module, "get_ip", fake_get_ip)

    assert pac_module.PAC.dnsResolve("nowhere.invalid") is None
    assert pac_module.PAC.dnsResolve("nowhere.invalid") is None
    assert calls == ["nowhere.invalid"]


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
