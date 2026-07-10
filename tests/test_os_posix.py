from pathlib import Path

import pytest

from proxylib import Proxy
from proxylib.env import EnvProxyConfig
from proxylib.pac import PAC
from proxylib.proxy import SimpleProxyMap


def _fake_gsettings(values):
    def get(schema, key):
        return values.get((schema, key))

    return get


# ---- top-level dispatch ------------------------------------------------------


def test_posix_system_proxy_direct_when_nothing_configured(monkeypatch):
    import proxylib.os.posix as posix
    import proxylib.os.posix._gsettings as gsettings
    import proxylib.os.posix.kde as kde
    import proxylib.os.posix.libproxy as libproxy
    import proxylib.os.posix.networkmanager as networkmanager

    for name in ("HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy", "PROXY_PAC"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(gsettings, "_gsettings_get", _fake_gsettings({}))
    monkeypatch.setattr(kde, "_kioslaverc_path", lambda: Path("/nonexistent/kioslaverc"))
    monkeypatch.setattr(libproxy, "detect", lambda: None)
    monkeypatch.setattr(networkmanager, "_nmcli_get", lambda *a: [])
    monkeypatch.setattr(networkmanager, "_proxy_settings_via_dbus_send", lambda: None)

    assert isinstance(posix.system_proxy(), SimpleProxyMap)


def test_posix_system_proxy_backend_order_libproxy_wins_over_gnome(monkeypatch):
    import proxylib.os.posix as posix
    import proxylib.os.posix._gsettings as gsettings
    import proxylib.os.posix.libproxy as libproxy

    monkeypatch.delenv("PROXY_PAC", raising=False)
    monkeypatch.setattr(
        gsettings,
        "_gsettings_get",
        _fake_gsettings(
            {
                ("org.gnome.system.proxy", "mode"): "manual",
                ("org.gnome.system.proxy.http", "host"): "gnome-proxy",
                ("org.gnome.system.proxy.http", "port"): "80",
            }
        ),
    )
    sentinel = libproxy.LibProxyMap()
    monkeypatch.setattr(libproxy, "detect", lambda: sentinel)

    assert posix.system_proxy() is sentinel


def test_posix_system_proxy_backend_order_gnome_before_mate(monkeypatch):
    # Both "configured" -- GNOME (first checked after libproxy) should win.
    import proxylib.os.posix as posix
    import proxylib.os.posix._gsettings as gsettings
    import proxylib.os.posix.libproxy as libproxy

    monkeypatch.delenv("PROXY_PAC", raising=False)
    monkeypatch.setattr(libproxy, "detect", lambda: None)
    monkeypatch.setattr(
        gsettings,
        "_gsettings_get",
        _fake_gsettings(
            {
                ("org.gnome.system.proxy", "mode"): "manual",
                ("org.gnome.system.proxy.http", "host"): "gnome-proxy",
                ("org.gnome.system.proxy.http", "port"): "80",
                ("org.mate.system.proxy", "mode"): "manual",
                ("org.mate.system.proxy.http", "host"): "mate-proxy",
                ("org.mate.system.proxy.http", "port"): "80",
            }
        ),
    )

    result = posix.system_proxy()
    assert list(result["http://example.com"]) == [Proxy.from_str("http://gnome-proxy:80")]


# ---- GNOME / MATE (gsettings) -------------------------------------------------


def test_gnome_auto_with_url_returns_pac_url(monkeypatch):
    import proxylib.os.posix._gsettings as gsettings
    import proxylib.os.posix.gnome as gnome

    monkeypatch.setattr(
        gsettings,
        "_gsettings_get",
        _fake_gsettings(
            {
                ("org.gnome.system.proxy", "mode"): "auto",
                ("org.gnome.system.proxy", "autoconfig-url"): "http://internal/proxy.pac",
            }
        ),
    )

    assert gnome.detect() == "http://internal/proxy.pac"


def test_gnome_auto_blank_url_uses_wpad(monkeypatch):
    import proxylib.os.posix._gsettings as gsettings
    import proxylib.os.posix.gnome as gnome

    monkeypatch.setattr(
        gsettings,
        "_gsettings_get",
        _fake_gsettings(
            {
                ("org.gnome.system.proxy", "mode"): "auto",
                ("org.gnome.system.proxy", "autoconfig-url"): "",
            }
        ),
    )
    sentinel = PAC()
    monkeypatch.setattr(gsettings, "_wpad_discover", lambda *a, **k: sentinel)

    assert gnome.detect() is sentinel


def test_gnome_auto_blank_url_wpad_fails_returns_none(monkeypatch):
    import proxylib.os.posix._gsettings as gsettings
    import proxylib.os.posix.gnome as gnome

    monkeypatch.setattr(
        gsettings,
        "_gsettings_get",
        _fake_gsettings(
            {
                ("org.gnome.system.proxy", "mode"): "auto",
                ("org.gnome.system.proxy", "autoconfig-url"): "",
            }
        ),
    )
    monkeypatch.setattr(gsettings, "_wpad_discover", lambda *a, **k: None)

    assert gnome.detect() is None


def test_gnome_manual(monkeypatch):
    import proxylib.os.posix._gsettings as gsettings
    import proxylib.os.posix.gnome as gnome

    monkeypatch.setattr(
        gsettings,
        "_gsettings_get",
        _fake_gsettings(
            {
                ("org.gnome.system.proxy", "mode"): "manual",
                ("org.gnome.system.proxy.http", "host"): "proxy.example.com",
                ("org.gnome.system.proxy.http", "port"): "8080",
                ("org.gnome.system.proxy", "ignore-hosts"): "['localhost', '*.internal']",
            }
        ),
    )

    result = gnome.detect()
    assert isinstance(result, EnvProxyConfig)
    assert list(result["http://example.com"]) == [
        Proxy.from_str("http://proxy.example.com:8080")
    ]
    assert result["http://localhost"] == [None]


def test_mate_manual(monkeypatch):
    import proxylib.os.posix._gsettings as gsettings
    import proxylib.os.posix.mate as mate

    monkeypatch.setattr(
        gsettings,
        "_gsettings_get",
        _fake_gsettings(
            {
                ("org.mate.system.proxy", "mode"): "manual",
                ("org.mate.system.proxy.http", "host"): "mate-proxy.example.com",
                ("org.mate.system.proxy.http", "port"): "3128",
            }
        ),
    )

    result = mate.detect()
    assert isinstance(result, EnvProxyConfig)
    assert list(result["http://example.com"]) == [
        Proxy.from_str("http://mate-proxy.example.com:3128")
    ]


def test_gnome_returns_none_when_no_gsettings(monkeypatch):
    import proxylib.os.posix._gsettings as gsettings
    import proxylib.os.posix.gnome as gnome

    monkeypatch.setattr(gsettings, "_gsettings_get", _fake_gsettings({}))
    assert gnome.detect() is None


# ---- KDE (kioslaverc) --------------------------------------------------------


def _write_kioslaverc(tmp_path, content: str):
    path = tmp_path / "kioslaverc"
    path.write_text(content, encoding="utf-8")
    return path


def test_kde_none_when_file_absent(tmp_path, monkeypatch):
    import proxylib.os.posix.kde as kde

    monkeypatch.setattr(kde, "_kioslaverc_path", lambda: tmp_path / "kioslaverc")
    assert kde.detect() is None


def test_kde_manual(tmp_path, monkeypatch):
    import proxylib.os.posix.kde as kde

    path = _write_kioslaverc(
        tmp_path,
        "[Proxy Settings]\n"
        "ProxyType=1\n"
        "httpProxy=http://proxy.example.com 8080\n"
        "NoProxyFor=localhost,*.internal\n",
    )
    monkeypatch.setattr(kde, "_kioslaverc_path", lambda: path)

    result = kde.detect()
    assert isinstance(result, EnvProxyConfig)
    assert list(result["http://example.com"]) == [
        Proxy.from_str("http://proxy.example.com:8080")
    ]
    assert result["http://localhost"] == [None]


def test_kde_pac_script(tmp_path, monkeypatch):
    import proxylib.os.posix.kde as kde

    path = _write_kioslaverc(
        tmp_path,
        "[Proxy Settings]\nProxyType=2\nProxy Config Script=http://internal/proxy.pac\n",
    )
    monkeypatch.setattr(kde, "_kioslaverc_path", lambda: path)

    assert kde.detect() == "http://internal/proxy.pac"


def test_kde_pac_script_with_percent_sign(tmp_path, monkeypatch):
    # A literal "%" (e.g. percent-encoded URL) must not trip configparser's
    # default string interpolation.
    import proxylib.os.posix.kde as kde

    path = _write_kioslaverc(
        tmp_path,
        "[Proxy Settings]\nProxyType=2\nProxy Config Script=http://internal/proxy%20script.pac\n",
    )
    monkeypatch.setattr(kde, "_kioslaverc_path", lambda: path)

    assert kde.detect() == "http://internal/proxy%20script.pac"


def test_kde_wpad(tmp_path, monkeypatch):
    import proxylib.os.posix.kde as kde

    path = _write_kioslaverc(tmp_path, "[Proxy Settings]\nProxyType=3\n")
    monkeypatch.setattr(kde, "_kioslaverc_path", lambda: path)
    sentinel = PAC()
    monkeypatch.setattr(kde, "_wpad_discover", lambda *a, **k: sentinel)

    assert kde.detect() is sentinel


def test_kde_none_type_returns_none(tmp_path, monkeypatch):
    import proxylib.os.posix.kde as kde

    path = _write_kioslaverc(tmp_path, "[Proxy Settings]\nProxyType=0\n")
    monkeypatch.setattr(kde, "_kioslaverc_path", lambda: path)

    assert kde.detect() is None


def test_kde_env_vars_type_returns_none(tmp_path, monkeypatch):
    # ProxyType=4 ("use environment variables") -- let system_proxy()'s own
    # env var fallback handle it, not the KDE backend.
    import proxylib.os.posix.kde as kde

    path = _write_kioslaverc(tmp_path, "[Proxy Settings]\nProxyType=4\n")
    monkeypatch.setattr(kde, "_kioslaverc_path", lambda: path)

    assert kde.detect() is None


# ---- NetworkManager: nmcli ----------------------------------------------------


def test_nm_nmcli_none_when_no_active_connection(monkeypatch):
    import proxylib.os.posix.networkmanager as nm

    monkeypatch.setattr(nm.shutil, "which", lambda name: "/usr/bin/nmcli" if name == "nmcli" else None)
    monkeypatch.setattr(nm, "_nmcli_get", lambda *a: [])
    assert nm.detect() is None


def test_nm_nmcli_auto_pac_url(monkeypatch):
    import proxylib.os.posix.networkmanager as nm

    monkeypatch.setattr(nm.shutil, "which", lambda name: "/usr/bin/nmcli" if name == "nmcli" else None)

    def fake_nmcli_get(*args):
        if args[:1] == ("UUID",):
            return ["uuid-1"]
        return ["auto", "http://internal/proxy.pac", ""]

    monkeypatch.setattr(nm, "_nmcli_get", fake_nmcli_get)
    assert nm.detect() == "http://internal/proxy.pac"


def test_nm_nmcli_auto_pac_script(monkeypatch):
    import proxylib.os.posix.networkmanager as nm

    js = "function FindProxyForURL(url, host) { return 'DIRECT'; }"
    monkeypatch.setattr(nm.shutil, "which", lambda name: "/usr/bin/nmcli" if name == "nmcli" else None)

    def fake_nmcli_get(*args):
        if args[:1] == ("UUID",):
            return ["uuid-1"]
        return ["auto", "", js]

    monkeypatch.setattr(nm, "_nmcli_get", fake_nmcli_get)
    assert nm.detect() == js


def test_nm_nmcli_auto_no_pac_uses_wpad(monkeypatch):
    import proxylib.os.posix.networkmanager as nm

    monkeypatch.setattr(nm.shutil, "which", lambda name: "/usr/bin/nmcli" if name == "nmcli" else None)

    def fake_nmcli_get(*args):
        if args[:1] == ("UUID",):
            return ["uuid-1"]
        return ["auto", "", ""]

    monkeypatch.setattr(nm, "_nmcli_get", fake_nmcli_get)
    sentinel = PAC()
    monkeypatch.setattr(nm, "_wpad_discover", lambda *a, **k: sentinel)

    assert nm.detect() is sentinel


def test_nm_nmcli_none_when_method_not_auto(monkeypatch):
    import proxylib.os.posix.networkmanager as nm

    monkeypatch.setattr(nm.shutil, "which", lambda name: "/usr/bin/nmcli" if name == "nmcli" else None)

    def fake_nmcli_get(*args):
        if args[:1] == ("UUID",):
            return ["uuid-1"]
        return ["none", "", ""]

    monkeypatch.setattr(nm, "_nmcli_get", fake_nmcli_get)
    assert nm.detect() is None


# ---- NetworkManager: dbus-send fallback (used only when nmcli is absent) -----


def _dbus_property_reply(*paths: str) -> str:
    body = "\n".join(f'         object path "{p}"' for p in paths)
    return (
        "method return time=1 sender=:1.1 -> destination=:1.2 serial=3 reply_serial=2\n"
        "   variant       array [\n" + body + "\n      ]\n"
    )


def _dbus_single_path_reply(path: str) -> str:
    return (
        "method return time=1 sender=:1.1 -> destination=:1.2 serial=4 reply_serial=2\n"
        f'   variant       object path "{path}"\n'
    )


def _dbus_get_settings_reply(proxy_fields: dict) -> str:
    entries = "\n".join(
        f'            dict entry(\n'
        f'               string "{key}"\n'
        f'               variant             string "{value}"\n'
        f'            )'
        for key, value in proxy_fields.items()
    )
    return (
        "method return time=1 sender=:1.1 -> destination=:1.2 serial=5 reply_serial=2\n"
        "   array [\n"
        "      dict entry(\n"
        '         string "connection"\n'
        "         array [\n"
        "         ]\n"
        "      )\n"
        "      dict entry(\n"
        '         string "proxy"\n'
        "         array [\n" + entries + "\n         ]\n"
        "      )\n"
        "   ]\n"
    )


def test_nm_dbus_send_not_used_when_nmcli_present(monkeypatch):
    import proxylib.os.posix.networkmanager as nm

    monkeypatch.setattr(nm.shutil, "which", lambda name: f"/usr/bin/{name}")
    called = []
    monkeypatch.setattr(nm, "_proxy_settings_via_dbus_send", lambda: called.append(1) or None)
    monkeypatch.setattr(nm, "_nmcli_get", lambda *a: ["uuid-1"] if a[:1] == ("UUID",) else ["none", "", ""])

    nm.detect()
    assert called == []  # nmcli found an active connection, so dbus-send was never tried


def test_nm_dbus_send_used_when_nmcli_absent(monkeypatch):
    import proxylib.os.posix.networkmanager as nm

    def which(name):
        return None if name == "nmcli" else f"/usr/bin/{name}"

    monkeypatch.setattr(nm.shutil, "which", which)

    active_reply = _dbus_property_reply("/org/freedesktop/NetworkManager/ActiveConnection/1")
    connection_reply = _dbus_single_path_reply("/org/freedesktop/NetworkManager/Settings/1")
    settings_reply = _dbus_get_settings_reply(
        {"method": "auto", "pac-url": "http://internal/proxy.pac"}
    )

    def fake_run(cmd, **kwargs):
        class Result:
            pass

        result = Result()
        joined = " ".join(cmd)
        if "ActiveConnections" in joined:
            result.stdout = active_reply
        elif "Connection.Active" in joined:
            result.stdout = connection_reply
        elif "GetSettings" in joined:
            result.stdout = settings_reply
        else:
            result.stdout = ""
        return result

    monkeypatch.setattr(nm.subprocess, "run", fake_run)

    assert nm.detect() == "http://internal/proxy.pac"


def test_nm_dbus_send_no_proxy_group_returns_none(monkeypatch):
    import proxylib.os.posix.networkmanager as nm

    def which(name):
        return None if name == "nmcli" else f"/usr/bin/{name}"

    monkeypatch.setattr(nm.shutil, "which", which)

    active_reply = _dbus_property_reply("/org/freedesktop/NetworkManager/ActiveConnection/1")
    connection_reply = _dbus_single_path_reply("/org/freedesktop/NetworkManager/Settings/1")
    # No "proxy" group at all in the settings dict.
    settings_reply = (
        "method return time=1 sender=:1.1 -> destination=:1.2 serial=5 reply_serial=2\n"
        "   array [\n"
        "      dict entry(\n"
        '         string "connection"\n'
        "         array [\n"
        "         ]\n"
        "      )\n"
        "   ]\n"
    )

    def fake_run(cmd, **kwargs):
        class Result:
            pass

        result = Result()
        joined = " ".join(cmd)
        if "ActiveConnections" in joined:
            result.stdout = active_reply
        elif "Connection.Active" in joined:
            result.stdout = connection_reply
        elif "GetSettings" in joined:
            result.stdout = settings_reply
        else:
            result.stdout = ""
        return result

    monkeypatch.setattr(nm.subprocess, "run", fake_run)

    assert nm.detect() is None


def test_nm_dbus_send_absent_returns_none(monkeypatch):
    import proxylib.os.posix.networkmanager as nm

    monkeypatch.setattr(nm.shutil, "which", lambda name: None)
    assert nm.detect() is None


# ---- libproxy (ctypes bindings to libproxy's C API) --------------------------
#
# LibProxyMap only ever calls plain Python-style methods on self._lib
# (px_proxy_factory_new/get_proxies/free_proxies/free) -- a fake object with
# matching methods behaves identically to it for our purposes, without
# needing a real libproxy.so/.dylib in the test environment. A NULL-
# terminated char** is faithfully modeled by a plain list of bytes ending in
# None: ctypes auto-converts POINTER(c_char_p) indexing to bytes/None too.


class _FakeLibproxy:
    def __init__(self, proxies=("direct://",), factory_ok=True):
        self._proxies = proxies
        self._factory_ok = factory_ok
        self.freed_proxies_arrays = []
        self.freed_factories = []

    def px_proxy_factory_new(self):
        return 1234 if self._factory_ok else 0

    def px_proxy_factory_get_proxies(self, factory, url):
        return [p.encode("utf-8") for p in self._proxies] + [None]

    def px_proxy_factory_free_proxies(self, proxies_array):
        self.freed_proxies_arrays.append(proxies_array)

    def px_proxy_factory_free(self, factory):
        self.freed_factories.append(factory)


def test_libproxy_detect_none_when_lib_unavailable(monkeypatch):
    import proxylib.os.posix.libproxy as libproxy

    monkeypatch.setattr(libproxy, "_libproxy", None)
    assert libproxy.detect() is None


def test_libproxy_detect_returns_map_when_lib_available(monkeypatch):
    import proxylib.os.posix.libproxy as libproxy

    monkeypatch.setattr(libproxy, "_libproxy", _FakeLibproxy())
    result = libproxy.detect()
    assert isinstance(result, libproxy.LibProxyMap)


def test_libproxymap_parses_direct():
    from proxylib import LibProxyMap

    fake = _FakeLibproxy(proxies=("direct://",))
    assert LibProxyMap(fake)["http://example.com"] == [None]


def test_libproxymap_parses_proxy_url():
    from proxylib import LibProxyMap

    fake = _FakeLibproxy(proxies=("http://proxy.example.com:8080/",))
    result = LibProxyMap(fake)["http://example.com"]
    assert list(result) == [Proxy.from_str("http://proxy.example.com:8080")]


def test_libproxymap_parses_multiple_fallback_proxies():
    from proxylib import LibProxyMap

    fake = _FakeLibproxy(proxies=("http://p1:80/", "http://p2:80/", "direct://"))
    result = list(LibProxyMap(fake)["http://example.com"])
    assert result == [Proxy.from_str("http://p1:80"), Proxy.from_str("http://p2:80"), None]


def test_libproxymap_frees_proxies_array_and_factory():
    from proxylib import LibProxyMap

    fake = _FakeLibproxy(proxies=("direct://",))
    LibProxyMap(fake)["http://example.com"]
    assert len(fake.freed_proxies_arrays) == 1
    assert fake.freed_factories == [1234]


def test_libproxymap_raises_keyerror_when_factory_creation_fails():
    from proxylib import LibProxyMap

    fake = _FakeLibproxy(factory_ok=False)
    with pytest.raises(KeyError):
        LibProxyMap(fake)["http://example.com"]


def test_libproxymap_raises_keyerror_when_lib_unavailable(monkeypatch):
    # LibProxyMap(None) auto-detects, so pin the module-level lib to "not
    # found" -- otherwise this test would flip on a machine with a real
    # libproxy installed.
    import proxylib.os.posix.libproxy as libproxy
    from proxylib import LibProxyMap

    monkeypatch.setattr(libproxy, "_libproxy", None)
    with pytest.raises(KeyError):
        LibProxyMap(None)["http://example.com"]
    assert LibProxyMap(None).get("http://example.com", "fallback") == "fallback"
