import pytest

from proxylib import Proxy, ProxyDict, ProxyMapAdapter, SimpleProxyMap

requests = pytest.importorskip("requests")


def test_proxydict_returns_uri_for_proxy():
    proxymap = SimpleProxyMap(Proxy.from_str("http://proxy:8080"))
    pd = ProxyDict(proxymap)
    assert pd["http://example.com"] == "http://proxy:8080"


def test_proxydict_raises_keyerror_for_direct():
    pd = ProxyDict(SimpleProxyMap("DIRECT"))
    with pytest.raises(KeyError):
        pd["http://example.com"]


def test_proxydict_copy():
    proxymap = SimpleProxyMap(Proxy.from_str("http://proxy:8080"))
    pd = ProxyDict(proxymap)
    copy = pd.copy()
    assert copy is not pd
    assert copy.proxymap is proxymap


def test_requests_proxies_alias_is_gone():
    # Removed ahead of 1.0.0 -- ProxyDict is the only name for this now.
    import proxylib
    import proxylib.requests

    assert not hasattr(proxylib, "RequestsProxies")
    assert not hasattr(proxylib.requests, "RequestsProxies")


@pytest.fixture
def captured_send(monkeypatch):
    """Stub out HTTPAdapter.send so no real network call is made, and capture its kwargs."""
    captured = {}

    def fake_send(self, request, **kwargs):
        captured.update(kwargs)
        response = requests.Response()
        response.status_code = 200
        response.request = request
        return response

    monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", fake_send)
    return captured


def _session_with(adapter):
    session = requests.Session()
    session.trust_env = False
    session.mount("http://", adapter)
    return session


def test_proxy_map_adapter_injects_resolved_proxy(captured_send):
    proxymap = SimpleProxyMap(Proxy.from_str("http://proxy:8080"))
    session = _session_with(ProxyMapAdapter(proxymap))

    session.get("http://example.com", proxies={})

    assert captured_send["proxies"]["http"] == "http://proxy:8080"
    assert captured_send["proxies"]["all"] == "http://proxy:8080"


def test_proxy_map_adapter_direct_sets_no_proxy(captured_send):
    session = _session_with(ProxyMapAdapter(SimpleProxyMap("DIRECT")))

    session.get("http://example.com", proxies={})

    assert captured_send["proxies"] == {}


def test_proxy_map_adapter_explicit_proxy_takes_precedence(captured_send):
    proxymap = SimpleProxyMap(Proxy.from_str("http://autoproxy:8080"))
    session = _session_with(ProxyMapAdapter(proxymap))

    session.get("http://example.com", proxies={"http": "http://explicit:9999"})

    assert captured_send["proxies"]["http"] == "http://explicit:9999"
