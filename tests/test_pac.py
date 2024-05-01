from src.proxylib import PAC, Proxy, UriSplit, load_pac

pac = PAC()


def test_pac_isPlainHostname():
    assert not pac.isPlainHostName("google.com")
    assert pac.isPlainHostName("google")


def test_example():
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
