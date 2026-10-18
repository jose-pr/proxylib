"""Proxy strings consumers depend on (netproxy builds SimpleProxyMap from proxy
URLs and PAC result strings): their parse must not drift between releases.

2.0 changes only how absence is spelled (no port and no credentials are
``None``, not ``0``/``""``) and fixes the strings 1.x parsed to host-less
proxies (the last three cases)."""

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
        ("PROXY a:1; DIRECT", [("http", "a", 1, None, None), None]),
        (
            "PROXY a:1; SOCKS b:2; SOCKS5 c:3; HTTPS d:4",
            [
                ("http", "a", 1, None, None),
                ("socks4", "b", 2, None, None),
                ("socks5", "c", 3, None, None),
                ("https", "d", 4, None, None),
            ],
        ),
        ("http://u:p@a:1", [("http", "a", 1, "u", "p")]),
        ("http://a:1/", [("http", "a", 1, None, None)]),
        ("socks5h://a:1", [("socks5h", "a", 1, None, None)]),
        ("a:1", [("http", "a", 1, None, None)]),
        ("PROXY [::1]:8080", [("http", "::1", 8080, None, None)]),
        ("http://[::1]:8080", [("http", "::1", 8080, None, None)]),
    ],
)
def test_simpleproxymap_parses_consumer_strings(text, expected):
    assert [_fields(p) for p in SimpleProxyMap(text)[""]] == expected
