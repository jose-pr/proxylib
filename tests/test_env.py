from proxylib import Proxy
from proxylib.env import EnvProxyConfig


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


def test_no_proxy_local_bypasses_loopback():
    cfg = EnvProxyConfig("http://proxy:80", "http://proxy:80", ["<local>"])
    assert cfg["http://127.0.0.1"] == [None]


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
