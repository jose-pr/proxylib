"""POSIX desktop settings (GNOME, MATE, KDE, NetworkManager) as ProxyConfig,
the shared program runner, and LibProxyMap."""

import sys

import pytest

from proxylib import Proxy, ProxyConfig
from proxylib.system import _posix, _run
from proxylib.system._posix import _gsettings, _kde, _libproxy, _networkmanager as nm
from proxylib.system._posix._libproxy import LibProxyMap


@pytest.fixture(autouse=True)
def clear_posix_caches():
    _run.clear_which_cache()
    _gsettings.clear_gsettings_cache()
    yield
    _run.clear_which_cache()
    _gsettings.clear_gsettings_cache()


def _fake_gsettings(monkeypatch, values):
    monkeypatch.setattr(_gsettings, "_gsettings_get", lambda schema, key: values.get((schema, key)))


def _gnome(monkeypatch, values):
    _fake_gsettings(monkeypatch, values)
    return _gsettings.read_config("org.gnome.system.proxy", "gnome")


def _hosts(answer):
    return [p.host if p else None for p in answer]


# ---- the program runner ----------------------------------------------------------


def test_run_returns_stdout_and_none_on_any_failure(monkeypatch):
    monkeypatch.setattr(_run, "which", lambda name: sys.executable)
    assert _run.run(["python", "-c", "print('ok')"]).strip() == "ok"
    assert _run.run(["python", "-c", "import sys; sys.exit(3)"]) is None
    assert _run.run(["python", "-c", "import time; time.sleep(5)"], timeout=0.2) is None
    monkeypatch.setattr(_run, "which", lambda name: None)
    assert _run.run(["missing-program"]) is None


def test_run_uses_the_c_locale_and_no_stdin(monkeypatch):
    monkeypatch.setattr(_run, "which", lambda name: sys.executable)
    code = "import os, sys; print(os.environ['LC_ALL'], sys.stdin.read() == '')"
    assert _run.run(["python", "-c", code]).split() == ["C", "True"]


def test_run_decodes_bad_utf8_with_replacement(monkeypatch):
    monkeypatch.setattr(_run, "which", lambda name: sys.executable)
    assert "�" in _run.run(["python", "-c", "import sys; sys.stdout.buffer.write(b'caf\\xe9')"])


def test_which_cache_dedups_repeated_lookups(monkeypatch):
    calls = []
    monkeypatch.setattr(_run.shutil, "which", lambda name: calls.append(name) or f"/usr/bin/{name}")
    assert _run.which("gsettings") == "/usr/bin/gsettings"
    assert _run.which("gsettings") == "/usr/bin/gsettings"
    assert calls == ["gsettings"]


# ---- which desktop answers ---------------------------------------------------------


def _stub_readers(monkeypatch, gnome=None, mate=None, kde=None, networkmanager=None):
    by_schema = {"org.gnome.system.proxy": gnome, "org.mate.system.proxy": mate}
    monkeypatch.setattr(_gsettings, "read_config", lambda schema, source: by_schema[schema])
    monkeypatch.setattr(_kde, "read_config", lambda: kde)
    monkeypatch.setattr(nm, "read_config", lambda: networkmanager)


def test_nothing_readable_is_none(monkeypatch):
    _stub_readers(monkeypatch)
    assert _posix.read_config() is None


def test_the_first_configured_source_wins(monkeypatch):
    gnome_direct = ProxyConfig(source="gnome", state="direct")
    kde = ProxyConfig(source="kde", state="configured", proxies={"http": "k:1"})
    mate = ProxyConfig(source="mate", state="configured", proxies={"http": "m:1"})
    _stub_readers(monkeypatch, gnome=gnome_direct, mate=mate, kde=kde)
    assert _posix.read_config() is mate


def test_with_nothing_configured_the_first_with_settings_answers(monkeypatch):
    gnome_direct = ProxyConfig(source="gnome", state="direct")
    _stub_readers(monkeypatch, gnome=gnome_direct, kde=ProxyConfig(source="kde", state="direct"))
    assert _posix.read_config() is gnome_direct


# ---- gsettings ---------------------------------------------------------------------


def test_gsettings_batches_into_one_call_when_children_included(monkeypatch):
    calls = []
    output = (
        "org.gnome.system.proxy mode 'manual'\n"
        "org.gnome.system.proxy ignore-hosts ['localhost', '*.internal']\n"
        "org.gnome.system.proxy.http host 'proxy.example.com'\n"
        "org.gnome.system.proxy.http port 8080\n"
    )
    monkeypatch.setattr(_gsettings._run, "run", lambda argv, **k: calls.append(argv) or output)
    assert _gsettings._gsettings_get("org.gnome.system.proxy", "mode") == "manual"
    assert _gsettings._gsettings_get("org.gnome.system.proxy.http", "host") == "proxy.example.com"
    assert _gsettings._gsettings_get("org.gnome.system.proxy.http", "port") == "8080"
    assert calls == [["gsettings", "list-recursively", "org.gnome.system.proxy"]]


def test_gsettings_lists_a_child_schema_left_out_of_the_base_listing(monkeypatch):
    calls = []

    def run(argv, **k):
        calls.append(argv)
        if argv[-1] == "org.gnome.system.proxy":
            return "org.gnome.system.proxy mode 'manual'\n"
        return "org.gnome.system.proxy.http host 'proxy.example.com'\n"

    monkeypatch.setattr(_gsettings._run, "run", run)
    assert _gsettings._gsettings_get("org.gnome.system.proxy", "mode") == "manual"
    assert _gsettings._gsettings_get("org.gnome.system.proxy.http", "host") == "proxy.example.com"
    assert _gsettings._gsettings_get("org.gnome.system.proxy.http", "port") is None
    assert calls[1] == ["gsettings", "list-recursively", "org.gnome.system.proxy.http"]


def test_gsettings_missing_is_none(monkeypatch):
    monkeypatch.setattr(_gsettings._run, "run", lambda argv, **k: None)
    assert _gsettings.read_config("org.gnome.system.proxy", "gnome") is None


def test_gsettings_cache_expires(monkeypatch):
    calls = []
    now = [1000.0]
    monkeypatch.setattr(_gsettings.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(_gsettings._run, "run", lambda argv, **k: calls.append(1) or "org.gnome.system.proxy mode 'none'\n")
    _gsettings._gsettings_list_recursively("org.gnome.system.proxy")
    _gsettings._gsettings_list_recursively("org.gnome.system.proxy")
    now[0] += _gsettings._CACHE_TTL + 1
    _gsettings._gsettings_list_recursively("org.gnome.system.proxy")
    assert len(calls) == 2


def test_gnome_mode_none_is_direct(monkeypatch):
    config = _gnome(monkeypatch, {("org.gnome.system.proxy", "mode"): "none"})
    assert (config.source, config.state) == ("gnome", "direct")


def test_gnome_auto_with_a_url_is_a_pac_and_blank_is_auto_detect(monkeypatch):
    config = _gnome(
        monkeypatch,
        {("org.gnome.system.proxy", "mode"): "auto", ("org.gnome.system.proxy", "autoconfig-url"): "http://internal/proxy.pac"},
    )
    assert (config.pac_url, config.auto_detect) == ("http://internal/proxy.pac", False)
    config = _gnome(monkeypatch, {("org.gnome.system.proxy", "mode"): "auto", ("org.gnome.system.proxy", "autoconfig-url"): ""})
    assert (config.pac_url, config.auto_detect, config.state) == (None, True, "configured")


def test_gnome_manual(monkeypatch):
    config = _gnome(
        monkeypatch,
        {
            ("org.gnome.system.proxy", "mode"): "manual",
            ("org.gnome.system.proxy.http", "host"): "proxy.example.com",
            ("org.gnome.system.proxy.http", "port"): "8080",
            ("org.gnome.system.proxy", "ignore-hosts"): "['localhost', '*.internal']",
        },
    )
    proxymap = config.to_proxymap()
    assert proxymap["http://example.com"] == (Proxy("http", "proxy.example.com", 8080),)
    assert proxymap["http://app.internal/"] == (None,)
    assert proxymap["https://example.com"] == (None,)


@pytest.mark.parametrize("port", [None, "0", "nope"])
def test_gnome_a_missing_or_zero_port_is_the_default(monkeypatch, port):
    values = {("org.gnome.system.proxy", "mode"): "manual", ("org.gnome.system.proxy.http", "host"): "gnome-proxy"}
    if port is not None:
        values[("org.gnome.system.proxy.http", "port")] = port
    assert _gnome(monkeypatch, values).proxies["http"] == Proxy("http", "gnome-proxy")


def test_gnome_socks_only_is_socks5_for_every_scheme(monkeypatch):
    config = _gnome(
        monkeypatch,
        {
            ("org.gnome.system.proxy", "mode"): "manual",
            ("org.gnome.system.proxy.socks", "host"): "s",
            ("org.gnome.system.proxy.socks", "port"): "1080",
        },
    )
    assert config.to_proxymap()["https://x/"] == (Proxy("socks5", "s", 1080),)


def test_gnome_manual_with_no_host_is_direct(monkeypatch):
    assert _gnome(monkeypatch, {("org.gnome.system.proxy", "mode"): "manual"}).state == "direct"


def test_gnome_ignore_hosts_use_glib_syntax(monkeypatch):
    config = _gnome(
        monkeypatch,
        {
            ("org.gnome.system.proxy", "mode"): "manual",
            ("org.gnome.system.proxy.http", "host"): "gnome-proxy",
            ("org.gnome.system.proxy.http", "port"): "3128",
            ("org.gnome.system.proxy", "ignore-hosts"): "['*.local', '192.168.0.0/16']",
        },
    )
    proxymap = config.to_proxymap()
    assert proxymap["http://printer.local/"] == (None,)
    assert proxymap["http://192.168.1.9/"] == (None,)
    assert _hosts(proxymap["http://example.com/"]) == ["gnome-proxy"]


def test_mate_uses_its_own_schema(monkeypatch):
    _fake_gsettings(
        monkeypatch,
        {
            ("org.mate.system.proxy", "mode"): "manual",
            ("org.mate.system.proxy.http", "host"): "mate-proxy.example.com",
            ("org.mate.system.proxy.http", "port"): "3128",
        },
    )
    config = _gsettings.read_config("org.mate.system.proxy", "mate")
    assert config.source == "mate"
    assert config.proxies["http"] == Proxy("http", "mate-proxy.example.com", 3128)


def test_an_empty_typed_array_is_no_entries():
    assert _gsettings._string_list("@as []") == []
    assert _gsettings._string_list("['a', 'b']") == ["a", "b"]


# ---- KDE ---------------------------------------------------------------------------


@pytest.fixture
def kioslaverc(tmp_path, monkeypatch):
    path = tmp_path / "kioslaverc"
    monkeypatch.setattr(_kde, "_kioslaverc_path", lambda: path)

    def write(text):
        path.write_text("[Proxy Settings]\n" + text, encoding="utf-8")

    return write


def test_kde_no_file_is_none(kioslaverc):
    assert _kde.read_config() is None


def test_kde_manual(kioslaverc):
    kioslaverc(
        "ProxyType=1\n"
        "httpProxy=http://proxy.example.com 8080\n"
        "socksProxy=socks://s 1080\n"
        "NoProxyFor=localhost,*.internal\n"
    )
    config = _kde.read_config()
    proxymap = config.to_proxymap()
    assert proxymap["http://example.com"] == (Proxy("http", "proxy.example.com", 8080),)
    assert proxymap["https://example.com"] == (Proxy("socks5", "s", 1080),)
    assert proxymap["http://app.internal"] == (None,)


@pytest.mark.parametrize(
    "text, expected",
    [
        ("ProxyType=0\n", ("direct", False, None)),
        ("ProxyType=2\nProxy Config Script=http://internal/proxy%20script.pac\n", ("configured", False, "http://internal/proxy%20script.pac")),
        ("ProxyType=3\n", ("configured", True, None)),
    ],
)
def test_kde_proxy_types(kioslaverc, text, expected):
    kioslaverc(text)
    config = _kde.read_config()
    assert (config.state, config.auto_detect, config.pac_url) == expected


def test_kde_environment_type_defers_to_the_variables(kioslaverc):
    kioslaverc("ProxyType=4\n")
    assert _kde.read_config() is None


def test_kde_reversed_exception_lists_the_proxied_hosts(kioslaverc):
    kioslaverc("ProxyType=1\nhttpProxy=http://proxy.example.com 8080\nNoProxyFor=*.internal\nReversedException=true\n")
    proxymap = _kde.read_config().to_proxymap()
    assert _hosts(proxymap["http://app.internal/"]) == ["proxy.example.com"]
    assert proxymap["http://example.com/"] == (None,)


def test_kde_non_utf8_kioslaverc_is_not_configured(tmp_path, monkeypatch):
    path = tmp_path / "kioslaverc"
    path.write_bytes(b"[Proxy Settings]\nProxyType=1\nhttpProxy=http://caf\xe9 8080\n")
    monkeypatch.setattr(_kde, "_kioslaverc_path", lambda: path)
    assert _kde.read_config() is None


# ---- NetworkManager ----------------------------------------------------------------


def _nmcli(monkeypatch, replies):
    monkeypatch.setattr(nm._run, "which", lambda name: "/usr/bin/" + name if name == "nmcli" else None)
    monkeypatch.setattr(nm, "_nmcli_get", lambda *args: replies.get(args, []))


_ACTIVE = ("UUID", "connection", "show", "--active")
_FIELDS = "proxy.method,proxy.pac-url,proxy.pac-script"


def test_nm_auto_with_a_pac_url_script_or_neither():
    js = "function FindProxyForURL(url, host) { return 'DIRECT'; }"
    assert nm.config_from_settings({"method": "auto", "pac-url": "http://pac/x.pac"}).pac_url == "http://pac/x.pac"
    assert nm.config_from_settings({"method": "auto", "pac-script": js}).pac_script == js
    assert nm.config_from_settings({"method": "auto"}).auto_detect is True
    assert nm.config_from_settings({"method": "auto", "pac-script": "not a script"}).auto_detect is True


def test_nm_method_none_is_not_a_setting():
    assert nm.config_from_settings({"method": "none"}) is None


def test_nm_reads_through_nmcli(monkeypatch):
    _nmcli(monkeypatch, {_ACTIVE: ["uuid-1"], (_FIELDS, "connection", "show", "uuid-1"): ["auto", "http://pac/x.pac", ""]})
    config = nm.read_config()
    assert (config.source, config.pac_url) == ("networkmanager", "http://pac/x.pac")


def test_nm_no_active_connection_is_none(monkeypatch):
    _nmcli(monkeypatch, {})
    monkeypatch.setattr(nm, "_proxy_settings_via_dbus_send", lambda: None)
    assert nm.read_config() is None


def test_nmcli_uses_the_first_active_connection_with_a_proxy(monkeypatch):
    _nmcli(
        monkeypatch,
        {
            _ACTIVE: ["wired", "vpn", ""],
            (_FIELDS, "connection", "show", "wired"): ["none", "", ""],
            (_FIELDS, "connection", "show", "vpn"): ["auto", "http://pac/x.pac", ""],
        },
    )
    assert nm._proxy_settings_via_nmcli()["pac-url"] == "http://pac/x.pac"


def test_nm_dbus_send_not_used_when_nmcli_answers(monkeypatch):
    _nmcli(monkeypatch, {_ACTIVE: ["uuid-1"], (_FIELDS, "connection", "show", "uuid-1"): ["none", "", ""]})
    called = []
    monkeypatch.setattr(nm, "_proxy_settings_via_dbus_send", lambda: called.append(1) or None)
    nm.read_config()
    assert called == []


def _dbus_replies(proxy_fields):
    entries = "\n".join(
        f'            dict entry(\n               string "{k}"\n               variant             string "{v}"\n            )'
        for k, v in proxy_fields.items()
    )
    proxy_group = (
        "      dict entry(\n" '         string "proxy"\n' "         array [\n" + entries + "\n         ]\n" "      )\n"
        if proxy_fields
        else ""
    )
    return {
        "ActiveConnections": '   variant       array [\n         object path "/org/freedesktop/NetworkManager/ActiveConnection/1"\n      ]\n',
        "Connection.Active": '   variant       object path "/org/freedesktop/NetworkManager/Settings/1"\n',
        "GetSettings": "   array [\n      dict entry(\n" '         string "connection"\n' "         array [\n         ]\n      )\n"
        + proxy_group
        + "   ]\n",
    }


def _dbus(monkeypatch, proxy_fields):
    replies = _dbus_replies(proxy_fields)
    monkeypatch.setattr(nm._run, "which", lambda name: None if name == "nmcli" else "/usr/bin/" + name)

    def run(argv, **k):
        joined = " ".join(argv)
        return next((reply for marker, reply in replies.items() if marker in joined), "")

    monkeypatch.setattr(nm._run, "run", run)


def test_nm_dbus_send_used_when_nmcli_is_absent(monkeypatch):
    _dbus(monkeypatch, {"method": "auto", "pac-url": "http://internal/proxy.pac"})
    assert nm.read_config().pac_url == "http://internal/proxy.pac"


def test_nm_dbus_send_without_a_proxy_group_is_none(monkeypatch):
    _dbus(monkeypatch, {})
    assert nm.read_config() is None


def test_nm_neither_tool_is_none(monkeypatch):
    monkeypatch.setattr(nm._run, "which", lambda name: None)
    assert nm.read_config() is None


# ---- LibProxyMap -------------------------------------------------------------------
# A fake with libproxy's four functions; a NULL-terminated char** is modelled
# as a list of bytes ending in None, which is what ctypes indexing yields.


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


def test_libproxymap_answers_in_order():
    assert LibProxyMap(_FakeLibproxy())["http://example.com"] == (None,)
    fake = _FakeLibproxy(proxies=("http://p1:80/", "http://p2:80/", "direct://"))
    assert _hosts(LibProxyMap(fake)["http://example.com"]) == ["p1", "p2", None]


def test_libproxymap_reuses_one_factory_and_frees_everything():
    fake = _FakeLibproxy()
    created = []
    original = fake.px_proxy_factory_new
    fake.px_proxy_factory_new = lambda: created.append(1) or original()
    proxymap = LibProxyMap(fake)
    for _ in range(3):
        proxymap["http://example.com"]
    assert created == [1]
    assert len(fake.freed_proxies_arrays) == 3
    proxymap.close()
    assert fake.freed_factories == [1234]


def test_libproxymap_failures_are_no_opinion(monkeypatch):
    fake = _FakeLibproxy()
    fake.px_proxy_factory_get_proxies = lambda factory, url: None
    with pytest.raises(KeyError):
        LibProxyMap(fake)["http://example.com"]
    with pytest.raises(KeyError):
        LibProxyMap(_FakeLibproxy(factory_ok=False))["http://example.com"]
    monkeypatch.setattr(_libproxy, "_libproxy", None)
    with pytest.raises(KeyError):
        LibProxyMap()["http://example.com"]


@pytest.mark.skipif(sys.platform == "win32", reason="real gsettings and nmcli are POSIX programs")
def test_real_desktop_settings_read_without_error():
    # Whatever this machine has (often nothing): reading must not raise.
    config = _posix.read_config()
    assert config is None or isinstance(config, ProxyConfig)

