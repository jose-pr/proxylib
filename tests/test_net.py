import ipaddress

import pytest

import proxylib
from proxylib import NoReachableProxyError, _net
from proxylib.proxy import Proxy


@pytest.fixture(autouse=True)
def clear_caches():
    proxylib.clear_caches()
    yield
    proxylib.clear_caches()


def test_resolve_ip_literal_and_hostname():
    assert _net.resolve_ip("127.0.0.1") == ipaddress.ip_address("127.0.0.1")
    assert _net.resolve_ip("localhost") is not None


def test_resolve_ip_unknown_or_empty_is_none():
    assert _net.resolve_ip("this.host.should.not.exist.invalid", timeout=2) is None
    assert _net.resolve_ip("") is None


def test_join_and_split_host_handle_ipv6():
    assert _net.join_host("::1", 8080) == "[::1]:8080"
    assert _net.join_host("proxy", 0) == "proxy"
    assert _net.split_host_port("[::1]:8080") == ("::1", 8080)
    assert _net.split_host_port("example.com") == ("example.com", None)
    assert _net.split_host_port("host:abc") is None


def test_default_port():
    assert [_net.default_port(s) for s in ("http", "HTTPS", "socks5", "socks4")] == [80, 443, 1080, 1080]
    assert _net.default_port("not-a-real-scheme") is None


def test_local_networks_carry_prefixes():
    networks = _net.local_networks()
    assert networks
    assert all(isinstance(i, (ipaddress.IPv4Interface, ipaddress.IPv6Interface)) for i in networks)
    assert any(i.ip.is_loopback for i in networks)


def test_is_link_scoped():
    assert _net.is_link_scoped(ipaddress.ip_address("127.0.0.1"))
    assert _net.is_link_scoped(ipaddress.ip_address("169.254.1.1"))
    assert not _net.is_link_scoped(ipaddress.ip_address("10.0.0.1"))


class _FakeProbe:
    """Stand-in for _net._tcp_check: succeeds only for `reachable` hosts."""

    def __init__(self, reachable):
        self.reachable = reachable
        self.attempts = []

    def __call__(self, host, port, timeout):
        self.attempts.append((host, port))
        return host in self.reachable


def test_first_working_proxy_returns_first_reachable(monkeypatch):
    fake = _FakeProbe(reachable={"p2"})
    monkeypatch.setattr(_net, "_tcp_check", fake)
    p1, p2 = Proxy.parse("http://p1:8080"), Proxy.parse("http://p2:8080")
    assert _net.first_working_proxy([p1, p2]) is p2
    assert fake.attempts == [("p1", 8080), ("p2", 8080)]


def test_first_working_proxy_direct_short_circuits(monkeypatch):
    fake = _FakeProbe(reachable=set())
    monkeypatch.setattr(_net, "_tcp_check", fake)
    assert _net.first_working_proxy([None, Proxy.parse("http://p:80")]) is None
    assert fake.attempts == []


def test_first_working_proxy_uses_default_port_when_missing(monkeypatch):
    fake = _FakeProbe(reachable={"p"})
    monkeypatch.setattr(_net, "_tcp_check", fake)
    _net.first_working_proxy([Proxy.parse_pac_result("PROXY p")[0]])
    assert fake.attempts == [("p", 80)]


def test_first_working_proxy_raises_when_none_reachable(monkeypatch):
    monkeypatch.setattr(_net, "_tcp_check", _FakeProbe(reachable=set()))
    with pytest.raises(NoReachableProxyError):
        _net.first_working_proxy([Proxy.parse("http://p1:80"), Proxy.parse("http://p2:80")])


def test_first_working_proxy_blacklists_a_failed_probe(monkeypatch):
    fake = _FakeProbe(reachable={"p2"})
    monkeypatch.setattr(_net, "_tcp_check", fake)
    p1, p2 = Proxy.parse("http://p1:80"), Proxy.parse("http://p2:80")
    assert _net.first_working_proxy([p1, p2]) is p2
    fake.attempts.clear()
    assert _net.first_working_proxy([p1, p2]) is p2
    assert fake.attempts == [("p2", 80)]


def test_first_working_proxy_circuit_breaker_expires(monkeypatch):
    fake = _FakeProbe(reachable=set())
    monkeypatch.setattr(_net, "_tcp_check", fake)
    clock = [1000.0]
    p1 = Proxy.parse("http://p1:80")
    with pytest.raises(NoReachableProxyError):
        _net.first_working_proxy([p1], circuit_breaker_ttl=30.0, clock=lambda: clock[0])
    fake.attempts.clear()
    fake.reachable.add("p1")
    clock[0] += 31
    assert _net.first_working_proxy([p1], circuit_breaker_ttl=30.0, clock=lambda: clock[0]) is p1
    assert fake.attempts == [("p1", 80)]


def test_first_working_proxy_circuit_breaker_ttl_zero_disables_it(monkeypatch):
    fake = _FakeProbe(reachable=set())
    monkeypatch.setattr(_net, "_tcp_check", fake)
    p1 = Proxy.parse("http://p1:80")
    with pytest.raises(NoReachableProxyError):
        _net.first_working_proxy([p1], circuit_breaker_ttl=0)
    fake.reachable.add("p1")
    assert _net.first_working_proxy([p1], circuit_breaker_ttl=0) is p1


def test_clear_caches_empties_the_circuit_breaker():
    _net._circuit_breaker[("p1", 80)] = float("inf")
    proxylib.clear_caches()
    assert _net._circuit_breaker == {}
