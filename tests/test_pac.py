from src.proxylib import PAC, Proxy, UriSplit

pac = PAC()


def test_pac_isPlainHostname():
    assert not pac.isPlainHostname("google.com")
    assert pac.isPlainHostname("google")
