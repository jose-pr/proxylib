import pytest

from proxylib import Proxy
from proxylib.env import EnvProxyConfig, get_default_no_proxy, set_default_no_proxy


@pytest.fixture(autouse=True)
def clear_default_no_proxy():
    set_default_no_proxy(None)
    yield
    set_default_no_proxy(None)


def test_env_selects_http_vs_https_proxy():
    cfg = EnvProxyConfig("http://httpproxy:80", "http://httpsproxy:80", [])
    assert list(cfg["http://example.com"]) == [Proxy.from_str("http://httpproxy:80")]
    assert list(cfg["https://example.com"]) == [Proxy.from_str("http://httpsproxy:80")]


def test_no_proxy_exact_and_subdomain_match():
    cfg = EnvProxyConfig("http://proxy:80", "http://proxy:80", ["example.com"])
    assert cfg["https://example.com"] == [None]
    assert cfg["https://api.example.com"] == [None]


def test_no_proxy_does_not_match_lookalike_domain():
    cfg = EnvProxyConfig("http://proxy:80", "http://proxy:80", ["example.com"])
    assert list(cfg["https://evilexample.com"]) == [Proxy.from_str("http://proxy:80")]


def test_no_proxy_leading_dot_entry():
    cfg = EnvProxyConfig("http://proxy:80", "http://proxy:80", [".example.com"])
    assert cfg["https://api.example.com"] == [None]
    assert cfg["https://example.com"] == [None]


def test_no_proxy_port_specific_entry():
    cfg = EnvProxyConfig("http://proxy:80", "http://proxy:80", ["example.com:8080"])
    assert cfg["http://example.com:8080"] == [None]
    assert list(cfg["http://example.com:80"]) == [Proxy.from_str("http://proxy:80")]


def test_no_proxy_cidr_matches_ip_literal():
    cfg = EnvProxyConfig("http://proxy:80", "http://proxy:80", ["10.0.0.0/8"])
    assert cfg["http://10.1.2.3"] == [None]
    assert list(cfg["http://11.0.0.1"]) == [Proxy.from_str("http://proxy:80")]


def test_no_proxy_cidr_ipv6_entry_parses_correctly():
    # IPv6 CIDRs contain ":" -- must be parsed as a network via the "/" before
    # the existing rpartition(":") host:port split runs, or the ":" inside
    # the address would be mangled into a bogus port split. (proxylib's own
    # URL parser doesn't yet support bracketed IPv6 literal hosts, so this is
    # checked at the entry-parsing level rather than through a full request.)
    import ipaddress

    from proxylib.env import _parse_no_proxy_entry

    assert _parse_no_proxy_entry("2001:db8::/32") == ipaddress.ip_network("2001:db8::/32")


def test_no_proxy_cidr_does_not_match_hostname_without_resolving(monkeypatch):
    import proxylib.env as env

    def boom(host):
        raise AssertionError("DNS resolution attempted for a CIDR NO_PROXY entry")

    monkeypatch.setattr(env, "get_ip", boom)
    cfg = EnvProxyConfig("http://proxy:80", "http://proxy:80", ["10.0.0.0/8"])
    assert list(cfg["http://example.com"]) == [Proxy.from_str("http://proxy:80")]


def test_default_no_proxy_is_merged_in():
    set_default_no_proxy(["example.com"])
    cfg = EnvProxyConfig("http://proxy:80", "http://proxy:80", [])
    assert cfg["https://example.com"] == [None]


def test_default_no_proxy_does_not_override_explicit_rules():
    set_default_no_proxy(["other.com"])
    cfg = EnvProxyConfig("http://proxy:80", "http://proxy:80", ["example.com"])
    assert cfg["https://example.com"] == [None]
    assert cfg["https://other.com"] == [None]


def test_get_default_no_proxy_returns_a_copy():
    set_default_no_proxy(["example.com"])
    rules = get_default_no_proxy()
    rules.append("mutated.com")
    assert get_default_no_proxy() == ["example.com"]


def test_no_proxy_local_bypasses_loopback():
    cfg = EnvProxyConfig("http://proxy:80", "http://proxy:80", ["<local>"])
    assert cfg["http://127.0.0.1"] == [None]


def test_no_proxy_local_bypasses_link_local():
    # 169.254/16 is inherently non-routable beyond the local link -- bypass
    # it even without a matching local interface subnet (shared helper with
    # ConfigurableProxyMap's bypass_local=).
    cfg = EnvProxyConfig("http://proxy:80", "http://proxy:80", ["<local>"])
    assert cfg["http://169.254.1.1"] == [None]


def test_env_accepts_trailing_slash_proxy_urls():
    # The common HTTP_PROXY="http://proxy:8080/" shape must build a plain
    # proxy map -- it used to be misrouted into the PAC loader (network I/O
    # from the constructor, then failure).
    cfg = EnvProxyConfig("http://proxy:8080/", "http://sproxy:443/", [])
    assert list(cfg["http://example.com"]) == [Proxy.from_str("http://proxy:8080")]
    assert list(cfg["https://example.com"]) == [Proxy.from_str("http://sproxy:443")]


def test_env_does_not_resolve_dns_without_local_entry(monkeypatch):
    import proxylib.env as env

    def boom(host):
        raise AssertionError("DNS resolution attempted without a <local> entry")

    monkeypatch.setattr(env, "get_ip", boom)
    cfg = EnvProxyConfig("http://proxy:80", "http://proxy:80", ["other.com"])
    assert list(cfg["http://example.com"]) == [Proxy.from_str("http://proxy:80")]


def test_from_env_reads_upper_and_lower_case(monkeypatch):
    monkeypatch.delenv("HTTP_PROXY", raising=False)
    monkeypatch.delenv("HTTPS_PROXY", raising=False)
    monkeypatch.delenv("NO_PROXY", raising=False)
    monkeypatch.setenv("http_proxy", "http://proxy:80")
    monkeypatch.setenv("no_proxy", "localhost, example.com")

    cfg = EnvProxyConfig.from_env()
    assert cfg["http://localhost"] == [None]
    assert cfg["http://example.com"] == [None]
    assert list(cfg["http://other.com"]) == [Proxy.from_str("http://proxy:80")]
