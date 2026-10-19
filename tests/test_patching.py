"""patch() handles, the active map, register_patcher, the built-in requests and
urllib targets, and PROXYLIB_IMPORTPATCH in fresh interpreters."""

import importlib.metadata
import os
import pathlib
import subprocess
import sys
import textwrap
import urllib.request

import pytest

from proxylib import MissingExtraError, Patch, SimpleProxyMap, patch, register_patcher, unpatch
from proxylib import patching

_SRC = str(pathlib.Path(__file__).resolve().parents[1] / "src")
A = SimpleProxyMap("PROXY a:1")
B = SimpleProxyMap("PROXY b:1")


@pytest.fixture(autouse=True)
def clean_patching():
    registry = dict(patching._registry)
    hooked = set(patching._hooked)
    unpatch()
    yield
    unpatch()
    for name in set(patching._registry) - set(registry):
        if name in patching._installed:
            patching._registry[name].uninstall()
            patching._installed.discard(name)
    patching._registry.clear()
    patching._registry.update(registry)
    patching._hooked.clear()
    patching._hooked.update(hooked)


def _host(target):
    return patching._ActiveMap(target)["http://x/"][0].host


def _run(code, **env):
    environ = {k: v for k, v in os.environ.items() if not k.startswith("PROXYLIB_")}
    environ.update(PYTHONPATH=_SRC, **env)
    return subprocess.run(
        [sys.executable, "-c", textwrap.dedent(code)], capture_output=True, text=True, timeout=60, env=environ
    )


# ---- the patch stack -------------------------------------------------------------


def test_with_no_patch_the_default_map_has_no_opinion():
    with pytest.raises(KeyError):
        patching._ActiveMap("requests")["http://x/"]


def test_patches_nest_and_restore_the_previous_map():
    with patch(A) as outer:
        assert isinstance(outer, Patch) and outer.active
        with patch(B):
            assert _host("requests") == "b"
        assert _host("requests") == "a"
    assert not outer.active
    with pytest.raises(KeyError):
        patching._ActiveMap("requests")["http://x/"]


def test_a_patch_can_cover_some_targets_only():
    with patch(A), patch(B, targets=["urllib"]):
        assert _host("urllib") == "b"
        assert _host("requests") == "a"


def test_patches_are_undone_newest_first():
    first = patch(A)
    second = patch(B)
    with pytest.raises(RuntimeError):
        first.undo()
    second.undo()
    second.undo()  # already ended: nothing happens
    first.undo()
    assert patching._frames == []


def test_unpatch_ends_every_patch():
    first, second = patch(A), patch(B)
    unpatch()
    assert not first.active and not second.active


def test_an_unknown_target_is_an_error():
    with pytest.raises(ValueError, match="nope"):
        patch(A, targets=["nope"])


# ---- register_patcher ------------------------------------------------------------


def _client(tmp_path, monkeypatch, name):
    (tmp_path / f"{name}.py").write_text("VALUE = 1\n", encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.delitem(sys.modules, name, raising=False)
    calls = []
    register_patcher(name, calls.append, uninstall=lambda: calls.append("uninstalled"), module=name, unnamed=True)
    return calls


def test_a_registered_client_is_installed_once_when_imported(tmp_path, monkeypatch):
    calls = _client(tmp_path, monkeypatch, "ip_client_a")
    assert calls == []
    importlib_module = __import__("ip_client_a")
    assert importlib_module.VALUE == 1
    assert len(calls) == 1
    installed_map = calls[0]
    with patch(A, targets=["ip_client_a"]):
        assert installed_map["http://x/"][0].host == "a"
    patch(B)
    assert installed_map["http://x/"][0].host == "b"
    assert len(calls) == 1


def test_registering_a_name_twice_needs_replace(tmp_path, monkeypatch):
    _client(tmp_path, monkeypatch, "ip_client_b")
    with pytest.raises(ValueError, match="already registered"):
        register_patcher("ip_client_b", print, uninstall=print, module="ip_client_b")
    register_patcher("ip_client_b", print, uninstall=print, module="ip_client_b", replace=True)
    with pytest.raises(ValueError):
        register_patcher("requests", print, uninstall=print, module="requests")
    assert {"requests", "urllib", "ip_client_b"} <= set(patching.targets())


def test_naming_a_client_that_is_not_installed_raises(monkeypatch):
    register_patcher("ip_missing", print, uninstall=print, module="ip_missing_client.sub")
    with pytest.raises(MissingExtraError) as info:
        patch(A, targets=["ip_missing"])
    assert info.value.name == "ip_missing_client"
    patch(A)  # unnamed: skipped


# ---- the built-in targets in this process -------------------------------------------

requests = pytest.importorskip("requests")


def test_new_requests_sessions_use_the_active_map():
    from proxylib.integrations.requests import ProxyMapAdapter

    session = requests.Session()
    try:
        adapter = session.get_adapter("https://example.com/")
        assert isinstance(adapter, ProxyMapAdapter)
        with pytest.raises(KeyError):
            adapter.proxymap["https://example.com/"]
        with patch(A):
            assert adapter.proxymap["https://example.com/"][0].host == "a"
    finally:
        session.close()


def test_a_requests_session_without_a_patch_keeps_its_own_proxies(monkeypatch):
    session = requests.Session()
    try:
        adapter = session.get_adapter("http://example.com/")
        sent = {}

        def send(self, request, **kwargs):
            sent.update(kwargs["proxies"])

        monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", send)
        adapter.send(requests.Request("GET", "http://example.com/").prepare(), proxies={"http": "http://env:1"})
        assert sent == {"http": "http://env:1"}
    finally:
        session.close()


def test_urllib_gets_the_handler_when_no_opener_was_installed():
    from proxylib.integrations.urllib import ProxyMapHandler

    assert any(isinstance(h, ProxyMapHandler) for h in urllib.request._opener.handlers)


# ---- fresh interpreters -----------------------------------------------------------

ADAPTER = "type(requests.Session().get_adapter('http://x/')).__name__"


@pytest.mark.parametrize("importpatch_disable", ["1", "0"], ids=["entry-points-off", "entry-points-on"])
def test_clients_are_patched_whether_imported_before_or_after_proxylib(importpatch_disable):
    code = "import {}, {}; import urllib.request as u; print({}, u._opener is not None)"
    for first, second in (("proxylib", "requests"), ("requests", "proxylib")):
        # urllib3 2 warns on import under a Python built with LibreSSL (Apple's python3).
        result = _run(
            code.format(first, second, ADAPTER),
            IMPORTPATCH_DISABLE=importpatch_disable,
            PYTHONWARNINGS="ignore:::urllib3",
        )
        assert (result.returncode, result.stdout.split(), result.stderr) == (0, ["ProxyMapAdapter", "True"], "")


def test_importpatch_off_installs_nothing_until_patch_is_called():
    result = _run(
        f"""
        import urllib.request, proxylib, requests
        print({ADAPTER}, urllib.request._opener)
        proxylib.patch(proxylib.SimpleProxyMap("DIRECT"))
        print({ADAPTER})
        """,
        PROXYLIB_IMPORTPATCH="0",
    )
    assert result.stdout.split() == ["HTTPAdapter", "None", "ProxyMapAdapter"], result.stderr


@pytest.mark.parametrize(
    "value, auto",
    [
        ("1", {"requests", "urllib", "httpx", "aiohttp", "pip"}),
        ("TRUE", {"requests", "urllib", "httpx", "aiohttp", "pip"}),
        ("", set()),
        ("requests:urllib.request:httpx", {"requests", "urllib", "httpx"}),
        (" aiohttp :: ", {"aiohttp"}),
        ("pip._vendor.requests:pip", {"pip"}),
    ],
)
def test_importpatch_names_the_clients_that_use_auto_proxy(value, auto):
    code = "import proxylib.patching as p; print(' '.join(t for t in p.targets() if repr(p.active(t)) == '<auto_proxy()>'))"
    result = _run(code, PROXYLIB_IMPORTPATCH=value)
    assert set(result.stdout.split()) == auto, result.stderr


def test_an_unknown_name_warns():
    result = _run("import proxylib.patching as p; print(p.active('requests'))", PROXYLIB_IMPORTPATCH="requests:pycurl")
    assert result.stdout.strip() == "<auto_proxy()>"
    assert "PROXYLIB_IMPORTPATCH names 'pycurl'" in result.stderr


HTTPX = "type(httpx.Client()._transport).__name__"


def test_httpx_is_patched_only_when_named():
    for value, expected in (("", "HTTPTransport"), ("httpx", "ProxyTransport"), ("1", "ProxyTransport")):
        result = _run(f"import proxylib, httpx; print({HTTPX})", PROXYLIB_IMPORTPATCH=value)
        assert result.stdout.strip() == expected, (value, result.stderr)
    result = _run(f"import proxylib, httpx; print(type(httpx.Client(transport=httpx.HTTPTransport())._transport).__name__)",
                  PROXYLIB_IMPORTPATCH="httpx")
    assert result.stdout.strip() == "HTTPTransport", result.stderr


def test_aiohttp_is_patched_only_when_named():
    code = "import proxylib, aiohttp; print(getattr(aiohttp.ClientSession._request, '__wrapped__', None) is not None)"
    assert _run(code).stdout.strip() == "False"
    assert _run(code, PROXYLIB_IMPORTPATCH="aiohttp").stdout.strip() == "True"


def test_a_program_opener_is_left_alone():
    result = _run(
        """
        import urllib.request
        mine = urllib.request.build_opener()
        urllib.request.install_opener(mine)
        import proxylib
        print(urllib.request._opener is mine)
        """
    )
    assert result.stdout.strip() == "True", result.stderr


def _entry_points_installed():
    try:
        importlib.metadata.version("importpatch")
    except importlib.metadata.PackageNotFoundError:
        return False
    eps = importlib.metadata.entry_points()
    group = eps.select(group="importpatch") if hasattr(eps, "select") else eps.get("importpatch", ())
    return any(ep.value.startswith("proxylib.") for ep in group)


@pytest.mark.skipif(not _entry_points_installed(), reason="needs proxylib installed (its entry points)")
def test_entry_points_patch_programs_that_never_import_proxylib():
    result = _run(f"import requests, sys; print({ADAPTER}, 'proxylib' in sys.modules)")
    assert result.stdout.split() == ["ProxyMapAdapter", "True"], result.stderr
