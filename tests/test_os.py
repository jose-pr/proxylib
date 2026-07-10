import sys

import pytest

from proxylib.env import EnvProxyConfig
from proxylib.proxy import SimpleProxyMap


def test_dispatches_to_platform_backend():
    import proxylib.os as proxylib_os

    if sys.platform == "win32":
        from proxylib.os.nt import system_proxy as expected
    elif sys.platform == "darwin":
        from proxylib.os.darwin import system_proxy as expected
    else:
        from proxylib.os.posix import system_proxy as expected

    assert proxylib_os.system_proxy is expected


def test_auto_proxy_returns_proxy_map_for_direct_env(monkeypatch):
    import proxylib.os as proxylib_os

    monkeypatch.setattr(proxylib_os, "system_proxy", lambda: SimpleProxyMap())
    monkeypatch.setattr(
        "proxylib.pac.wpad.discover", lambda *a, **k: None
    )

    result = proxylib_os.auto_proxy()
    assert isinstance(result, SimpleProxyMap)


def test_auto_proxy_falls_back_to_wpad(monkeypatch):
    import proxylib.os as proxylib_os
    from proxylib.pac import PAC

    monkeypatch.setattr(proxylib_os, "system_proxy", lambda: SimpleProxyMap())
    sentinel = PAC()
    monkeypatch.setattr("proxylib.pac.wpad.discover", lambda *a, **k: sentinel)

    result = proxylib_os.auto_proxy()
    assert result is sentinel


def test_auto_proxy_loads_pac_url_string(monkeypatch):
    import proxylib.os as proxylib_os
    from proxylib.pac import PAC

    monkeypatch.setattr(proxylib_os, "system_proxy", lambda: "file:examples/example.pac")

    result = proxylib_os.auto_proxy()
    assert isinstance(result, PAC)


def test_auto_proxy_passes_through_env_config(monkeypatch):
    import proxylib.os as proxylib_os

    cfg = EnvProxyConfig("http://proxy:80", "http://proxy:80", [])
    monkeypatch.setattr(proxylib_os, "system_proxy", lambda: cfg)

    result = proxylib_os.auto_proxy()
    assert result is cfg


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
