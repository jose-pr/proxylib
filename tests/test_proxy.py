import pickle

import pytest

from proxylib import (
    ChainProxyMap,
    Proxy,
    ProxyParseError,
    SimpleProxyMap,
    ProxyMap,
)

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


def test_proxymap_call_proxy_url_is_a_simple_map():
    assert isinstance(ProxyMap("http://proxy.example.com:8080"), SimpleProxyMap)


def test_proxymap_call_trailing_slash_is_a_proxy_not_a_pac():
    # HTTP_PROXY-style values are commonly written with a trailing slash.
    m = ProxyMap("http://proxy.example.com:8080/")
    assert isinstance(m, SimpleProxyMap)
    assert m["http://x"][0].url == "http://proxy.example.com:8080"


def test_proxymap_call_pac_location_is_loaded_on_first_lookup(monkeypatch):
    import proxylib.pac as pac

    loads = []
    monkeypatch.setattr(pac, "load", lambda src: loads.append(src) or SimpleProxyMap("PROXY a:1"))
    m = ProxyMap("file:examples/example.pac")
    assert loads == []
    assert m["http://x/"][0].host == "a"
    m["http://y/"]
    assert loads == ["file:examples/example.pac"]


def test_proxymap_call_returns_a_mapping_unchanged():
    proxies = {"http": "http://p:1"}
    assert ProxyMap(proxies) is proxies


def test_proxymap_call_does_not_reinitialise_a_returned_map():
    class Counting(SimpleProxyMap):
        inits = 0

        def __init__(self, proxy=None):
            type(self).inits += 1
            super().__init__(proxy)

    existing = Counting("PROXY a:1")
    assert ProxyMap(existing) is existing
    assert Counting.inits == 1


def test_proxymap_call_without_arguments_is_direct():
    assert ProxyMap()["http://x/"] == (None,)


def test_proxymap_is_still_structural():
    assert isinstance({}, ProxyMap) and isinstance(SimpleProxyMap(), ProxyMap)
    assert not isinstance(42, ProxyMap)


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


def test_ipv6_proxy_host_is_bracketed_in_urls():
    proxy = Proxy("http", "::1", 8080, "u", "p")
    assert proxy.url == "http://[::1]:8080"
    assert proxy.uri() == "http://u:p@[::1]:8080"
    assert Proxy.parse("http://[::1]:8080") == Proxy("http", "::1", 8080)
    assert Proxy.parse_pac_result("PROXY [::1]:8080")[0].url == "http://[::1]:8080"
    assert Proxy("http", "proxy", 3128).url == "http://proxy:3128"
