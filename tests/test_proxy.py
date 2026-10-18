import pickle

import pytest

from proxylib import (
    ChainProxyMap,
    ConfigurableProxyMap,
    Proxy,
    ProxyParseError,
    SimpleProxyMap,
    from_source,
)
from proxylib.env import set_default_no_proxy


@pytest.fixture(autouse=True)
def clear_default_no_proxy():
    set_default_no_proxy(None)
    yield
    set_default_no_proxy(None)


def test_pac_result_direct():
    assert Proxy.parse_pac_result("direct") == (None,)


def test_pac_result_proxy():
    (proxy,) = Proxy.parse_pac_result("PROXY fastproxy.example.com:8080")
    assert (proxy.scheme, proxy.host, proxy.port) == ("http", "fastproxy.example.com", 8080)


def test_pac_result_multi():
    proxies = Proxy.parse_pac_result(
        "PROXY proxy1.example.com:80; PROXY proxy2.example.com:8080; DIRECT"
    )
    assert [p.host if p else None for p in proxies] == ["proxy1.example.com", "proxy2.example.com", None]


def test_scheme_aliases():
    assert Proxy.parse_pac_result("PROXY p:80")[0].scheme == "http"
    assert Proxy.parse_pac_result("SOCKS p:1080")[0].scheme == "socks4"
    assert Proxy.parse("socks://p:1080").scheme == "socks4"
    assert Proxy.parse("p:80").scheme == "http"


def test_scheme_does_not_accept_a_comma():
    with pytest.raises(ProxyParseError):
        Proxy.parse("http,x://h:1")


def test_proxy_url_and_uri():
    proxy = Proxy.parse("http://user:pass@proxy.example.com:8080")
    assert proxy.url == "http://proxy.example.com:8080"
    assert proxy.uri() == "http://user:pass@proxy.example.com:8080"
    assert str(proxy) == proxy.url


def test_proxy_uri_percent_encodes_credentials():
    proxy = Proxy("http", "p", 1, "dom\\user", "p@ss:w/rd")
    assert proxy.uri() == "http://dom%5Cuser:p%40ss%3Aw%2Frd@p:1"
    assert Proxy.parse(proxy.uri()) == proxy


def test_proxy_is_an_immutable_hashable_value():
    a, b = Proxy.parse("http://p:1"), Proxy("HTTP", "P", 1)
    assert a == b and hash(a) == hash(b)
    with pytest.raises(AttributeError):
        a.host = "other"
    assert pickle.loads(pickle.dumps(a)) == a


@pytest.mark.parametrize("text", ["", "http://", "http://:8080", "http://p:99999", "http://p:abc"])
def test_proxy_parse_rejects_malformed_text(text):
    with pytest.raises(ProxyParseError):
        Proxy.parse(text)


def test_proxy_parse_refuses_a_pac_location():
    with pytest.raises(ProxyParseError, match="PAC"):
        Proxy.parse("http://wpad.corp/proxy.pac")
    assert Proxy.parse("http://proxy:3128/").port == 3128


def test_simple_proxy_map_wraps_single_proxy():
    proxy = Proxy.parse("http://p:80")
    m = SimpleProxyMap(proxy)
    assert m.proxies == (proxy,)
    assert m["anything"] == (proxy,)


def test_simple_proxy_map_accepts_sequence():
    p1 = Proxy.parse("http://p1:80")
    p2 = Proxy.parse("http://p2:80")
    assert SimpleProxyMap([p1, p2]).proxies == (p1, p2)


def test_simple_proxy_map_default_and_empty_are_direct():
    assert SimpleProxyMap().proxies == (None,)
    assert SimpleProxyMap([]).proxies == (None,)


def test_simple_proxy_map_from_pac_string():
    assert SimpleProxyMap("DIRECT").proxies == (None,)


def test_from_source_proxy_url_is_a_simple_map():
    assert isinstance(from_source("http://proxy.example.com:8080"), SimpleProxyMap)


def test_from_source_trailing_slash_is_a_proxy_not_a_pac():
    # HTTP_PROXY-style values are commonly written with a trailing slash.
    m = from_source("http://proxy.example.com:8080/")
    assert isinstance(m, SimpleProxyMap)
    assert m["http://x"][0].url == "http://proxy.example.com:8080"


def test_from_source_pac_location_is_loaded_on_first_lookup(monkeypatch):
    import proxylib.pac as pac

    loads = []
    monkeypatch.setattr(pac, "load", lambda src: loads.append(src) or SimpleProxyMap("PROXY a:1"))
    m = from_source("file:examples/example.pac")
    assert loads == []
    assert m["http://x/"][0].host == "a"
    m["http://y/"]
    assert loads == ["file:examples/example.pac"]


def test_from_source_returns_a_mapping_unchanged():
    proxies = {"http": "http://p:1"}
    assert from_source(proxies) is proxies


class _KeyErrorMap:
    def __getitem__(self, uri):
        raise KeyError(uri)


def test_chain_proxy_map_falls_through_keyerror_to_next_map():
    p = Proxy.parse("http://p:80")
    chain = ChainProxyMap(_KeyErrorMap(), SimpleProxyMap(p))
    assert chain["http://example.com"] == (p,)


def test_chain_proxy_map_first_definitive_map_wins():
    p1 = Proxy.parse("http://p1:80")
    p2 = Proxy.parse("http://p2:80")
    chain = ChainProxyMap(SimpleProxyMap(p1), SimpleProxyMap(p2))
    assert chain["http://example.com"] == (p1,)


def test_chain_proxy_map_direct_result_is_definitive_and_stops():
    p = Proxy.parse("http://p:80")
    chain = ChainProxyMap(SimpleProxyMap("DIRECT"), SimpleProxyMap(p))
    assert chain["http://example.com"] == (None,)


def test_chain_proxy_map_raises_keyerror_when_all_maps_have_no_opinion():
    chain = ChainProxyMap(_KeyErrorMap(), _KeyErrorMap())
    with pytest.raises(KeyError):
        chain["http://example.com"]


def test_chain_proxy_map_can_nest():
    p = Proxy.parse("http://p:80")
    inner = ChainProxyMap(_KeyErrorMap())
    outer = ChainProxyMap(inner, SimpleProxyMap(p))
    assert outer["http://example.com"] == (p,)


# ---- ConfigurableProxyMap -----------------------------------------------------


class _CountingProxyMap:
    """Records every URL it's asked to resolve; returns a fixed result."""

    def __init__(self, result):
        self.result = result
        self.calls = []

    def __getitem__(self, url):
        self.calls.append(url)
        return self.result


def test_configurable_proxy_map_passes_through_by_default():
    p = Proxy.parse("http://p:80")
    inner = _CountingProxyMap((p,))
    cpm = ConfigurableProxyMap(inner)
    assert cpm["http://example.com"] == (p,)
    assert inner.calls == ["http://example.com"]


def test_configurable_proxy_map_caches_within_ttl():
    p = Proxy.parse("http://p:80")
    inner = _CountingProxyMap((p,))
    cpm = ConfigurableProxyMap(inner, cache_ttl=60.0)

    cpm["http://example.com"]
    cpm["http://example.com"]

    assert inner.calls == ["http://example.com"]


def test_configurable_proxy_map_cache_ttl_none_bypasses_cache():
    p = Proxy.parse("http://p:80")
    inner = _CountingProxyMap((p,))
    cpm = ConfigurableProxyMap(inner)

    cpm["http://example.com"]
    cpm["http://example.com"]

    assert inner.calls == ["http://example.com", "http://example.com"]


def test_configurable_proxy_map_clear_cache():
    p = Proxy.parse("http://p:80")
    inner = _CountingProxyMap((p,))
    cpm = ConfigurableProxyMap(inner, cache_ttl=60.0)

    cpm["http://example.com"]
    cpm.clear_cache()
    cpm["http://example.com"]

    assert inner.calls == ["http://example.com", "http://example.com"]


def test_configurable_proxy_map_browser_compatibility_strips_https_path():
    p = Proxy.parse("http://p:80")
    inner = _CountingProxyMap((p,))
    cpm = ConfigurableProxyMap(inner, browser_compatibility=True)

    cpm["https://example.com/secret/path?query=1"]

    assert inner.calls == ["https://example.com"]


def test_configurable_proxy_map_browser_compatibility_leaves_http_alone():
    p = Proxy.parse("http://p:80")
    inner = _CountingProxyMap((p,))
    cpm = ConfigurableProxyMap(inner, browser_compatibility=True)

    cpm["http://example.com/some/path"]

    assert inner.calls == ["http://example.com/some/path"]


def test_configurable_proxy_map_cache_key_is_the_effective_url():
    # Two HTTPS URLs differing only in path/query must share one cache entry
    # once browser_compatibility strips them down to the same effective URL.
    p = Proxy.parse("http://p:80")
    inner = _CountingProxyMap((p,))
    cpm = ConfigurableProxyMap(inner, browser_compatibility=True, cache_ttl=60.0)

    cpm["https://example.com/path/a"]
    cpm["https://example.com/path/b?x=1"]

    assert inner.calls == ["https://example.com"]


def test_configurable_proxy_map_round_robin_rotates_first_choice():
    p1 = Proxy.parse("http://p1:80")
    p2 = Proxy.parse("http://p2:80")
    p3 = Proxy.parse("http://p3:80")
    inner = _CountingProxyMap((p1, p2, p3))
    cpm = ConfigurableProxyMap(inner, round_robin=True)

    assert cpm["http://example.com"] == (p1, p2, p3)
    assert cpm["http://example.com"] == (p2, p3, p1)
    assert cpm["http://example.com"] == (p3, p1, p2)
    assert cpm["http://example.com"] == (p1, p2, p3)


def test_configurable_proxy_map_round_robin_noop_for_single_entry():
    p = Proxy.parse("http://p:80")
    inner = _CountingProxyMap((p,))
    cpm = ConfigurableProxyMap(inner, round_robin=True)

    assert cpm["http://example.com"] == (p,)
    assert cpm["http://example.com"] == (p,)


def test_configurable_proxy_map_probe_picks_first_reachable(monkeypatch):
    import proxylib.proxy as proxy_module

    p1 = Proxy.parse("http://p1:80")
    p2 = Proxy.parse("http://p2:80")
    inner = _CountingProxyMap((p1, p2))
    cpm = ConfigurableProxyMap(inner, probe=True, probe_timeout=1.0)

    monkeypatch.setattr(proxy_module, "first_working_proxy", lambda proxies, timeout: p2)

    assert cpm["http://example.com"] == (p2,)


def test_configurable_proxy_map_probe_raises_keyerror_when_none_reachable(monkeypatch):
    import proxylib.proxy as proxy_module

    p1 = Proxy.parse("http://p1:80")
    inner = _CountingProxyMap((p1,))
    cpm = ConfigurableProxyMap(inner, probe=True)

    def boom(proxies, timeout):
        raise LookupError("no reachable proxy")

    monkeypatch.setattr(proxy_module, "first_working_proxy", boom)

    with pytest.raises(KeyError):
        cpm["http://example.com"]


def test_configurable_proxy_map_bypass_local_loopback():
    p = Proxy.parse("http://p:80")
    inner = _CountingProxyMap((p,))
    cpm = ConfigurableProxyMap(inner, bypass_local=True)

    assert cpm["http://127.0.0.1"] == (None,)
    assert inner.calls == []  # bypassed before ever consulting the inner map


def test_configurable_proxy_map_bypass_local_does_not_affect_other_hosts():
    p = Proxy.parse("http://p:80")
    inner = _CountingProxyMap((p,))
    cpm = ConfigurableProxyMap(inner, bypass_local=True)

    assert cpm["http://example.com"] == (p,)


def test_configurable_proxy_map_no_proxy_rules():
    p = Proxy.parse("http://p:80")
    inner = _CountingProxyMap((p,))
    cpm = ConfigurableProxyMap(inner, no_proxy=["example.com"])

    assert cpm["http://example.com"] == (None,)
    assert cpm["http://other.com"] == (p,)


def test_configurable_proxy_map_no_proxy_merges_with_global_defaults():
    set_default_no_proxy(["fromdefault.com"])
    p = Proxy.parse("http://p:80")
    inner = _CountingProxyMap((p,))
    cpm = ConfigurableProxyMap(inner, no_proxy=["explicit.com"])

    assert cpm["http://explicit.com"] == (None,)
    assert cpm["http://fromdefault.com"] == (None,)
    assert cpm["http://other.com"] == (p,)


def test_package_exposes_version():
    import proxylib

    assert isinstance(proxylib.__version__, str) and proxylib.__version__


def test_proxy_repr_and_str_mask_the_password():
    proxy = Proxy.parse("http://alice:s3cret@proxy:8080")
    assert "s3cret" not in repr(proxy)
    assert "s3cret" not in str(proxy)
    assert "password='***'" in repr(proxy)
    assert proxy.uri() == "http://alice:s3cret@proxy:8080"
    assert "password" not in repr(Proxy.parse("http://proxy:8080"))


def test_configurable_round_robin_rotates_cached_results():
    m = ConfigurableProxyMap(
        SimpleProxyMap("PROXY a:1; PROXY b:1; PROXY c:1"), cache_ttl=60, round_robin=True
    )
    assert [list(m["http://x/"])[0].host for _ in range(4)] == ["a", "b", "c", "a"]


def test_configurable_cache_is_bounded_and_drops_least_recent():
    calls = []

    class Counting:
        def __getitem__(self, url):
            calls.append(url)
            return [None]

    m = ConfigurableProxyMap(Counting(), cache_ttl=60, cache_maxsize=2)
    m["http://a/"], m["http://b/"], m["http://a/"], m["http://c/"]
    assert len(m._cache) == 2
    m["http://a/"]
    m["http://b/"]
    assert calls == ["http://a/", "http://b/", "http://c/", "http://b/"]


def test_configurable_applies_default_no_proxy_without_explicit_rules():
    set_default_no_proxy(["internal.test"])
    m = ConfigurableProxyMap(SimpleProxyMap("PROXY a:1"))
    assert m["http://internal.test/"] == (None,)
    assert list(m["http://other.test/"])[0].host == "a"


def test_ipv6_proxy_host_is_bracketed_in_urls():
    proxy = Proxy("http", "::1", 8080, "u", "p")
    assert proxy.url == "http://[::1]:8080"
    assert proxy.uri() == "http://u:p@[::1]:8080"
    assert Proxy.parse("http://[::1]:8080") == Proxy("http", "::1", 8080)
    assert Proxy.parse_pac_result("PROXY [::1]:8080")[0].url == "http://[::1]:8080"
    assert Proxy("http", "proxy", 3128).url == "http://proxy:3128"
