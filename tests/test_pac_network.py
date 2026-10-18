"""PAC loading and WPAD discovery against a real local HTTP server."""

import socket
import urllib.error

import pytest

import proxylib.pac as pac
import proxylib.pac.wpad as wpad

_SCRIPT = b'function FindProxyForURL(url, host) { return "PROXY p:1"; }'


@pytest.fixture(autouse=True)
def fresh_caches():
    pac.clear_download_cache()
    wpad._cache.clear()
    yield
    pac.clear_download_cache()
    wpad._cache.clear()


def test_load_fetches_a_script_and_ignores_proxy_env(http_server, monkeypatch):
    # A PAC fetch must never go through the proxy it is about to configure.
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:9")
    monkeypatch.setenv("http_proxy", "http://127.0.0.1:9")
    http_server.route("/proxy.pac", _SCRIPT)
    result = pac.load(http_server.url("/proxy.pac"))
    assert result["http://example.com/"][0].host == "p"


def test_load_raises_on_http_error(http_server):
    with pytest.raises(urllib.error.HTTPError):
        pac.load(http_server.url("/missing.pac"))


def test_load_raises_when_the_body_is_not_a_pac(http_server):
    http_server.route("/page.html", b"<html>login</html>")
    with pytest.raises(ValueError, match="FindProxyForURL"):
        pac.load(http_server.url("/page.html"))


def test_load_raises_on_an_oversized_body(http_server):
    http_server.route("/big.pac", _SCRIPT + b" " * (1024 * 1024))
    with pytest.raises(ValueError, match="larger than"):
        pac.load(http_server.url("/big.pac"))


def test_load_times_out(http_server):
    http_server.route("/slow.pac", _SCRIPT, delay=2)
    with pytest.raises((socket.timeout, urllib.error.URLError, TimeoutError)):
        pac.load(http_server.url("/slow.pac"), timeout=0.2)


def test_load_raises_when_nothing_listens():
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    with pytest.raises(urllib.error.URLError):
        pac.load(f"http://127.0.0.1:{port}/proxy.pac", timeout=0.5)


def test_load_without_an_engine_warns_and_returns_direct(http_server, monkeypatch):
    monkeypatch.setattr(pac, "_have_engine", False)
    http_server.route("/proxy.pac", _SCRIPT)
    with pytest.warns(UserWarning):
        result = pac.load(http_server.url("/proxy.pac"))
    assert result["http://example.com/"] == [None]


def test_load_does_not_cache_file_urls(tmp_path):
    script = tmp_path / "proxy.pac"
    script.write_bytes(_SCRIPT)
    pac.load(script.as_uri())
    assert pac._download_cache == {}


def test_wpad_tries_the_next_domain_when_a_fetch_fails(http_server, monkeypatch):
    # wpad.a.example.com resolves but serves 404; wpad.example.com serves the script.
    http_server.route("/example.com/wpad.dat", _SCRIPT)
    monkeypatch.setattr(wpad, "_resolve_with_timeout", lambda host, timeout: "127.0.0.1")
    real_load = wpad.load
    fetched = []

    def load_from_local_server(url, **kwargs):
        host = url.split("/")[2]
        fetched.append(host)
        return real_load(http_server.url(f"/{host[len('wpad.'):]}/wpad.dat"), **kwargs)

    monkeypatch.setattr(wpad, "load", load_from_local_server)
    result = wpad.discover("host.a.example.com", timeout=2, cache_ttl=0)
    assert fetched == ["wpad.a.example.com", "wpad.example.com"]
    assert result["http://example.com/"][0].host == "p"
