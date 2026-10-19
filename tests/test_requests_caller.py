"""A caller's own proxies, and trust_env=False, win over a patched map, as in
requests itself; only proxies requests takes from the environment lose."""

import pytest

import proxylib
from proxylib import SimpleProxyMap

requests = pytest.importorskip("requests")

URL = "http://example.test/x"


@pytest.fixture
def patched(recording_proxy, no_proxy_env):
    """requests patched with a map that sends everything to recording_proxy."""
    with proxylib.patch(SimpleProxyMap(f"PROXY 127.0.0.1:{recording_proxy.port}"), targets=["requests"]):
        yield recording_proxy


def _proxy(server):
    return f"http://127.0.0.1:{server.port}"


@pytest.mark.parametrize("key", ["http", "all", "http://example.test"])
def test_a_callers_proxies_entry_beats_the_map(patched, gateway, key):
    with requests.Session() as session:
        assert session.get(URL, proxies={key: _proxy(gateway)}, timeout=10).text == "via gateway"
    assert patched.seen == []


def test_session_proxies_beat_the_map(patched, gateway):
    with requests.Session() as session:
        session.proxies = {"http": _proxy(gateway)}
        assert session.get(URL, timeout=10).text == "via gateway"
    assert patched.seen == []


def test_send_with_proxies_beats_the_map(patched, gateway):
    with requests.Session() as session:
        prepared = session.prepare_request(requests.Request("GET", URL))
        assert session.send(prepared, proxies={"http": _proxy(gateway)}, timeout=10).text == "via gateway"
    assert patched.seen == []


def test_a_proxylib_value_from_the_caller_is_still_read(patched, gateway, dead_port):
    chain = f"PROXY 127.0.0.1:{dead_port}; PROXY 127.0.0.1:{gateway.port}"
    with requests.Session() as session:
        assert session.get(URL, proxies={"http": chain}, timeout=10).text == "via gateway"
    assert patched.seen == []


def test_trust_env_false_leaves_the_request_to_requests(patched, http_server):
    http_server.route("/x", b"direct")
    with requests.Session() as session:
        session.trust_env = False
        assert session.get(http_server.url("/x"), timeout=10).text == "direct"
    assert patched.seen == []


def test_an_environment_proxy_still_loses_to_the_map(patched, gateway, monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", _proxy(gateway))
    with requests.Session() as session:
        assert session.get(URL, timeout=10).text == "via proxy"
    assert gateway.seen == []
    assert [target for _, target, _ in patched.seen] == [URL]


def test_without_a_caller_proxy_the_map_decides(patched):
    with requests.Session() as session:
        assert session.get(URL, timeout=10).text == "via proxy"
