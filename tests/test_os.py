import sys

import pytest

from proxylib.env import EnvProxyConfig
from proxylib.proxy import SimpleProxyMap


def test_dispatches_to_platform_backend(monkeypatch):
    import proxylib.os as proxylib_os

    sentinel = SimpleProxyMap()
    monkeypatch.setattr(proxylib_os, "_python_system_proxy", lambda: sentinel)

    assert proxylib_os.system_proxy() is sentinel


def test_auto_proxy_returns_proxy_map_for_direct_env(monkeypatch):
    import proxylib.os as proxylib_os

    monkeypatch.setattr(proxylib_os, "system_proxy", lambda provider="python": SimpleProxyMap())
    monkeypatch.setattr(
        "proxylib.pac.wpad.discover", lambda *a, **k: None
    )

    result = proxylib_os.auto_proxy()
    assert isinstance(result, SimpleProxyMap)


def test_auto_proxy_falls_back_to_wpad(monkeypatch):
    import proxylib.os as proxylib_os
    from proxylib.pac import PAC

    monkeypatch.setattr(proxylib_os, "system_proxy", lambda provider="python": SimpleProxyMap())
    sentinel = PAC()
    monkeypatch.setattr("proxylib.pac.wpad.discover", lambda *a, **k: sentinel)

    result = proxylib_os.auto_proxy()
    assert result is sentinel


def test_auto_proxy_loads_pac_url_string(monkeypatch):
    import proxylib.os as proxylib_os
    from proxylib.pac import PAC

    monkeypatch.setattr(proxylib_os, "system_proxy", lambda provider="python": "file:examples/example.pac")

    result = proxylib_os.auto_proxy()
    assert isinstance(result, PAC)


def test_auto_proxy_passes_through_env_config(monkeypatch):
    import proxylib.os as proxylib_os

    cfg = EnvProxyConfig("http://proxy:80", "http://proxy:80", [])
    monkeypatch.setattr(proxylib_os, "system_proxy", lambda provider="python": cfg)

    result = proxylib_os.auto_proxy()
    assert result is cfg


def test_auto_proxy_passes_provider_through_to_system_proxy(monkeypatch):
    import proxylib.os as proxylib_os

    seen = []
    monkeypatch.setattr(
        proxylib_os, "system_proxy", lambda provider="python": (seen.append(provider), SimpleProxyMap())[1]
    )
    monkeypatch.setattr("proxylib.pac.wpad.discover", lambda *a, **k: None)

    proxylib_os.auto_proxy(provider="system")
    assert seen == ["system"]


def test_system_proxy_provider_system_uses_native_provider(monkeypatch):
    import proxylib.os as proxylib_os

    sentinel = SimpleProxyMap()  # stand-in for a native ProxyMap instance
    monkeypatch.setattr(proxylib_os, "_native_system_provider", lambda: sentinel)

    assert proxylib_os.system_proxy(provider="system") is sentinel


def test_system_proxy_provider_system_falls_back_to_python_when_native_unavailable(monkeypatch):
    import proxylib.os as proxylib_os

    fallback = SimpleProxyMap()
    monkeypatch.setattr(proxylib_os, "_native_system_provider", lambda: None)
    monkeypatch.setattr(proxylib_os, "_python_system_proxy", lambda: fallback)

    assert proxylib_os.system_proxy(provider="system") is fallback


def test_system_proxy_provider_python_never_calls_native_provider(monkeypatch):
    import proxylib.os as proxylib_os

    def boom():
        raise AssertionError("provider='python' must not touch the native provider")

    monkeypatch.setattr(proxylib_os, "_native_system_provider", boom)
    monkeypatch.setattr(proxylib_os, "_python_system_proxy", lambda: SimpleProxyMap())

    proxylib_os.system_proxy(provider="python")
    proxylib_os.system_proxy()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows WinHTTP backend")
def test_nt_system_proxy_direct_when_no_settings(monkeypatch):
    import proxylib.os.nt as nt

    monkeypatch.setattr(nt, "_read_ie_proxy_config", lambda: nt._IEProxySettings(False, None, None, None))

    assert isinstance(nt.system_proxy(), SimpleProxyMap)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows WinHTTP backend")
def test_nt_system_proxy_auto_detect_uses_wpad_first(monkeypatch):
    import proxylib.os.nt as nt
    from proxylib.pac import PAC

    monkeypatch.setattr(
        nt, "_read_ie_proxy_config", lambda: nt._IEProxySettings(True, "http://ignored/proxy.pac", None, None)
    )
    sentinel = PAC()
    monkeypatch.setattr(nt, "_wpad_discover", lambda *a, **k: sentinel)

    assert nt.system_proxy() is sentinel


@pytest.mark.skipif(sys.platform != "win32", reason="Windows WinHTTP backend")
def test_nt_system_proxy_falls_back_to_pac_url_when_autodetect_fails(monkeypatch):
    import proxylib.os.nt as nt

    monkeypatch.setattr(
        nt, "_read_ie_proxy_config", lambda: nt._IEProxySettings(True, "http://internal/proxy.pac", None, None)
    )
    monkeypatch.setattr(nt, "_wpad_discover", lambda *a, **k: None)

    assert nt.system_proxy() == "http://internal/proxy.pac"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows WinHTTP backend")
def test_nt_system_proxy_manual_proxy_all_protocols(monkeypatch):
    import proxylib.os.nt as nt
    from proxylib import Proxy

    monkeypatch.setattr(
        nt,
        "_read_ie_proxy_config",
        lambda: nt._IEProxySettings(False, None, "proxy.example.com:8080", "localhost;*.internal"),
    )

    result = nt.system_proxy()
    assert isinstance(result, EnvProxyConfig)
    assert list(result["http://example.com"]) == [Proxy.from_str("http://proxy.example.com:8080")]
    assert result["http://localhost"] == [None]


@pytest.mark.skipif(sys.platform != "win32", reason="Windows WinHTTP backend")
def test_nt_system_proxy_manual_proxy_per_protocol(monkeypatch):
    import proxylib.os.nt as nt
    from proxylib import Proxy

    monkeypatch.setattr(
        nt,
        "_read_ie_proxy_config",
        lambda: nt._IEProxySettings(False, None, "http=h:80;https=s:443", None),
    )

    result = nt.system_proxy()
    assert list(result["http://example.com"]) == [Proxy.from_str("http://h:80")]
    assert list(result["https://example.com"]) == [Proxy.from_str("http://s:443")]


# ---- WinHttpProxyMap (WinHttpGetProxyForUrl) ----------------------------------


@pytest.mark.skipif(sys.platform != "win32", reason="Windows WinHTTP backend")
class TestWinHttpProxyMap:
    """These construct a real WinHttpOpen() session (cheap, no network I/O)
    but stub the WinHttpGetProxyForUrl call itself via the _query_proxy_for_url
    seam, so no real autoproxy/network resolution happens."""

    def test_raises_keyerror_after_close(self):
        import proxylib.os.nt as nt

        m = nt.WinHttpProxyMap()
        m.close()
        with pytest.raises(KeyError):
            m["http://example.com"]

    def test_direct_when_nothing_configured(self, monkeypatch):
        import proxylib.os.nt as nt

        monkeypatch.setattr(nt, "_read_ie_proxy_config", lambda: nt._IEProxySettings(False, None, None, None))

        def boom(*a, **k):
            raise AssertionError("WinHttpGetProxyForUrl should not be called with nothing to autodetect")

        monkeypatch.setattr(nt, "_query_proxy_for_url", boom)

        m = nt.WinHttpProxyMap()
        try:
            assert m["http://example.com"] == [None]
        finally:
            m.close()

    def test_autodetect_resolves_proxy(self, monkeypatch):
        import proxylib.os.nt as nt
        from proxylib import Proxy

        monkeypatch.setattr(nt, "_read_ie_proxy_config", lambda: nt._IEProxySettings(True, None, None, None))
        monkeypatch.setattr(
            nt, "_query_proxy_for_url", lambda *a, **k: ("proxy.example.com:8080", None, True, 0)
        )

        m = nt.WinHttpProxyMap()
        try:
            assert list(m["http://example.com"]) == [Proxy.from_str("http://proxy.example.com:8080")]
        finally:
            m.close()

    def test_autodetect_resolves_direct(self, monkeypatch):
        import proxylib.os.nt as nt

        monkeypatch.setattr(nt, "_read_ie_proxy_config", lambda: nt._IEProxySettings(True, None, None, None))
        monkeypatch.setattr(nt, "_query_proxy_for_url", lambda *a, **k: (None, None, True, 0))

        m = nt.WinHttpProxyMap()
        try:
            assert m["http://example.com"] == [None]
        finally:
            m.close()

    def test_retries_with_auto_logon_on_login_failure(self, monkeypatch):
        import proxylib.os.nt as nt
        from proxylib import Proxy

        monkeypatch.setattr(nt, "_read_ie_proxy_config", lambda: nt._IEProxySettings(True, None, None, None))
        calls = []

        def fake_query(hsession, url, auto_detect, auto_config_url, auto_logon):
            calls.append(auto_logon)
            if not auto_logon:
                return None, None, False, nt._ERROR_WINHTTP_LOGIN_FAILURE
            return "proxy.example.com:8080", None, True, 0

        monkeypatch.setattr(nt, "_query_proxy_for_url", fake_query)

        m = nt.WinHttpProxyMap()
        try:
            assert list(m["http://example.com"]) == [Proxy.from_str("http://proxy.example.com:8080")]
        finally:
            m.close()
        assert calls == [False, True]

    def test_falls_back_to_manual_proxy_when_autodetect_fails(self, monkeypatch):
        import proxylib.os.nt as nt
        from proxylib import Proxy

        monkeypatch.setattr(
            nt,
            "_read_ie_proxy_config",
            lambda: nt._IEProxySettings(True, None, "proxy.example.com:8080", None),
        )
        # Some other failure (e.g. ERROR_WINHTTP_AUTODETECTION_FAILED) -- no retry.
        monkeypatch.setattr(nt, "_query_proxy_for_url", lambda *a, **k: (None, None, False, 12180))

        m = nt.WinHttpProxyMap()
        try:
            assert list(m["http://example.com"]) == [Proxy.from_str("http://proxy.example.com:8080")]
        finally:
            m.close()

    def test_direct_when_autodetect_fails_and_no_manual_proxy(self, monkeypatch):
        import proxylib.os.nt as nt

        monkeypatch.setattr(nt, "_read_ie_proxy_config", lambda: nt._IEProxySettings(True, None, None, None))
        monkeypatch.setattr(nt, "_query_proxy_for_url", lambda *a, **k: (None, None, False, 12180))

        m = nt.WinHttpProxyMap()
        try:
            assert m["http://example.com"] == [None]
        finally:
            m.close()

    def test_real_winhttp_session_smoke(self):
        # No mocking at all: exercises the real WinHttpOpen/GetProxyForUrl/
        # CloseHandle calls end-to-end against this machine's actual config.
        import proxylib.os.nt as nt

        m = nt.WinHttpProxyMap()
        try:
            result = list(m["http://example.com"])
            assert all(p is None or isinstance(p, nt.Proxy) for p in result)
        finally:
            m.close()


# darwin.py's system_proxy() just calls _read_scutil_proxy() (a subprocess.run wrapper)
# then decides; monkeypatching that one function makes these platform-independent.


def test_darwin_system_proxy_direct_when_no_settings(monkeypatch):
    import proxylib.os.darwin as darwin

    monkeypatch.setattr(darwin, "_read_scutil_proxy", lambda: {})

    assert isinstance(darwin.system_proxy(), SimpleProxyMap)


def test_darwin_system_proxy_auto_discovery_uses_wpad_first(monkeypatch):
    import proxylib.os.darwin as darwin
    from proxylib.pac import PAC

    monkeypatch.setattr(
        darwin,
        "_read_scutil_proxy",
        lambda: {
            "ProxyAutoDiscoveryEnable": "1",
            "ProxyAutoConfigEnable": "1",
            "ProxyAutoConfigURLString": "http://ignored/proxy.pac",
        },
    )
    sentinel = PAC()
    monkeypatch.setattr(darwin, "_wpad_discover", lambda *a, **k: sentinel)

    assert darwin.system_proxy() is sentinel


def test_darwin_system_proxy_falls_back_to_pac_when_discovery_fails(monkeypatch):
    import proxylib.os.darwin as darwin

    monkeypatch.setattr(
        darwin,
        "_read_scutil_proxy",
        lambda: {
            "ProxyAutoDiscoveryEnable": "1",
            "ProxyAutoConfigEnable": "1",
            "ProxyAutoConfigURLString": "http://internal/proxy.pac",
        },
    )
    monkeypatch.setattr(darwin, "_wpad_discover", lambda *a, **k: None)

    assert darwin.system_proxy() == "http://internal/proxy.pac"


# ---- CFNetworkProxyMap --------------------------------------------------------
#
# Fully mocked at the _resolve_proxies_for_url() seam -- these run on every
# platform (never touch real CFNetwork/ctypes), unlike the WinHttpProxyMap
# tests above which are Windows-only because they construct a real session.


def test_cfnetworkproxymap_raises_keyerror_on_resolution_failure(monkeypatch):
    import proxylib.os.darwin as darwin

    monkeypatch.setattr(darwin, "_resolve_proxies_for_url", lambda url, deadline: None)

    with pytest.raises(KeyError):
        darwin.CFNetworkProxyMap()["http://example.com"]


def test_cfnetworkproxymap_direct(monkeypatch):
    import proxylib.os.darwin as darwin

    monkeypatch.setattr(darwin, "_resolve_proxies_for_url", lambda url, deadline: [None])

    assert darwin.CFNetworkProxyMap()["http://example.com"] == [None]


def test_cfnetworkproxymap_resolves_proxy(monkeypatch):
    import proxylib.os.darwin as darwin
    from proxylib import Proxy

    monkeypatch.setattr(
        darwin, "_resolve_proxies_for_url", lambda url, deadline: ["http://proxy.example.com:8080"]
    )

    result = darwin.CFNetworkProxyMap()["http://example.com"]
    assert list(result) == [Proxy.from_str("http://proxy.example.com:8080")]


def test_cfnetworkproxymap_resolves_fallback_chain(monkeypatch):
    import proxylib.os.darwin as darwin
    from proxylib import Proxy

    monkeypatch.setattr(
        darwin,
        "_resolve_proxies_for_url",
        lambda url, deadline: ["http://p1:80", "http://p2:80", None],
    )

    result = list(darwin.CFNetworkProxyMap()["http://example.com"])
    assert result == [Proxy.from_str("http://p1:80"), Proxy.from_str("http://p2:80"), None]


def test_cfnetworkproxymap_passes_deadline_through(monkeypatch):
    import proxylib.os.darwin as darwin

    seen = {}

    def fake_resolve(url, deadline):
        seen["url"] = url
        seen["deadline"] = deadline
        return [None]

    monkeypatch.setattr(darwin, "_resolve_proxies_for_url", fake_resolve)

    darwin.CFNetworkProxyMap(deadline=2.5)["http://example.com"]
    assert seen == {"url": "http://example.com", "deadline": 2.5}


@pytest.mark.skipif(sys.platform != "darwin", reason="real CFNetwork/CoreFoundation call")
def test_cfnetworkproxymap_real_smoke():
    # No mocking at all: exercises the real CFNetworkCopySystemProxySettings/
    # CFNetworkCopyProxiesForURL ctypes calls end-to-end against this
    # machine's actual config -- the only thing that can actually validate
    # the hand-written CFNetwork bindings (see the UNVERIFIED note on
    # CFNetworkProxyMap; this test is what removes that caveat once green).
    import proxylib.os.darwin as darwin

    result = list(darwin.CFNetworkProxyMap()["http://example.com"])
    assert all(p is None or isinstance(p, darwin.Proxy) for p in result)


def test_darwin_system_proxy_manual_proxy(monkeypatch):
    import proxylib.os.darwin as darwin
    from proxylib import Proxy

    monkeypatch.setattr(
        darwin,
        "_read_scutil_proxy",
        lambda: {
            "HTTPEnable": "1",
            "HTTPProxy": "proxy.example.com",
            "HTTPPort": "8080",
            "ExceptionsList": ["localhost", "*.internal"],
        },
    )

    result = darwin.system_proxy()
    assert isinstance(result, EnvProxyConfig)
    assert list(result["http://example.com"]) == [
        Proxy.from_str("http://proxy.example.com:8080")
    ]
    assert result["http://localhost"] == [None]
