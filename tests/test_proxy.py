from src.proxylib import Proxy, UriSplit


def test_pac_direct():
    proxy = Proxy.from_str("direct", UriSplit.PAC)
    assert proxy == None


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
    assert proxies[2] == None
    assert proxies[1].host == "proxy2.example.com"
    assert proxies[0].host == "proxy1.example.com"
