import ipaddress

from proxylib import netutils


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
