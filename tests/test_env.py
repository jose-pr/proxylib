import os
import warnings

import pytest

from proxylib import BypassRules, EnvProxyConfig, Proxy, ProxyParseError, lookup


def _env(**names):
    return EnvProxyConfig.from_environ(names)


def test_selects_the_proxy_for_the_scheme():
    cfg = EnvProxyConfig(proxies={"http": "http://httpproxy:80", "https": "http://httpsproxy:80"})
    assert cfg["http://example.com"] == (Proxy.parse("http://httpproxy:80"),)
    assert cfg["https://example.com"] == (Proxy.parse("http://httpsproxy:80"),)


def test_unconfigured_scheme_is_no_opinion():
    cfg = EnvProxyConfig(proxies={"https": "http://p:1"})
    with pytest.raises(KeyError):
        cfg["http://example.com/"]


def test_all_proxy_covers_every_scheme():
    cfg = _env(ALL_PROXY="socks5://s:1080")
    assert cfg["http://x/"] == (Proxy("socks5", "s", 1080),)
    assert cfg["ftp://x/"] == (Proxy("socks5", "s", 1080),)


def test_scheme_proxy_wins_over_all_proxy():
    cfg = _env(all_proxy="http://all:1", https_proxy="http://tls:1")
    assert cfg["https://x/"][0].host == "tls"
    assert cfg["http://x/"][0].host == "all"


def test_any_scheme_proxy_variable_is_read():
    assert _env(ftp_proxy="http://f:21")["ftp://x/"][0].host == "f"


def test_websockets_use_the_http_proxies():
    cfg = _env(http_proxy="http://plain:1", https_proxy="http://tls:1")
    assert cfg["ws://x/"][0].host == "plain"
    assert cfg["wss://x/"][0].host == "tls"


def test_lowercase_wins_over_uppercase():
    assert _env(HTTP_PROXY="http://upper:1", http_proxy="http://lower:1")["http://x/"][0].host == "lower"
    assert _env(NO_PROXY="upper.test", no_proxy="lower.test").no_proxy.matches("http://lower.test/")


def test_scheme_less_values_are_http_proxies():
    assert _env(https_proxy="proxy:3128")["https://x/"] == (Proxy("http", "proxy", 3128),)


def test_trailing_slash_value_is_a_proxy():
    assert _env(http_proxy="http://proxy:8080/")["http://x/"] == (Proxy("http", "proxy", 8080),)


def test_pac_location_value_is_loaded_on_first_lookup(monkeypatch):
    import proxylib.pac as pac
    from proxylib import SimpleProxyMap

    loaded = []
    monkeypatch.setattr(pac, "load", lambda src: loaded.append(src) or SimpleProxyMap("PROXY a:1"))
    cfg = _env(HTTP_PROXY="http://wpad.corp/proxy.pac")
    assert loaded == []
    assert cfg["http://x/"][0].host == "a"
    assert loaded == ["http://wpad.corp/proxy.pac"]


def test_no_proxy_bypasses():
    cfg = _env(http_proxy="http://p:1", no_proxy="example.com, 10.0.0.0/8")
    assert cfg["http://api.example.com/"] == (None,)
    assert cfg["http://10.2.3.4/"] == (None,)
    assert cfg["http://other.test/"][0].host == "p"


def test_no_proxy_star_bypasses_even_with_no_proxy_configured():
    assert _env(NO_PROXY="*")["http://example.com/"] == (None,)


def test_no_proxy_accepts_bypass_rules():
    rules = BypassRules.parse("*.corp", dialect="wininet")
    cfg = EnvProxyConfig(proxies={"all": "http://p:1"}, no_proxy=rules)
    assert cfg["http://a.corp/"] == (None,)


def test_malformed_no_proxy_entry_warns_and_does_not_raise():
    with pytest.warns(UserWarning, match="10.0.0.0/33"):
        cfg = _env(http_proxy="http://p:1", NO_PROXY="10.0.0.0/33, example.com")
    assert cfg["http://example.com/"] == (None,)


def test_cgi_request_ignores_uppercase_http_proxy():
    # httpoxy: a CGI server turns the client's "Proxy:" header into HTTP_PROXY.
    cfg = _env(REQUEST_METHOD="GET", HTTP_PROXY="http://attacker:1", HTTPS_PROXY="http://ok:1")
    with pytest.raises(KeyError):
        cfg["http://example.com/"]
    assert cfg["https://example.com/"][0].host == "ok"


def test_cgi_request_keeps_lowercase_http_proxy():
    cfg = _env(REQUEST_METHOD="GET", http_proxy="http://trusted:1")
    assert cfg["http://example.com/"][0].host == "trusted"


@pytest.mark.skipif(os.name != "nt", reason="Windows environment names are case-insensitive")
def test_cgi_on_windows_ignores_http_proxy_from_os_environ(monkeypatch):
    monkeypatch.setenv("REQUEST_METHOD", "GET")
    monkeypatch.setenv("http_proxy", "http://attacker:1")
    with pytest.raises(KeyError):
        EnvProxyConfig.from_environ()["http://example.com/"]


def test_a_key_that_is_not_a_url_is_a_parse_error():
    with pytest.raises(ProxyParseError):
        _env(http_proxy="http://p:1")["http"]


def test_repr_hides_the_password():
    assert "secret" not in repr(_env(http_proxy="http://u:secret@p:1"))


def test_lookup_reads_an_env_config():
    assert lookup(_env(all_proxy="http://p:1"), "http://x/")[0].host == "p"


def test_empty_values_are_ignored():
    with pytest.raises(KeyError):
        _env(http_proxy="")["http://x/"]
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        _env(no_proxy="")
