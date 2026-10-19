import pytest

from proxylib import Proxy, ProxyDict, ProxyMapAdapter, SimpleProxyMap

requests = pytest.importorskip("requests")


def test_proxydict_returns_uri_for_proxy():
    proxymap = SimpleProxyMap(Proxy.parse("http://proxy:8080"))
    pd = ProxyDict(proxymap)
    assert pd["http://example.com"] == "http://proxy:8080"


def test_proxydict_raises_keyerror_for_direct():
    pd = ProxyDict(SimpleProxyMap("DIRECT"))
    with pytest.raises(KeyError):
        pd["http://example.com"]


def test_proxydict_copy():
    proxymap = SimpleProxyMap(Proxy.parse("http://proxy:8080"))
    pd = ProxyDict(proxymap)
    copy = pd.copy()
    assert copy is not pd
    assert copy.proxymap is proxymap


def test_requests_proxies_alias_is_gone():
    # Removed ahead of 1.0.0 -- ProxyDict is the only name for this now.
    import proxylib
    import proxylib.integrations.requests

    assert not hasattr(proxylib, "RequestsProxies")
    assert not hasattr(proxylib.integrations.requests, "RequestsProxies")


def test_old_proxylib_requests_module_path_is_gone():
    # proxylib.requests moved to proxylib.integrations.requests pre-1.0; no
    # shim is kept at the old path (explicitly accepted breaking change).
    with pytest.raises(ModuleNotFoundError):
        import proxylib.requests  # noqa: F401


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
    proxymap = SimpleProxyMap(Proxy.parse("http://proxy:8080"))
    session = _session_with(ProxyMapAdapter(proxymap))

    session.get("http://example.com", proxies={})

    # The most-specific key select_proxy() checks (scheme://hostname), not a
    # bare scheme/"all" key -- see the env-precedence regression test below
    # for why that specificity matters.
    assert captured_send["proxies"]["http://example.com"] == "http://proxy:8080"


def test_proxy_map_adapter_direct_sets_no_proxy(captured_send):
    session = _session_with(ProxyMapAdapter(SimpleProxyMap("DIRECT")))

    session.get("http://example.com", proxies={})

    assert captured_send["proxies"]["http://example.com"] is None


def test_proxy_map_adapter_explicit_proxy_at_same_key_takes_precedence(captured_send):
    # An explicit proxies= entry at the *same* scheme://hostname key the
    # adapter itself would write still wins (setdefault, not overwrite) --
    # a less-specific key (bare "http") no longer does, since a per-request
    # ProxyMap decision is more specific by definition (see the class
    # docstring and the env-precedence test below).
    proxymap = SimpleProxyMap(Proxy.parse("http://autoproxy:8080"))
    session = _session_with(ProxyMapAdapter(proxymap))

    session.get("http://example.com", proxies={"http://example.com": "http://explicit:9999"})

    assert captured_send["proxies"]["http://example.com"] == "http://explicit:9999"


def test_proxy_map_adapter_no_opinion_leaves_proxies_untouched(captured_send):
    # A ProxyMap that raises KeyError (no opinion) must not add any key at
    # all -- distinct from an explicit DIRECT ([None]), which does (see
    # test_proxy_map_adapter_direct_sets_no_proxy above).
    class NoOpinionMap:
        def __getitem__(self, url):
            raise KeyError(url)

    session = _session_with(ProxyMapAdapter(NoOpinionMap()))

    session.get("http://example.com", proxies={"http": "http://from-caller:8080"})

    assert captured_send["proxies"] == {"http": "http://from-caller:8080"}


def test_proxy_map_adapter_wins_over_env_proxy_when_trust_env(monkeypatch, captured_send):
    # Regression for the env-precedence bug: with trust_env=True (requests'
    # own default), Session.merge_environment_settings merges HTTP_PROXY in
    # via proxies.setdefault(scheme, ...) *before* adapter.send() runs. The
    # old proxies.setdefault(resolved.scheme, ...) implementation lost to
    # that every time; writing the more-specific scheme://hostname key wins
    # regardless of merge order.
    monkeypatch.setenv("HTTP_PROXY", "http://from-env:9999")
    monkeypatch.delenv("HTTPS_PROXY", raising=False)
    monkeypatch.delenv("NO_PROXY", raising=False)

    proxymap = SimpleProxyMap(Proxy.parse("http://from-proxymap:8080"))
    session = requests.Session()
    session.trust_env = True
    session.mount("http://", ProxyMapAdapter(proxymap))

    session.get("http://example.com")

    assert captured_send["proxies"]["http://example.com"] == "http://from-proxymap:8080"


def test_proxydict_treats_non_url_keys_as_missing():
    from proxylib import EnvProxyConfig

    pd = ProxyDict(EnvProxyConfig({}, proxies={"http": "http://p:1"}))
    assert pd.get("http") is None
    assert "all" not in pd
    assert pd["http://example.com/"] == "http://p:1"


def test_requests_get_with_proxydict_over_env_config_reaches_local_server(http_server):
    # requests probes bare keys ("http", "all") before the URL ones.
    from proxylib import EnvProxyConfig

    http_server.route("/", b"ok")
    response = requests.get(
        http_server.url("/"), proxies=ProxyDict(EnvProxyConfig({})), timeout=5
    )
    assert response.text == "ok"


# ---- failover --------------------------------------------------------------------


@pytest.fixture
def tried(monkeypatch):
    """The proxy (or None for DIRECT) each HTTPAdapter.send attempt used."""
    from requests.adapters import HTTPAdapter
    from requests.utils import select_proxy

    attempts = []
    original = HTTPAdapter.send

    def send(self, request, **kwargs):
        attempts.append(select_proxy(request.url, kwargs.get("proxies") or {}))
        return original(self, request, **kwargs)

    monkeypatch.setattr(HTTPAdapter, "send", send)
    return attempts


def _session(adapter):
    session = requests.Session()
    session.trust_env = False
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


def test_a_dead_proxy_fails_over_and_is_skipped_next_time(http_server, dead_port, no_proxy_env, tried):
    http_server.route("/ok", b"fine")
    dead = f"http://127.0.0.1:{dead_port}"
    session = _session(ProxyMapAdapter(SimpleProxyMap(f"PROXY 127.0.0.1:{dead_port}; DIRECT")))
    with session:
        assert session.get(http_server.url("/ok"), timeout=10).text == "fine"
        assert tried == [dead, None]
        tried.clear()
        assert session.get(http_server.url("/ok"), timeout=10).status_code == 200
        assert tried == [None]


def test_without_failover_the_first_error_is_raised(http_server, dead_port, no_proxy_env, tried):
    session = _session(ProxyMapAdapter(SimpleProxyMap(f"PROXY 127.0.0.1:{dead_port}; DIRECT"), failover=False))
    with session, pytest.raises(requests.exceptions.ProxyError):
        session.get(http_server.url("/ok"), timeout=10)
    assert len(tried) == 1


def test_a_read_timeout_never_fails_over(http_server, no_proxy_env, tried):
    http_server.route("/slow", b"late", delay=1.0)
    session = _session(ProxyMapAdapter(SimpleProxyMap("DIRECT; DIRECT")))
    with session, pytest.raises(requests.exceptions.ReadTimeout):
        session.get(http_server.url("/slow"), timeout=(5, 0.2))
    assert tried == [None]


class _NoOpinion:
    def __getitem__(self, url):
        raise KeyError(url)


def test_a_chain_in_proxies_is_resolved_and_failed_over(http_server, dead_port, no_proxy_env, tried):
    http_server.route("/ok", b"fine")
    session = _session(ProxyMapAdapter(_NoOpinion()))
    with session:
        response = session.get(http_server.url("/ok"), proxies={"http": f"PROXY 127.0.0.1:{dead_port}; DIRECT"}, timeout=10)
    assert response.status_code == 200
    assert tried == [f"http://127.0.0.1:{dead_port}", None]


def test_a_proxydict_in_proxies_keeps_its_whole_answer(http_server, dead_port, no_proxy_env, tried):
    http_server.route("/ok", b"fine")
    proxies = ProxyDict(SimpleProxyMap(f"PROXY 127.0.0.1:{dead_port}; DIRECT"))
    with _session(ProxyMapAdapter(_NoOpinion())) as session:
        assert session.get(http_server.url("/ok"), proxies=proxies, timeout=10).status_code == 200
    assert tried == [f"http://127.0.0.1:{dead_port}", None]


def test_a_plain_proxy_url_in_proxies_is_left_to_requests(http_server, dead_port, no_proxy_env, tried):
    with _session(ProxyMapAdapter(_NoOpinion())) as session, pytest.raises(requests.exceptions.ProxyError):
        session.get(http_server.url("/ok"), proxies={"http": f"http://127.0.0.1:{dead_port}"}, timeout=10)
    assert len(tried) == 1