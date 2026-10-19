"""proxylib.system: ProxyConfig, each OS's settings as pure functions,
auto_proxy's precedence, and the OS resolvers behind their seams."""

import sys
import time

import pytest

from proxylib import MissingExtraError, Proxy, ProxyConfig, SimpleProxyMap, auto_proxy, lookup
from proxylib import system
from proxylib.bypass import BypassRules
from proxylib.pac import engines
from proxylib.system import _config, _darwin, _nt
from proxylib.system._posix import _libproxy


@pytest.fixture
def discover_calls(monkeypatch):
    """Counts WPAD discovery calls; discovery finds nothing."""
    calls = []
    monkeypatch.setattr("proxylib.pac.wpad.discover", lambda *a, **k: calls.append(k) or None)
    return calls


def _windows(monkeypatch, *settings):
    """Stand in for Windows with these Internet Options settings."""
    monkeypatch.setattr(system, "_PLATFORM", "win32")
    monkeypatch.setattr(_nt, "_read_ie_proxy_config", lambda: _nt._IEProxySettings(*settings))


def _no_resolver(monkeypatch):
    built = []
    monkeypatch.setattr(system, "_os_resolver", lambda: built.append(1))
    return built


def _hosts(answer):
    return [p.host if p else None for p in answer]


# ---- ProxyConfig ---------------------------------------------------------------


def test_proxyconfig_defaults_to_unset_and_parses_proxy_strings():
    config = ProxyConfig(source="test", state="configured", proxies={"HTTP": "a:1"})
    assert ProxyConfig().state == "unset" and ProxyConfig().source == "none"
    assert config.proxies == {"http": Proxy("http", "a", 1)}
    with pytest.raises(TypeError):
        config.proxies["https"] = Proxy("http", "b", 1)
    with pytest.raises(ValueError, match="state"):
        ProxyConfig(state="maybe")


def test_direct_state_is_direct_for_everything_and_never_discovers(discover_calls):
    proxymap = ProxyConfig(state="direct", auto_detect=True).to_proxymap(wpad=True)
    assert proxymap["http://x/"] == (None,)
    assert discover_calls == []


def test_manual_proxies_per_scheme_with_socks_as_the_fallback():
    config = ProxyConfig(
        state="configured", proxies={"https": "b:443", "socks": Proxy("socks5", "s", 1080)}
    )
    proxymap = config.to_proxymap()
    assert proxymap["https://x/"] == (Proxy("http", "b", 443),)
    assert proxymap["wss://x/"] == (Proxy("http", "b", 443),)
    assert proxymap["http://x/"] == (Proxy("socks5", "s", 1080),)


def test_a_scheme_with_no_proxy_is_direct_and_not_cross_filled():
    proxymap = ProxyConfig(state="configured", proxies={"https": "b:443"}).to_proxymap()
    assert proxymap["http://x/"] == (None,)
    assert proxymap["ftp://x/"] == (None,)


def test_bypass_applies_to_the_manual_proxies():
    config = ProxyConfig(
        state="configured", proxies={"http": "a:1"}, bypass=BypassRules.parse("*.internal", dialect="wininet")
    )
    proxymap = config.to_proxymap()
    assert proxymap["http://app.internal/"] == (None,)
    assert proxymap["http://localhost/"] == (None,)
    assert _hosts(proxymap["http://example.com/"]) == ["a"]


def test_wpad_runs_when_the_os_asks_or_when_asked_and_unset(discover_calls):
    ProxyConfig(state="configured", auto_detect=True).to_proxymap()["http://x/"]
    assert len(discover_calls) == 1
    ProxyConfig(state="unset").to_proxymap(wpad=True)["http://x/"]
    assert len(discover_calls) == 2
    ProxyConfig(state="unset").to_proxymap()["http://x/"]
    ProxyConfig(state="configured", proxies={"http": "a:1"}).to_proxymap(wpad=True)["http://x/"]
    assert len(discover_calls) == 2


def test_nothing_is_fetched_until_the_first_lookup(discover_calls):
    proxymap = ProxyConfig(state="configured", auto_detect=True).to_proxymap()
    assert discover_calls == []
    proxymap["http://x/"]
    assert len(discover_calls) == 1


def test_a_failing_source_passes_to_the_next_and_is_retried_later(monkeypatch, discover_calls, tmp_path):
    config = ProxyConfig(
        state="configured",
        auto_detect=True,
        pac_url=(tmp_path / "missing.pac").as_uri(),
        proxies={"http": "a:1"},
    )
    proxymap = config.to_proxymap()
    assert _hosts(proxymap["http://x/"]) == ["a"]
    assert _hosts(proxymap["http://y/"]) == ["a"]
    assert len(discover_calls) == 1
    now = time.monotonic()
    monkeypatch.setattr(_config.time, "monotonic", lambda: now + _config._RETRY_AFTER + 1)
    proxymap["http://z/"]
    assert len(discover_calls) == 2


def test_wpad_answers_before_the_pac_and_the_proxies(monkeypatch):
    monkeypatch.setattr("proxylib.pac.wpad.discover", lambda *a, **k: SimpleProxyMap("PROXY w:1"))
    config = ProxyConfig(state="configured", auto_detect=True, pac_url="http://pac.invalid/x.pac", proxies={"http": "a:1"})
    assert _hosts(config.to_proxymap()["http://x/"]) == ["w"]


def test_a_missing_js_engine_is_not_swallowed(monkeypatch):
    monkeypatch.setattr(engines, "_installed", lambda name: False)
    config = ProxyConfig(state="configured", pac_script="function FindProxyForURL(u, h) { return 'DIRECT'; }")
    with pytest.raises(MissingExtraError):
        config.to_proxymap()["http://x/"]
    with pytest.warns(UserWarning, match="DIRECT"):
        assert config.to_proxymap(on_missing_engine="direct")["http://x/"] == (None,)


# ---- Windows settings ----------------------------------------------------------


def _windows_map(proxy, bypass=None, auto_detect=False, pac_url=None):
    return _nt.config_from_settings(_nt._IEProxySettings(auto_detect, pac_url, proxy, bypass)).to_proxymap()


def test_windows_socks_entry_alone_is_socks4_for_every_scheme():
    assert _windows_map("socks=c:1080")["http://x/"] == (Proxy("socks4", "c", 1080),)


def test_windows_https_entry_alone_leaves_http_direct():
    proxymap = _windows_map("https=b:443")
    assert proxymap["http://x/"] == (None,)
    assert proxymap["https://x/"] == (Proxy("http", "b", 443),)


def test_windows_one_server_serves_http_https_and_ftp():
    proxymap = _windows_map("proxy.example.com:8080")
    for url in ("http://x/", "https://x/", "ftp://x/"):
        assert proxymap[url] == (Proxy("http", "proxy.example.com", 8080),)


def test_windows_per_protocol_entries():
    proxymap = _windows_map("http=h:80;https=s:443 ftp=f:21")
    assert _hosts(proxymap["http://x/"]) == ["h"]
    assert _hosts(proxymap["https://x/"]) == ["s"]
    assert _hosts(proxymap["ftp://x/"]) == ["f"]


def test_windows_proxy_override_uses_wininet_syntax():
    proxymap = _windows_map("proxy:8080", "*.corp.example.com;10.*;<local>")
    assert proxymap["http://a.corp.example.com/"] == (None,)
    assert proxymap["http://10.9.9.9/"] == (None,)
    assert proxymap["http://intranet/"] == (None,)
    assert _hosts(proxymap["http://example.com/"]) == ["proxy"]


def test_windows_with_nothing_switched_on_is_direct_and_never_discovers(monkeypatch, discover_calls):
    _windows(monkeypatch, False, None, None, None)
    assert system.system_config().state == "direct"
    assert auto_proxy(system=False, environ={})["http://x/"] == (None,)
    assert discover_calls == []


def test_windows_auto_detect_discovers_once(monkeypatch, discover_calls):
    _windows(monkeypatch, True, None, None, None)
    config = system.system_config()
    assert (config.source, config.state, config.auto_detect) == ("windows", "configured", True)
    assert auto_proxy(system=False, environ={})["http://x/"] == (None,)
    assert len(discover_calls) == 1


def test_windows_settings_that_cannot_be_read_are_unset(monkeypatch):
    monkeypatch.setattr(system, "_PLATFORM", "win32")
    monkeypatch.setattr(_nt, "_read_ie_proxy_config", lambda: None)
    assert system.system_config() == ProxyConfig()


# ---- macOS settings ------------------------------------------------------------


def test_macos_socks_only_is_socks5_for_every_scheme():
    config = _darwin.config_from_scutil({"SOCKSEnable": "1", "SOCKSProxy": "s", "SOCKSPort": "1080"})
    assert config.to_proxymap()["https://x/"] == (Proxy("socks5", "s", 1080),)


def test_macos_https_only_leaves_http_direct():
    config = _darwin.config_from_scutil({"HTTPSEnable": "1", "HTTPSProxy": "b", "HTTPSPort": "3128"})
    proxymap = config.to_proxymap()
    assert proxymap["http://x/"] == (None,)
    assert proxymap["https://x/"] == (Proxy("http", "b", 3128),)


def test_macos_nothing_enabled_is_direct_and_no_output_is_unset():
    assert _darwin.config_from_scutil({"HTTPEnable": "0", "ExcludeSimpleHostnames": "0"}).state == "direct"
    assert _darwin.config_from_scutil({}) is None


def test_macos_pac_and_auto_discovery():
    config = _darwin.config_from_scutil(
        {"ProxyAutoDiscoveryEnable": "1", "ProxyAutoConfigEnable": "1", "ProxyAutoConfigURLString": "http://pac/x.pac"}
    )
    assert (config.auto_detect, config.pac_url) == (True, "http://pac/x.pac")
    disabled = _darwin.config_from_scutil({"ProxyAutoConfigEnable": "0", "ProxyAutoConfigURLString": "http://pac/x.pac"})
    assert disabled.pac_url is None and disabled.state == "direct"


def test_macos_exceptions_use_macos_syntax():
    config = _darwin.config_from_scutil(
        {
            "HTTPEnable": "1",
            "HTTPProxy": "proxy",
            "HTTPPort": "8080",
            "ExceptionsList": ["*.local", "169.254/16"],
            "ExcludeSimpleHostnames": "1",
        }
    )
    proxymap = config.to_proxymap()
    assert proxymap["http://printer.local/"] == (None,)
    assert proxymap["http://169.254.1.1/"] == (None,)
    assert proxymap["http://intranet/"] == (None,)
    assert proxymap["http://example.com/"] == (Proxy("http", "proxy", 8080),)


def test_macos_reads_scutil_through_the_runner(monkeypatch):
    output = (
        "<dictionary> {\n"
        "  ExceptionsList : <array> {\n    0 : *.local\n  }\n"
        "  HTTPEnable : 1\n  HTTPPort : 3128\n  HTTPProxy : proxy.example.com\n"
        "}\n"
    )
    seen = []
    monkeypatch.setattr(_darwin._run, "run", lambda argv, **k: seen.append(argv) or output)
    monkeypatch.setattr(system, "_PLATFORM", "darwin")
    config = system.system_config()
    assert seen == [["scutil", "--proxy"]]
    assert config.proxies == {"http": Proxy("http", "proxy.example.com", 3128)}
    assert config.bypass.matches("http://printer.local/")


# ---- auto_proxy ----------------------------------------------------------------


def test_environment_variables_win_over_the_os_settings(monkeypatch):
    _windows(monkeypatch, False, None, "manual:3128", None)
    built = _no_resolver(monkeypatch)
    proxymap = auto_proxy(environ={"HTTP_PROXY": "http://p:1"})
    assert _hosts(proxymap["http://x/"]) == ["p"]
    assert proxymap["https://x/"] == (None,)
    assert built == []


def test_a_pac_location_in_a_proxy_variable_is_loaded(monkeypatch, http_server):
    if not engines.names():
        pytest.skip("no JS engine installed")
    http_server.route("/proxy.pac", b'function FindProxyForURL(u, h) { return "PROXY from-pac:8080"; }')
    built = _no_resolver(monkeypatch)
    proxymap = auto_proxy(environ={"HTTP_PROXY": http_server.url("/proxy.pac")})
    assert _hosts(proxymap["http://x/"]) == ["from-pac"]
    assert built == []


def test_an_empty_or_no_proxy_only_environment_reads_the_os(monkeypatch):
    _windows(monkeypatch, False, None, "manual:3128", None)
    _no_resolver(monkeypatch)
    for environ in ({}, {"HTTP_PROXY": ""}, {"NO_PROXY": "example.com"}):
        assert _hosts(auto_proxy(environ=environ)["http://x/"]) == ["manual"]


def test_the_os_resolver_answers_first(monkeypatch):
    _windows(monkeypatch, False, None, "manual:3128", None)
    monkeypatch.setattr(system, "_os_resolver", lambda: SimpleProxyMap("PROXY native:1"))
    assert _hosts(auto_proxy(environ={})["http://x/"]) == ["native"]


def test_a_url_the_os_resolver_cannot_answer_goes_to_the_settings(monkeypatch):
    class NoOpinion:
        def __getitem__(self, url):
            raise KeyError(url)

    _windows(monkeypatch, False, None, "manual:3128", None)
    monkeypatch.setattr(system, "_os_resolver", lambda: NoOpinion())
    assert _hosts(auto_proxy(environ={})["http://x/"]) == ["manual"]


def test_system_false_never_builds_an_os_resolver(monkeypatch):
    _windows(monkeypatch, False, None, "manual:3128", None)
    built = []
    monkeypatch.setattr(system, "_os_resolver", lambda: built.append(1) or SimpleProxyMap("PROXY native:1"))
    assert _hosts(auto_proxy(system=False, environ={})["http://x/"]) == ["manual"]
    assert built == []


def test_without_libproxy_only_the_settings_answer(monkeypatch):
    monkeypatch.setattr(system, "_PLATFORM", "linux")
    monkeypatch.setattr(_libproxy, "_libproxy", None)
    monkeypatch.setattr(system._posix, "read_config", lambda: ProxyConfig(source="gnome", state="configured", proxies={"http": "g:1"}))
    assert system._os_resolver() is None
    proxymap = auto_proxy(environ={})
    assert type(proxymap).__name__ == "Bypass"
    assert _hosts(proxymap["http://x/"]) == ["g"]


def test_with_libproxy_its_map_is_the_resolver(monkeypatch):
    monkeypatch.setattr(system, "_PLATFORM", "linux")
    fake = object()
    monkeypatch.setattr(_libproxy, "_libproxy", fake)
    resolver = system._os_resolver()
    assert isinstance(resolver, system.LibProxyMap) and resolver._lib is fake


def test_no_proxy_is_applied_over_everything(monkeypatch):
    _no_resolver(monkeypatch)
    _windows(monkeypatch, False, None, "manual:3128", None)
    assert auto_proxy(environ={}, no_proxy=["internal.test"])["http://internal.test/"] == (None,)
    assert auto_proxy(environ={"HTTP_PROXY": "http://p:1"}, no_proxy="internal.test")["http://internal.test/"] == (None,)


def test_the_provider_keyword_is_gone():
    with pytest.raises(TypeError):
        auto_proxy(provider="system")


def test_auto_proxy_answers_every_url(monkeypatch):
    _no_resolver(monkeypatch)
    monkeypatch.setattr(system, "_PLATFORM", "linux")
    monkeypatch.setattr(system._posix, "read_config", lambda: None)
    assert lookup(auto_proxy(environ={}), "http://x/") == (None,)


# ---- WinHTTPProxyMap -----------------------------------------------------------


@pytest.mark.skipif(sys.platform != "win32", reason="Windows WinHTTP backend")
class TestWinHTTPProxyMap:
    """A real WinHttpOpen() session (no network I/O); WinHttpGetProxyForUrl
    itself is replaced through the _query_proxy_for_url seam."""

    def _map(self, monkeypatch, settings, query=None):
        monkeypatch.setattr(_nt, "_read_ie_proxy_config", lambda: _nt._IEProxySettings(*settings))
        if query is not None:
            monkeypatch.setattr(_nt, "_query_proxy_for_url", query)
        return _nt.WinHTTPProxyMap()

    def test_has_no_opinion_after_close(self):
        proxymap = _nt.WinHTTPProxyMap()
        proxymap.close()
        with pytest.raises(KeyError):
            proxymap["http://example.com"]

    def test_direct_when_nothing_configured(self, monkeypatch):
        def boom(*a, **k):
            raise AssertionError("nothing to auto-detect")

        proxymap = self._map(monkeypatch, (False, None, None, None), boom)
        assert proxymap["http://example.com"] == (None,)
        proxymap.close()

    def test_autodetect_resolves_a_proxy_or_direct(self, monkeypatch):
        proxymap = self._map(monkeypatch, (True, None, None, None), lambda *a, **k: ("proxy.example.com:8080", None, True, 0))
        assert proxymap["http://example.com"] == (Proxy("http", "proxy.example.com", 8080),)
        monkeypatch.setattr(_nt, "_query_proxy_for_url", lambda *a, **k: (None, None, True, 0))
        assert proxymap["http://example.com"] == (None,)
        proxymap.close()

    def test_retries_with_auto_logon_on_login_failure(self, monkeypatch):
        calls = []

        def query(hsession, url, auto_detect, auto_config_url, auto_logon):
            calls.append(auto_logon)
            if not auto_logon:
                return None, None, False, _nt._ERROR_WINHTTP_LOGIN_FAILURE
            return "proxy.example.com:8080", None, True, 0

        proxymap = self._map(monkeypatch, (True, None, None, None), query)
        assert _hosts(proxymap["http://example.com"]) == ["proxy.example.com"]
        proxymap.close()
        assert calls == [False, True]

    def test_falls_back_to_the_manual_proxy_when_autodetect_fails(self, monkeypatch):
        proxymap = self._map(monkeypatch, (True, None, "proxy.example.com:8080", None), lambda *a, **k: (None, None, False, 12180))
        assert _hosts(proxymap["http://example.com"]) == ["proxy.example.com"]
        proxymap.close()

    def test_direct_when_autodetect_fails_and_no_manual_proxy(self, monkeypatch):
        proxymap = self._map(monkeypatch, (True, None, None, None), lambda *a, **k: (None, None, False, 12180))
        assert proxymap["http://example.com"] == (None,)
        proxymap.close()

    def test_real_winhttp_session_smoke(self):
        proxymap = _nt.WinHTTPProxyMap()
        try:
            assert all(p is None or isinstance(p, Proxy) for p in proxymap["http://example.com"])
        finally:
            proxymap.close()


@pytest.mark.skipif(sys.platform == "win32", reason="WinHTTP exists here")
def test_winhttp_map_off_windows_is_an_oserror():
    with pytest.raises(OSError):
        _nt.WinHTTPProxyMap()


def test_winhttp_proxy_list_keeps_every_entry_in_order():
    def urls(url, value):
        return [p.url for p in _nt._resolve_for_scheme(url, value)]

    assert urls("http://x/", "p1:8080;p2:8080") == ["http://p1:8080", "http://p2:8080"]
    assert urls("https://x/", "http=a:1 https=b:2 c:3") == ["http://b:2", "http://c:3"]
    assert urls("ftp://x/", "http=a:1;https=b:2") == ["http://a:1"]


# ---- CFNetworkProxyMap ---------------------------------------------------------
# Replaced at the _resolve_proxies_for_url seam, so these run on every OS.


def test_cfnetwork_failure_is_no_opinion(monkeypatch):
    monkeypatch.setattr(_darwin, "_resolve_proxies_for_url", lambda url, deadline: None)
    with pytest.raises(KeyError):
        _darwin.CFNetworkProxyMap()["http://example.com"]


def test_cfnetwork_answers_in_order(monkeypatch):
    monkeypatch.setattr(_darwin, "_resolve_proxies_for_url", lambda url, deadline: ["http://p1:80", "http://p2:80", None])
    assert _hosts(_darwin.CFNetworkProxyMap()["http://example.com"]) == ["p1", "p2", None]
    monkeypatch.setattr(_darwin, "_resolve_proxies_for_url", lambda url, deadline: [None])
    assert _darwin.CFNetworkProxyMap()["http://example.com"] == (None,)


def test_cfnetwork_passes_the_deadline_through(monkeypatch):
    seen = {}

    def resolve(url, deadline):
        seen.update(url=url, deadline=deadline)
        return [None]

    monkeypatch.setattr(_darwin, "_resolve_proxies_for_url", resolve)
    _darwin.CFNetworkProxyMap(deadline=2.5)["http://example.com"]
    assert seen == {"url": "http://example.com", "deadline": 2.5}


@pytest.mark.skipif(sys.platform != "darwin", reason="real CFNetwork/CoreFoundation call")
def test_cfnetworkproxymap_real_smoke():
    result = _darwin.CFNetworkProxyMap()["http://example.com"]
    assert all(p is None or isinstance(p, Proxy) for p in result)


def _fake_cf_bindings(monkeypatch):
    import types

    monkeypatch.setattr(_darwin, "_cfstring_to_str", lambda cf, ref: ref)
    monkeypatch.setattr(_darwin, "_cfnumber_to_int", lambda cf, ref: ref)
    cf = types.SimpleNamespace(CFDictionaryGetValue=lambda entry, key: entry.get(key))
    names = ("None", "AutoConfigurationURL", "HTTP", "HTTPS", "SOCKS", "FTP")
    return types.SimpleNamespace(
        cf=cf,
        kCFProxyTypeKey="type",
        kCFProxyHostNameKey="host",
        kCFProxyPortNumberKey="port",
        kCFProxyAutoConfigurationURLKey="pac",
        **{f"kCFProxyType{name}": name for name in names},
    )


def test_cfnetwork_https_entry_is_a_plain_http_proxy(monkeypatch):
    cfb = _fake_cf_bindings(monkeypatch)
    assert _darwin._parse_proxy_entry(cfb, {"type": "HTTPS", "host": "proxy", "port": 3128}) == ("proxy", "http://proxy:3128")


def test_cfnetwork_unknown_or_hostless_entry_is_skipped(monkeypatch):
    cfb = _fake_cf_bindings(monkeypatch)
    assert _darwin._parse_proxy_entry(cfb, {"type": "JavaScript"}) == ("skip", None)
    assert _darwin._parse_proxy_entry(cfb, {"type": "HTTP", "host": None}) == ("skip", None)
    assert _darwin._parse_proxy_entry(cfb, {"type": "None"}) == ("direct", None)
