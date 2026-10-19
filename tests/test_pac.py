import datetime
import ipaddress

import pytest

import proxylib
import proxylib.pac._functions as functions_module
import proxylib.pac.script as script_module
from proxylib import PACError, PacProxyMap, Proxy, load_pac, loads_pac
from proxylib.pac import functions as f

_WEEKDAYS = ("SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT")


@pytest.fixture(autouse=True)
def clear_caches():
    proxylib.clear_caches()
    yield
    proxylib.clear_caches()


# ---- builtins ----------------------------------------------------------------


def test_functions_is_a_read_only_mapping_of_pac_names():
    assert {"dnsResolve", "shExpMatch", "isInNet", "myIpAddressEx", "weekdayRange"} <= set(f)
    with pytest.raises(TypeError):
        f["shExpMatch"] = len


def test_isPlainHostName():
    assert not f["isPlainHostName"]("google.com")
    assert f["isPlainHostName"]("google")


def test_dnsDomainIs():
    assert f["dnsDomainIs"]("host.example.com", ".example.com")
    assert not f["dnsDomainIs"]("host.example.com", ".other.com")


def test_localHostOrDomainIs():
    assert f["localHostOrDomainIs"]("host", "host.example.com")
    assert f["localHostOrDomainIs"]("host.example.com", "host.example.com")
    assert not f["localHostOrDomainIs"]("other", "host.example.com")
    # The host part must match exactly, not as a string prefix.
    assert not f["localHostOrDomainIs"]("ww", "www.example.com")


def test_dnsDomainLevels_counts_dots():
    assert f["dnsDomainLevels"]("sub.example.com") == 2
    assert f["dnsDomainLevels"]("localhost") == 0


@pytest.mark.parametrize(
    "test, shexp, expected",
    [
        ("www.example.com", "*.example.com", True),
        ("www.example.org", "*.example.com", False),
        ("WWW.EXAMPLE.COM", "*.example.com", False),
        ("A.com", "a.com", False),
        ("a1", "a[1]", False),
        ("[a]", "[a]", True),
        ("ab", "a?", True),
        ("abc", "a?", False),
        ("http://x/p?q=1", "*/p?q=*", True),
    ],
)
def test_shExpMatch_follows_browser_semantics(test, shexp, expected):
    assert f["shExpMatch"](test, shexp) is expected


def test_isInNet():
    assert f["isInNet"]("10.1.2.3", "10.0.0.0", "255.0.0.0")
    assert not f["isInNet"]("8.8.8.8", "10.0.0.0", "255.0.0.0")
    assert f["isInNet"]("2001:db8::1", "2001:db8::", "32")


def test_isInNetEx():
    assert f["isInNetEx"]("10.1.2.3", "10.0.0.0/8")
    assert f["isInNetEx"]("2001:db8::1", "2001:db8::/32")
    assert not f["isInNetEx"]("8.8.8.8", "10.0.0.0/8")


def test_sortIpAddressList_and_getClientVersion():
    assert f["sortIpAddressList"]("10.0.0.2; 10.0.0.1") == "10.0.0.1; 10.0.0.2"
    assert isinstance(f["getClientVersion"](), str)


def test_weekdayRange():
    today_index = datetime.datetime.now().isoweekday() % 7
    assert f["weekdayRange"](_WEEKDAYS[today_index])
    assert not f["weekdayRange"](_WEEKDAYS[(today_index + 1) % 7])
    assert f["weekdayRange"]("SUN", "SAT")


def test_dateRange_and_timeRange():
    year = datetime.datetime.now().year
    assert f["dateRange"](year)
    assert not f["dateRange"](year + 1)
    assert f["timeRange"](0, 23)


def test_dnsResolve_caches_answers_and_failures(monkeypatch):
    calls = []

    def fake_resolve(host, **kwargs):
        calls.append(host)
        return ipaddress.ip_address("1.2.3.4") if host == "example.com" else None

    monkeypatch.setattr(functions_module._net, "resolve_ip", fake_resolve)
    assert f["dnsResolve"]("example.com") == "1.2.3.4"
    assert f["dnsResolve"]("example.com") == "1.2.3.4"
    assert f["dnsResolve"]("nowhere.invalid") is None
    assert f["dnsResolve"]("nowhere.invalid") is None
    f["dnsResolve"]("example.com", cache_ttl=0)
    assert calls == ["example.com", "nowhere.invalid", "example.com"]


# ---- PacProxyMap with a Python FindProxyForURL --------------------------------


def test_python_function_as_find_proxy_for_url():
    seen = []

    def find(url, host):
        seen.append((url, host))
        return "PROXY a:1; DIRECT"

    proxymap = PacProxyMap(find)
    assert proxymap["http://Example.COM/path?q=1"] == (Proxy("http", "a", 1), None)
    # The full URL reaches the function, with the host lower-cased.
    assert seen == [("http://Example.COM/path?q=1", "example.com")]


def test_browser_compatibility_strips_https_path_and_query():
    seen = []
    proxymap = PacProxyMap(lambda url, host: seen.append(url) or "DIRECT", browser_compatibility=True)
    proxymap["https://example.com/secret/path?token=1"]
    proxymap["http://example.com/visible?q=1"]
    assert seen == ["https://example.com/", "http://example.com/visible?q=1"]


def test_unusable_results_are_direct():
    assert PacProxyMap(lambda u, h: 1)["http://x/"] == (None,)
    assert PacProxyMap(lambda u, h: "")["http://x/"] == (None,)
    with pytest.warns(UserWarning, match="garbage"):
        assert PacProxyMap(lambda u, h: "garbage!!")["http://x/"] == (None,)


def test_pac_proxymap_is_a_proxymap():
    assert isinstance(PacProxyMap(lambda u, h: "DIRECT"), proxylib.ProxyMap)


# ---- loaders --------------------------------------------------------------------


def _fake_urlopen(monkeypatch, body):
    calls = []

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self, amt=None):
            return body if amt is None else body[:amt]

    def fake_urlopen(url, **kwargs):
        calls.append((url, kwargs))
        return FakeResponse()

    monkeypatch.setattr(script_module, "_urlopen", fake_urlopen)
    return calls


_DIRECT = b"function FindProxyForURL(url, host) { return 'DIRECT'; }"


def test_load_caches_downloads(monkeypatch):
    calls = _fake_urlopen(monkeypatch, _DIRECT)
    load_pac("http://internal/proxy.pac")
    load_pac("http://internal/proxy.pac")
    load_pac("http://internal/proxy.pac", cache_ttl=0)
    assert len(calls) == 2


def test_load_applies_the_download_timeout(monkeypatch):
    calls = _fake_urlopen(monkeypatch, _DIRECT)
    load_pac("http://internal/a.pac", cache_ttl=0)
    load_pac("http://internal/a.pac", cache_ttl=0, timeout=2)
    assert [kw for _, kw in calls] == [{"timeout": 10.0}, {"timeout": 2}]


def test_load_refuses_an_oversized_script(monkeypatch):
    _fake_urlopen(monkeypatch, _DIRECT + b" " * (1024 * 1024))
    with pytest.raises(PACError, match="larger than"):
        load_pac("http://internal/big.pac", cache_ttl=0)


def test_load_decodes_a_non_utf8_script_as_latin1(monkeypatch):
    body = "function FindProxyForURL(u, h) { /* caf\xe9 */ return 'DIRECT'; }".encode("latin-1")
    _fake_urlopen(monkeypatch, body)
    assert load_pac("http://internal/latin1.pac", cache_ttl=0)["http://x/"] == (None,)


def test_load_reads_a_path_and_never_fetches(monkeypatch, tmp_path):
    monkeypatch.setattr(script_module, "_urlopen", lambda *a, **k: pytest.fail("fetched a path"))
    path = tmp_path / "proxy.pac"
    path.write_bytes(_DIRECT)
    assert load_pac(path)["http://x/"] == (None,)
    assert load_pac(str(path))["http://x/"] == (None,)
    assert load_pac("file:" + str(path))["http://x/"] == (None,)


def test_load_does_not_treat_text_as_a_script():
    with pytest.raises(OSError):
        load_pac("function FindProxyForURL(u, h) { return 'DIRECT'; }")


def test_loads_takes_script_text():
    proxymap = loads_pac("function FindProxyForURL(u, h) { return 'PROXY p:1'; }")
    assert proxymap["http://x/"] == (Proxy("http", "p", 1),)


def test_text_without_find_proxy_for_url_is_a_pac_error():
    with pytest.raises(PACError):
        loads_pac("var x = 1;")


def test_fetch_bypasses_proxy_environment(monkeypatch):
    # The PAC fetch must never go through the proxy it is about to choose.
    import urllib.request

    monkeypatch.setenv("HTTP_PROXY", "http://bogus-proxy-should-not-be-used:9999")
    captured = {}

    class FakeResponse:
        code = 200
        msg = "OK"

        def info(self):
            return {}

    def fake_do_open(self, http_class, req, **kwargs):
        captured["host"] = req.host
        return FakeResponse()

    monkeypatch.setattr(urllib.request.AbstractHTTPHandler, "do_open", fake_do_open)
    script_module._urlopen("http://real-target.example/pac.js")
    assert captured["host"] == "real-target.example"


def test_example_pac_file():
    proxies = load_pac("examples/example.pac")
    assert proxies["http://plain/test"] == (None,)
    assert proxies["https://wustat.windows.com"] == (None,)
    assert proxies["https://127.1.1.1/testing"] == (None,)
    assert proxies["https://test.site"] == (Proxy.parse("http://wcg1.example.com:8080"),)
    assert proxies["nfs://127.1.1.1/testing"] == (None,)
