import pytest

from proxylib import ChainProxyMap, ConfigurableProxyMap, Proxy, ProxyMap, SimpleProxyMap, UriSplit
from proxylib.env import set_default_no_proxy
from proxylib.proxy import URL, _URI


@pytest.fixture(autouse=True)
def clear_default_no_proxy():
    set_default_no_proxy(None)
    yield
    set_default_no_proxy(None)


def test_pac_direct():
    proxy = Proxy.from_str("direct", UriSplit.PAC)
    assert proxy is None


def test_pac_proxy():
    proxy = Proxy.from_str("PROXY fastproxy.example.com:8080", UriSplit.PAC)
    assert proxy.scheme == "http"
    assert proxy.host == "fastproxy.example.com"
    assert proxy.port == 8080


def test_pac_multi():
    proxies = Proxy.find_all(
        "PROXY proxy1.example.com:80; PROXY proxy2.example.com:8080; DIRECT",
        UriSplit.PAC,
    )
    assert len(proxies) == 3
    assert proxies[2] is None
    assert proxies[1].host == "proxy2.example.com"
    assert proxies[0].host == "proxy1.example.com"


def test_scheme_aliases():
    assert Proxy.from_str("PROXY p:80", UriSplit.PAC).scheme == "http"
    assert Proxy.from_str("SOCKS p:1080", UriSplit.PAC).scheme == "socks4"
    assert Proxy.from_str("http://p:80").scheme == "http"


def test_scheme_does_not_match_comma():
    # The SCHEME char class used to be written "[A-Za-z0-9+-.]", where "+-."
    # is the RANGE 0x2B-0x2E and therefore also matches "," (0x2C). RFC 3986
    # allows ALPHA / DIGIT / "+" / "-" / "." only, so a comma must terminate
    # the scheme instead of being swallowed into it.
    import re

    from proxylib._uri import SCHEME

    assert re.fullmatch(SCHEME, "http,x") is None
    # The three legitimate punctuation chars still work.
    assert re.fullmatch(SCHEME, "a+b") is not None
    assert re.fullmatch(SCHEME, "a-b") is not None
    assert re.fullmatch(SCHEME, "a.b") is not None
    assert re.fullmatch(SCHEME, "svn+ssh") is not None

    parsed = Proxy.find_all("http,x://h:1")
    assert not any(p is not None and p.scheme == "http,x" for p in parsed)


def test_proxy_url_and_as_uri():
    proxy = Proxy.from_str("http://user:pass@proxy.example.com:8080")
    assert proxy.url == "http://proxy.example.com:8080"
    assert proxy.as_uri() == "http://user:pass@proxy.example.com:8080"


def test_uri_resolved_fills_default_port():
    uri = _URI("http", "", "", "example.com", None)
    resolved = uri.resolved()
    assert resolved.port == 80
    assert resolved.host == "example.com"


def test_uri_resolved_keeps_existing_port():
    uri = _URI("http", "", "", "example.com", 8080)
    assert uri.resolved() is uri


def test_uri_from_str_invalid_raises():
    with pytest.raises(ValueError):
        URL.from_str(":::", UriSplit.PAC)


def test_simple_proxy_map_wraps_single_proxy():
    proxy = Proxy.from_str("http://p:80")
    m = SimpleProxyMap(proxy)
    assert m.proxies == (proxy,)
    assert m["anything"] == (proxy,)


def test_simple_proxy_map_accepts_sequence():
    p1 = Proxy.from_str("http://p1:80")
    p2 = Proxy.from_str("http://p2:80")
    m = SimpleProxyMap([p1, p2])
    assert m.proxies == [p1, p2]


def test_simple_proxy_map_default_is_direct():
    m = SimpleProxyMap()
    assert m.proxies == (None,)


def test_simple_proxy_map_from_pac_string():
    m = SimpleProxyMap("DIRECT")
    assert m.proxies == [None]


def test_proxy_map_dispatches_bare_authority_to_simple_map():
    m = ProxyMap("http://proxy.example.com:8080")
    assert isinstance(m, SimpleProxyMap)


def test_proxy_map_trailing_slash_is_a_proxy_not_a_pac():
    # HTTP_PROXY-style values are very commonly written with a trailing
    # slash; that used to be misrouted to pac.load() (network I/O + failure).
    m = ProxyMap("http://proxy.example.com:8080/")
    assert isinstance(m, SimpleProxyMap)
    assert m["http://x"][0].netloc == "proxy.example.com:8080"


def test_proxy_map_dispatches_pac_path_to_pac_loader():
    m = ProxyMap("file:examples/example.pac")
    assert not isinstance(m, SimpleProxyMap)


def test_uri_from_str_bare_hostname_raises_value_error():
    # "example.com" matches the URI regex with every group empty; it must be
    # a clear ValueError, not an AttributeError on None later.
    with pytest.raises(ValueError):
        URL.from_str("example.com")


class _KeyErrorMap:
    def __getitem__(self, uri):
        raise KeyError(uri)


def test_chain_proxy_map_falls_through_keyerror_to_next_map():
    p = Proxy.from_str("http://p:80")
    chain = ChainProxyMap(_KeyErrorMap(), SimpleProxyMap(p))
    assert chain["http://example.com"] == (p,)


def test_chain_proxy_map_first_definitive_map_wins():
    p1 = Proxy.from_str("http://p1:80")
    p2 = Proxy.from_str("http://p2:80")
    chain = ChainProxyMap(SimpleProxyMap(p1), SimpleProxyMap(p2))
    assert chain["http://example.com"] == (p1,)


def test_chain_proxy_map_direct_result_is_definitive_and_stops():
    p = Proxy.from_str("http://p:80")
    chain = ChainProxyMap(SimpleProxyMap("DIRECT"), SimpleProxyMap(p))
    assert chain["http://example.com"] == [None]


def test_chain_proxy_map_raises_keyerror_when_all_maps_have_no_opinion():
    chain = ChainProxyMap(_KeyErrorMap(), _KeyErrorMap())
    with pytest.raises(KeyError):
        chain["http://example.com"]


def test_chain_proxy_map_can_nest():
    p = Proxy.from_str("http://p:80")
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
    p = Proxy.from_str("http://p:80")
    inner = _CountingProxyMap((p,))
    cpm = ConfigurableProxyMap(inner)
    assert cpm["http://example.com"] == (p,)
    assert inner.calls == ["http://example.com"]


def test_configurable_proxy_map_caches_within_ttl():
    p = Proxy.from_str("http://p:80")
    inner = _CountingProxyMap((p,))
    cpm = ConfigurableProxyMap(inner, cache_ttl=60.0)

    cpm["http://example.com"]
    cpm["http://example.com"]

    assert inner.calls == ["http://example.com"]


def test_configurable_proxy_map_cache_ttl_none_bypasses_cache():
    p = Proxy.from_str("http://p:80")
    inner = _CountingProxyMap((p,))
    cpm = ConfigurableProxyMap(inner)

    cpm["http://example.com"]
    cpm["http://example.com"]

    assert inner.calls == ["http://example.com", "http://example.com"]


def test_configurable_proxy_map_clear_cache():
    p = Proxy.from_str("http://p:80")
    inner = _CountingProxyMap((p,))
    cpm = ConfigurableProxyMap(inner, cache_ttl=60.0)

    cpm["http://example.com"]
    cpm.clear_cache()
    cpm["http://example.com"]

    assert inner.calls == ["http://example.com", "http://example.com"]


def test_configurable_proxy_map_browser_compatibility_strips_https_path():
    p = Proxy.from_str("http://p:80")
    inner = _CountingProxyMap((p,))
    cpm = ConfigurableProxyMap(inner, browser_compatibility=True)

    cpm["https://example.com/secret/path?query=1"]

    assert inner.calls == ["https://example.com"]


def test_configurable_proxy_map_browser_compatibility_leaves_http_alone():
    p = Proxy.from_str("http://p:80")
    inner = _CountingProxyMap((p,))
    cpm = ConfigurableProxyMap(inner, browser_compatibility=True)

    cpm["http://example.com/some/path"]

    assert inner.calls == ["http://example.com/some/path"]


def test_configurable_proxy_map_cache_key_is_the_effective_url():
    # Two HTTPS URLs differing only in path/query must share one cache entry
    # once browser_compatibility strips them down to the same effective URL.
    p = Proxy.from_str("http://p:80")
    inner = _CountingProxyMap((p,))
    cpm = ConfigurableProxyMap(inner, browser_compatibility=True, cache_ttl=60.0)

    cpm["https://example.com/path/a"]
    cpm["https://example.com/path/b?x=1"]

    assert inner.calls == ["https://example.com"]


def test_configurable_proxy_map_round_robin_rotates_first_choice():
    p1 = Proxy.from_str("http://p1:80")
    p2 = Proxy.from_str("http://p2:80")
    p3 = Proxy.from_str("http://p3:80")
    inner = _CountingProxyMap((p1, p2, p3))
    cpm = ConfigurableProxyMap(inner, round_robin=True)

    assert cpm["http://example.com"] == (p1, p2, p3)
    assert cpm["http://example.com"] == (p2, p3, p1)
    assert cpm["http://example.com"] == (p3, p1, p2)
    assert cpm["http://example.com"] == (p1, p2, p3)


def test_configurable_proxy_map_round_robin_noop_for_single_entry():
    p = Proxy.from_str("http://p:80")
    inner = _CountingProxyMap((p,))
    cpm = ConfigurableProxyMap(inner, round_robin=True)

    assert cpm["http://example.com"] == (p,)
    assert cpm["http://example.com"] == (p,)


def test_configurable_proxy_map_probe_picks_first_reachable(monkeypatch):
    import proxylib.proxy as proxy_module

    p1 = Proxy.from_str("http://p1:80")
    p2 = Proxy.from_str("http://p2:80")
    inner = _CountingProxyMap((p1, p2))
    cpm = ConfigurableProxyMap(inner, probe=True, probe_timeout=1.0)

    monkeypatch.setattr(proxy_module, "first_working_proxy", lambda proxies, timeout: p2)

    assert cpm["http://example.com"] == (p2,)


def test_configurable_proxy_map_probe_raises_keyerror_when_none_reachable(monkeypatch):
    import proxylib.proxy as proxy_module

    p1 = Proxy.from_str("http://p1:80")
    inner = _CountingProxyMap((p1,))
    cpm = ConfigurableProxyMap(inner, probe=True)

    def boom(proxies, timeout):
        raise LookupError("no reachable proxy")

    monkeypatch.setattr(proxy_module, "first_working_proxy", boom)

    with pytest.raises(KeyError):
        cpm["http://example.com"]


def test_configurable_proxy_map_bypass_local_loopback():
    p = Proxy.from_str("http://p:80")
    inner = _CountingProxyMap((p,))
    cpm = ConfigurableProxyMap(inner, bypass_local=True)

    assert cpm["http://127.0.0.1"] == [None]
    assert inner.calls == []  # bypassed before ever consulting the inner map


def test_configurable_proxy_map_bypass_local_does_not_affect_other_hosts():
    p = Proxy.from_str("http://p:80")
    inner = _CountingProxyMap((p,))
    cpm = ConfigurableProxyMap(inner, bypass_local=True)

    assert cpm["http://example.com"] == (p,)


def test_configurable_proxy_map_no_proxy_rules():
    p = Proxy.from_str("http://p:80")
    inner = _CountingProxyMap((p,))
    cpm = ConfigurableProxyMap(inner, no_proxy=["example.com"])

    assert cpm["http://example.com"] == [None]
    assert cpm["http://other.com"] == (p,)


def test_configurable_proxy_map_no_proxy_merges_with_global_defaults():
    set_default_no_proxy(["fromdefault.com"])
    p = Proxy.from_str("http://p:80")
    inner = _CountingProxyMap((p,))
    cpm = ConfigurableProxyMap(inner, no_proxy=["explicit.com"])

    assert cpm["http://explicit.com"] == [None]
    assert cpm["http://fromdefault.com"] == [None]
    assert cpm["http://other.com"] == (p,)


def test_package_exposes_version():
    import proxylib

    assert isinstance(proxylib.__version__, str) and proxylib.__version__
