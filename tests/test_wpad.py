import pytest

import proxylib.pac.wpad as wpad
from proxylib.pac import PAC
from proxylib.pac.wpad import _candidate_domains, discover


@pytest.fixture(autouse=True)
def clear_wpad_cache():
    wpad._cache.clear()
    yield
    wpad._cache.clear()


def test_candidate_domains_walks_up_skipping_bare_tld():
    domains = list(_candidate_domains("host.corp.example.com"))
    assert domains == ["corp.example.com", "example.com"]


def test_candidate_domains_short_fqdn_yields_nothing():
    assert list(_candidate_domains("host.com")) == []


def test_resolve_with_timeout_gives_up_on_a_hanging_socket_call(monkeypatch):
    import threading
    import time

    release = threading.Event()

    def hanging_gethostbyname(host):
        release.wait(timeout=5.0)  # simulates a DNS server that never replies
        return "10.0.0.1"

    monkeypatch.setattr(wpad.socket, "gethostbyname", hanging_gethostbyname)

    start = time.monotonic()
    result = wpad._resolve_with_timeout("wpad.example.com", 0.1)
    elapsed = time.monotonic() - start

    release.set()  # let the abandoned worker thread finish so it doesn't leak past the test
    assert result is None
    assert elapsed < 1.0  # gave up around the 0.1s timeout, not the 5s hang


def test_discover_returns_none_when_no_wpad_host_resolves(monkeypatch):
    monkeypatch.setattr(
        "socket.gethostbyname", lambda host: (_ for _ in ()).throw(OSError())
    )
    assert discover("host.corp.example.com") is None


def test_discover_loads_pac_from_first_resolving_wpad_host(monkeypatch):
    monkeypatch.setattr(
        "socket.gethostbyname",
        lambda host: "10.0.0.1" if host == "wpad.example.com" else (_ for _ in ()).throw(OSError()),
    )

    sentinel = PAC()

    def fake_load(url, **kwargs):
        assert url == "http://wpad.example.com/wpad.dat"
        return sentinel

    monkeypatch.setattr("proxylib.pac.wpad.load", fake_load)

    result = discover("host.corp.example.com")
    assert result is sentinel


def test_discover_caches_result(monkeypatch):
    calls = []

    def counting_probe(fqdn, timeout, **kwargs):
        calls.append(fqdn)
        return None

    monkeypatch.setattr(wpad, "_discover", counting_probe)

    assert discover("host.corp.example.com") is None
    assert discover("host.corp.example.com") is None
    assert calls == ["host.corp.example.com"]  # second call served from cache


def test_discover_caches_negative_results_separately_per_fqdn(monkeypatch):
    sentinel = PAC()
    monkeypatch.setattr(
        wpad, "_discover", lambda fqdn, timeout, **k: sentinel if "hit" in fqdn else None
    )

    assert discover("host.hit.example.com") is sentinel
    assert discover("host.miss.example.com") is None
    # Both now cached independently:
    monkeypatch.setattr(wpad, "_discover", lambda *a, **k: pytest.fail("probe re-ran"))
    assert discover("host.hit.example.com") is sentinel
    assert discover("host.miss.example.com") is None


def test_discover_cache_ttl_zero_disables_caching(monkeypatch):
    calls = []
    monkeypatch.setattr(wpad, "_discover", lambda fqdn, timeout, **k: calls.append(1))

    discover("host.corp.example.com", cache_ttl=0)
    discover("host.corp.example.com", cache_ttl=0)
    assert len(calls) == 2


def test_discover_cache_expires(monkeypatch):
    calls = []
    monkeypatch.setattr(wpad, "_discover", lambda fqdn, timeout, **k: calls.append(1))

    clock = [1000.0]
    monkeypatch.setattr(wpad.time, "monotonic", lambda: clock[0])

    discover("host.corp.example.com", cache_ttl=300)
    clock[0] += 301
    discover("host.corp.example.com", cache_ttl=300)
    assert len(calls) == 2
