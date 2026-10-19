"""Proxy headers, URL-prefix gateways, and which entries each client can use."""

import asyncio
import pickle
import ssl
import urllib.request

import pytest

from proxylib import (
    EnvProxyConfig,
    Proxy,
    ProxyDict,
    ProxyMap,
    ProxyMapHandler,
    ProxyParseError,
    SimpleProxyMap,
    UnsupportedProxyError,
    lookup,
)
from proxylib import _net

TOKEN = {"X-Proxy-Token": "s3cret"}


# ---- the value type ----------------------------------------------------------------


def test_headers_are_kept_compared_and_never_shown():
    proxy = Proxy("http", "p", 3128, headers=TOKEN)
    assert proxy.headers == TOKEN
    assert proxy == Proxy("http", "p", 3128, headers={"x-proxy-token": "s3cret"})
    assert proxy != Proxy("http", "p", 3128)
    assert hash(proxy) == hash(Proxy("http", "p", 3128, headers=[("X-PROXY-TOKEN", "s3cret")]))
    assert "s3cret" not in repr(proxy) and "X-Proxy-Token" in repr(proxy)
    assert "s3cret" not in proxy.uri() and proxy.url == "http://p:3128"
    assert pickle.loads(pickle.dumps(proxy)).headers == TOKEN


@pytest.mark.parametrize(
    "kwargs",
    [
        {"headers": {"Bad Name": "x"}},
        {"headers": {"X-Ok": "a\r\nInjected: 1"}},
        {"scheme": "socks5", "headers": TOKEN},
        {"path": "/fetch/"},
        {"scheme": "prefix+ftp"},
        {"scheme": "prefix+https", "path": "/fetch?url="},
    ],
)
def test_invalid_headers_and_paths_are_refused(kwargs):
    kwargs = {"scheme": "http", "host": "p", **kwargs}
    with pytest.raises(ProxyParseError):
        Proxy(**kwargs)


def test_a_gateway_parses_from_a_url_and_a_pac_result():
    gateway = Proxy.parse("prefix+https://u:p@gw.example/fetch/")
    assert (gateway.scheme, gateway.host, gateway.path, gateway.is_gateway) == ("prefix+https", "gw.example", "/fetch/", True)
    assert gateway.url == "prefix+https://gw.example/fetch/"
    assert gateway.gateway_url("http://a.test/x?q=1") == "https://gw.example/fetch/http://a.test/x?q=1"
    assert Proxy.parse("prefix+http://gw:8080").gateway_url("http://a/") == "http://gw:8080/http://a/"
    assert _net.default_port(gateway.scheme) == 443
    assert pickle.loads(pickle.dumps(gateway)) == gateway
    assert Proxy.parse_pac_result("PREFIX https://gw.example/fetch/; PROXY p:1; DIRECT") == (
        Proxy("prefix+https", "gw.example", path="/fetch/"),
        Proxy("http", "p", 1),
        None,
    )
    assert not Proxy.parse("http://p:1").is_gateway


def test_a_pac_result_with_prefix_is_read_wherever_proxies_are_given():
    text = "PREFIX http://gw:1/f/; DIRECT"
    expected = (Proxy("prefix+http", "gw", 1, path="/f/"), None)
    assert lookup(ProxyMap(text), "http://a/") == expected
    assert lookup(SimpleProxyMap(text), "http://a/") == expected
    assert lookup({"all": text}, "http://a/") == expected


def test_an_unusable_prefix_entry_is_dropped_with_a_warning():
    with pytest.warns(UserWarning, match="PREFIX gw"):
        assert Proxy.parse_pac_result("PREFIX gw; PROXY p:1") == (Proxy("http", "p", 1),)


def test_a_proxy_variable_takes_a_whole_pac_result_or_a_gateway():
    env = EnvProxyConfig(
        {"HTTP_PROXY": "PROXY a:1; SOCKS5 b:2; DIRECT", "https_proxy": "prefix+https://gw/fetch/"}
    )
    assert lookup(env, "http://x/") == (Proxy("http", "a", 1), Proxy("socks5", "b", 2), None)
    assert lookup(env, "https://x/") == (Proxy("prefix+https", "gw", path="/fetch/"),)


# ---- requests ------------------------------------------------------------------------

requests = pytest.importorskip("requests")
from proxylib import ProxyMapAdapter  # noqa: E402


def _session(proxymap, **kwargs):
    session = requests.Session()
    session.trust_env = False
    adapter = ProxyMapAdapter(proxymap, **kwargs)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


def test_requests_sends_proxy_headers_in_the_connect_only(recording_proxy, tls_server, no_proxy_env):
    proxy = Proxy("http", "127.0.0.1", recording_proxy.port, headers=TOKEN)
    with _session(SimpleProxyMap(proxy)) as session:
        response = session.get(f"https://127.0.0.1:{tls_server.port}/x", verify=tls_server.cafile, timeout=10)
    assert response.text == "tls ok"
    [(method, _, headers)] = recording_proxy.seen
    assert method == "CONNECT" and headers["x-proxy-token"] == "s3cret"
    [(_, _, reached)] = tls_server.seen
    assert "x-proxy-token" not in reached


def test_requests_sends_proxy_headers_to_a_plain_http_proxy(recording_proxy, no_proxy_env):
    proxy = Proxy("http", "127.0.0.1", recording_proxy.port, headers=TOKEN)
    with _session(SimpleProxyMap(proxy)) as session:
        assert session.get("http://example.test/x", timeout=10).text == "via proxy"
        assert session.get("http://example.test/y", timeout=10).text == "via proxy"
    assert [(m, t, h["x-proxy-token"]) for m, t, h in recording_proxy.seen] == [
        ("GET", "http://example.test/x", "s3cret"),
        ("GET", "http://example.test/y", "s3cret"),
    ]


def test_proxy_headers_go_only_to_the_proxy_they_belong_to(recording_proxy, no_proxy_env):
    with _session(SimpleProxyMap(Proxy("http", "127.0.0.1", recording_proxy.port))) as session:
        session.get("http://example.test/x", timeout=10)
    [(_, _, headers)] = recording_proxy.seen
    assert "x-proxy-token" not in headers


def test_requests_through_a_gateway_keeps_the_target_url_cookies_and_redirects(gateway, no_proxy_env):
    pac = f"PREFIX http://user:pw@127.0.0.1:{gateway.port}/fetch/"
    with _session(SimpleProxyMap(pac)) as session:
        response = session.get("http://example.test/page?q=1", timeout=10)
        assert (response.text, response.url) == ("via gateway", "http://example.test/page?q=1")
        assert session.cookies.get("seen", domain="example.test") == "1"
        redirected = session.get("http://example.test/redirect", timeout=10)
    assert redirected.url == "http://example.test/landed"
    assert [target for _, target, _ in gateway.seen] == [
        "/fetch/http://example.test/page?q=1",
        "/fetch/http://example.test/redirect",
        "/fetch/http://example.test/landed",
    ]
    _, _, headers = gateway.seen[0]
    assert headers["proxy-authorization"] == "Basic dXNlcjpwdw=="
    assert headers["host"] == f"127.0.0.1:{gateway.port}"
    assert "seen=1" in gateway.seen[2][2].get("cookie", "")


def test_a_gateway_given_as_requests_proxies_is_resolved_by_the_adapter(gateway, no_proxy_env):
    with _session({}) as session:
        session.get("http://example.test/a", proxies={"http": f"prefix+http://127.0.0.1:{gateway.port}/g/"}, timeout=10)
    assert [target for _, target, _ in gateway.seen] == ["/g/http://example.test/a"]


def test_requests_fails_over_from_a_dead_gateway(gateway, dead_port, no_proxy_env):
    pac = f"PREFIX http://127.0.0.1:{dead_port}/; PREFIX http://127.0.0.1:{gateway.port}/g/"
    with _session(SimpleProxyMap(pac)) as session:
        assert session.get("http://example.test/", timeout=10).text == "via gateway"
    assert [target for _, target, _ in gateway.seen] == ["/g/http://example.test/"]


def test_a_callers_specific_proxy_wins_without_failing_over(dead_port, no_proxy_env):
    with _session(SimpleProxyMap("PROXY 127.0.0.1:9; DIRECT")) as session:
        with pytest.raises(requests.exceptions.ConnectionError):
            session.get("http://example.test/", proxies={"http://example.test": f"http://127.0.0.1:{dead_port}"}, timeout=10)
    assert _net.order_by_health([Proxy("http", "127.0.0.1", 9)]) == [Proxy("http", "127.0.0.1", 9)]
    assert not _net._circuit_breaker


# ---- httpx ---------------------------------------------------------------------------

httpx = pytest.importorskip("httpx")
from proxylib.integrations.httpx import AsyncProxyTransport, ProxyTransport  # noqa: E402


def test_httpx_sends_proxy_headers_in_the_connect_only(recording_proxy, tls_server, no_proxy_env):
    proxy = Proxy("http", "127.0.0.1", recording_proxy.port, headers=TOKEN)
    context = ssl.create_default_context(cafile=tls_server.cafile)
    with httpx.Client(transport=ProxyTransport(SimpleProxyMap(proxy), verify=context)) as client:
        assert client.get(f"https://127.0.0.1:{tls_server.port}/x", timeout=10).text == "tls ok"
    [(method, _, headers)] = recording_proxy.seen
    assert method == "CONNECT" and headers["x-proxy-token"] == "s3cret"
    [(_, _, reached)] = tls_server.seen
    assert "x-proxy-token" not in reached


def test_httpx_through_a_gateway_keeps_the_target_url_and_cookies(gateway, no_proxy_env):
    pac = f"PREFIX http://127.0.0.1:{gateway.port}/fetch/"
    with httpx.Client(transport=ProxyTransport(SimpleProxyMap(pac)), follow_redirects=True) as client:
        response = client.get("http://example.test/page", timeout=10)
        assert (response.text, str(response.url)) == ("via gateway", "http://example.test/page")
        assert client.cookies.get("seen", domain="example.test") == "1"
        assert str(client.get("http://example.test/redirect", timeout=10).url) == "http://example.test/landed"
    assert [target for _, target, _ in gateway.seen] == [
        "/fetch/http://example.test/page",
        "/fetch/http://example.test/redirect",
        "/fetch/http://example.test/landed",
    ]
    assert gateway.seen[0][2]["host"] == f"127.0.0.1:{gateway.port}"


def test_async_httpx_through_a_gateway(gateway, no_proxy_env):
    pac = f"PREFIX http://127.0.0.1:{gateway.port}/fetch/"

    async def main():
        async with httpx.AsyncClient(transport=AsyncProxyTransport(SimpleProxyMap(pac))) as client:
            return (await client.get("http://example.test/a", timeout=10)).text

    assert asyncio.run(main()) == "via gateway"
    assert [target for _, target, _ in gateway.seen] == ["/fetch/http://example.test/a"]


# ---- urllib --------------------------------------------------------------------------


def _open(proxymap, url, context=None):
    handlers = [ProxyMapHandler(proxymap)]
    if context is not None:
        handlers.append(urllib.request.HTTPSHandler(context=context))
    with urllib.request.build_opener(*handlers).open(url, timeout=10) as response:
        return response.read()


def test_urllib_skips_what_it_cannot_use(recording_proxy, no_proxy_env):
    pac = f"SOCKS5 s:1; SOCKS4 t:1; PROXY 127.0.0.1:{recording_proxy.port}"
    assert _open(SimpleProxyMap(pac), "http://example.test/") == b"via proxy"
    with pytest.raises(UnsupportedProxyError) as raised:
        _open(SimpleProxyMap("SOCKS5 s:1; SOCKS4 t:1"), "http://example.test/")
    assert raised.value.client == "urllib" and len(raised.value.proxies) == 2


def test_urllib_through_a_gateway_keeps_the_target_url_cookies_and_redirects(gateway, no_proxy_env):
    import http.cookiejar

    jar = http.cookiejar.CookieJar()
    pac = f"PREFIX http://user:pw@127.0.0.1:{gateway.port}/fetch/"
    opener = urllib.request.build_opener(ProxyMapHandler(SimpleProxyMap(pac)), urllib.request.HTTPCookieProcessor(jar))
    with opener.open("http://example.test/page", timeout=10) as response:
        assert (response.read(), response.geturl()) == (b"via gateway", "http://example.test/page")
    assert [(c.domain, c.name) for c in jar] == [("example.test", "seen")]
    with opener.open("http://example.test/redirect", timeout=10) as response:
        assert response.geturl() == "http://example.test/landed"
    assert [target for _, target, _ in gateway.seen] == [
        "/fetch/http://example.test/page",
        "/fetch/http://example.test/redirect",
        "/fetch/http://example.test/landed",
    ]
    _, _, headers = gateway.seen[0]
    assert headers["proxy-authorization"] == "Basic dXNlcjpwdw=="
    assert headers["host"] == f"127.0.0.1:{gateway.port}"
    assert "seen=1" in gateway.seen[1][2].get("cookie", "")


def test_urllib_through_an_https_gateway(tls_server, no_proxy_env):
    context = ssl.create_default_context(cafile=tls_server.cafile)
    pac = f"PREFIX https://127.0.0.1:{tls_server.port}/g/"
    assert _open(SimpleProxyMap(pac), "http://example.test/a", context) == b"tls ok"
    [(_, target, _)] = tls_server.seen
    assert target == "/g/http://example.test/a"


def test_urllib_sends_proxy_authorization_in_the_connect_only(recording_proxy, tls_server, no_proxy_env):
    proxy = Proxy("http", "127.0.0.1", recording_proxy.port, headers={"Proxy-Authorization": "Bearer t"})
    context = ssl.create_default_context(cafile=tls_server.cafile)
    assert _open(SimpleProxyMap(proxy), f"https://127.0.0.1:{tls_server.port}/", context) == b"tls ok"
    [(method, _, headers)] = recording_proxy.seen
    assert method == "CONNECT" and headers["proxy-authorization"] == "Bearer t"
    [(_, _, reached)] = tls_server.seen
    assert "proxy-authorization" not in reached


def test_urllib_refuses_another_header_for_an_https_url_but_not_for_http(recording_proxy, no_proxy_env):
    proxymap = SimpleProxyMap(Proxy("http", "127.0.0.1", recording_proxy.port, headers=TOKEN))
    with pytest.raises(UnsupportedProxyError, match="Proxy-Authorization"):
        _open(proxymap, "https://example.test/")
    assert _open(proxymap, "http://example.test/") == b"via proxy"
    [(_, _, headers)] = recording_proxy.seen
    assert headers["x-proxy-token"] == "s3cret"


# ---- ProxyDict -----------------------------------------------------------------------


def test_a_proxydict_returns_the_first_proxy_a_url_can_name():
    mapping = ProxyDict(SimpleProxyMap(f"PREFIX http://gw:1/; PROXY p:1"))
    assert mapping["http://a/"] == "http://p:1"
    with pytest.raises(UnsupportedProxyError):
        ProxyDict(SimpleProxyMap(Proxy("http", "p", 1, headers=TOKEN)))["http://a/"]


# ---- aiohttp -------------------------------------------------------------------------


def test_aiohttp_skips_gateways_and_socks_and_sends_proxy_headers(recording_proxy, no_proxy_env):
    aiohttp = pytest.importorskip("aiohttp")
    from proxylib.integrations.aiohttp import ProxySession

    proxy = Proxy("http", "127.0.0.1", recording_proxy.port, headers=TOKEN)

    async def main(proxymap):
        async with ProxySession(proxymap) as session:
            async with session.get("http://example.test/x") as response:
                return await response.text()

    assert asyncio.run(main(SimpleProxyMap(["PREFIX http://gw:1/", "socks5://s:1", proxy]))) == "via proxy"
    [(_, target, headers)] = recording_proxy.seen
    assert (target, headers["x-proxy-token"]) == ("http://example.test/x", "s3cret")
    with pytest.raises(UnsupportedProxyError, match="aiohttp"):
        asyncio.run(main(SimpleProxyMap("PREFIX http://gw:1/")))
    assert aiohttp  # imported for the skip
