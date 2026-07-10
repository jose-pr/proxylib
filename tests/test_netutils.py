import ipaddress

import pytest

from proxylib import netutils
from proxylib.proxy import Proxy, UriSplit


@pytest.fixture(autouse=True)
def clear_interfaces_cache():
    netutils.clear_interfaces_cache()
    yield
    netutils.clear_interfaces_cache()


def test_get_ip_from_literal():
    ip = netutils.get_ip("127.0.0.1")
    assert ip == ipaddress.ip_address("127.0.0.1")


def test_get_ip_from_hostname():
    ip = netutils.get_ip("localhost")
    assert ip is not None


def test_get_ip_invalid_returns_none():
    assert netutils.get_ip("this.host.should.not.exist.invalid") is None


def test_get_default_port_known_schemes():
    assert netutils.get_default_port("http") == 80
    assert netutils.get_default_port("https") == 443
    assert netutils.get_default_port("socks5") == 1080


def test_get_default_port_unknown_scheme():
    assert netutils.get_default_port("not-a-real-scheme") is None


def test_get_local_interfaces_returns_something():
    interfaces = netutils.get_local_interfaces()
    assert isinstance(interfaces, list)
    assert all(
        isinstance(i, (ipaddress.IPv4Interface, ipaddress.IPv6Interface))
        for i in interfaces
    )


def test_get_local_interfaces_caches_within_ttl(monkeypatch):
    calls = []

    def fake_enumerate():
        calls.append(1)
        return []

    monkeypatch.setattr(netutils, "_enumerate_interfaces", fake_enumerate)

    netutils.get_local_interfaces()
    netutils.get_local_interfaces()

    assert len(calls) == 1


def test_get_local_interfaces_cache_ttl_zero_bypasses_cache(monkeypatch):
    calls = []

    def fake_enumerate():
        calls.append(1)
        return []

    monkeypatch.setattr(netutils, "_enumerate_interfaces", fake_enumerate)

    netutils.get_local_interfaces(cache_ttl=0)
    netutils.get_local_interfaces(cache_ttl=0)

    assert len(calls) == 2


class _FakeConnections:
    """Stand-in for socket.create_connection: succeeds only for `reachable` hosts."""

    def __init__(self, reachable):
        self.reachable = reachable
        self.attempts = []
        self.closed = []

    def __call__(self, address, timeout=None):
        self.attempts.append(address)
        host, port = address
        if host not in self.reachable:
            raise OSError("connection refused")
        fake_conns = self

        class Sock:
            def close(self):
                fake_conns.closed.append(address)

        return Sock()


def test_first_working_proxy_returns_first_reachable(monkeypatch):
    fake = _FakeConnections(reachable={"p2"})
    monkeypatch.setattr(netutils._socket, "create_connection", fake)

    p1 = Proxy.from_str("http://p1:8080")
    p2 = Proxy.from_str("http://p2:8080")
    result = netutils.first_working_proxy([p1, p2])

    assert result is p2
    assert fake.attempts == [("p1", 8080), ("p2", 8080)]
    assert fake.closed == [("p2", 8080)]  # probe socket must not leak


def test_first_working_proxy_direct_short_circuits(monkeypatch):
    fake = _FakeConnections(reachable=set())
    monkeypatch.setattr(netutils._socket, "create_connection", fake)

    assert netutils.first_working_proxy([None, Proxy.from_str("http://p:80")]) is None
    assert fake.attempts == []  # DIRECT needs no probe


def test_first_working_proxy_uses_default_port_when_missing(monkeypatch):
    fake = _FakeConnections(reachable={"p"})
    monkeypatch.setattr(netutils._socket, "create_connection", fake)

    proxy = Proxy.from_str("PROXY p", UriSplit.PAC)  # no port given
    netutils.first_working_proxy([proxy])
    assert fake.attempts == [("p", 80)]  # http default filled in


def test_first_working_proxy_raises_lookuperror_when_none_reachable(monkeypatch):
    fake = _FakeConnections(reachable=set())
    monkeypatch.setattr(netutils._socket, "create_connection", fake)

    with pytest.raises(LookupError):
        netutils.first_working_proxy([Proxy.from_str("http://p1:80"), Proxy.from_str("http://p2:80")])
