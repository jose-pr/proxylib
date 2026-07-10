import pytest

from proxylib import Proxy, ProxyMap, SimpleProxyMap, UriSplit
from proxylib.proxy import URL, _URI


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


def test_package_exposes_version():
    import proxylib

    assert isinstance(proxylib.__version__, str) and proxylib.__version__
