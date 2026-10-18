"""Proxy strings consumers depend on (netproxy builds SimpleProxyMap from proxy
URLs and PAC result strings): their parse must not drift between releases."""

import pytest

from proxylib import SimpleProxyMap


def _fields(proxy):
    if proxy is None:
        return None
    return (proxy.scheme, proxy.host, proxy.port, proxy.username, proxy.password)


@pytest.mark.parametrize(
    "text, expected",
    [
        ("DIRECT", [None]),
        ("direct", [None]),
        ("PROXY a:1; DIRECT", [("http", "a", 1, "", ""), None]),
        (
            "PROXY a:1; SOCKS b:2; SOCKS5 c:3; HTTPS d:4",
            [("http", "a", 1, "", ""), ("socks4", "b", 2, "", ""), ("socks5", "c", 3, "", ""), ("https", "d", 4, "", "")],
        ),
        ("http://u:p@a:1", [("http", "a", 1, "u", "p")]),
        ("http://a:1/", [("http", "a", 1, "", "")]),
        ("socks5h://a:1", [("socks5h", "a", 1, "", "")]),
    ],
)
def test_simpleproxymap_parses_consumer_strings(text, expected):
    assert [_fields(p) for p in SimpleProxyMap(text)[""]] == expected
