import pytest

from proxylib import Proxy, ProxyMapAdapter, RequestsProxies, SimpleProxyMap

requests = pytest.importorskip("requests")


def test_requests_proxies_returns_uri_for_proxy():
    proxymap = SimpleProxyMap(Proxy.from_str("http://proxy:8080"))
    rp = RequestsProxies(proxymap)
    assert rp["http://example.com"] == "http://proxy:8080"


def test_requests_proxies_raises_keyerror_for_direct():
    rp = RequestsProxies(SimpleProxyMap("DIRECT"))
    with pytest.raises(KeyError):
        rp["http://example.com"]


def test_requests_proxies_copy():
    proxymap = SimpleProxyMap(Proxy.from_str("http://proxy:8080"))
    rp = RequestsProxies(proxymap)
    copy = rp.copy()
    assert copy is not rp
    assert copy.proxymap is proxymap


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
