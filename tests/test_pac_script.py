"""PacScript on every installed engine: builtins reach the script, a script can
override them, errors and overruns become PACError, threads are safe."""

import functools
import operator
import threading
import time

import pytest

from proxylib import MissingExtraError, PACError, PacScript, Proxy, loads_pac
from proxylib.pac import engines

ENGINES = [
    pytest.param(name, marks=pytest.mark.skipif(name not in engines.names(), reason=f"{name} not installed"))
    for name in ("dukpy", "quickjs")
]


# A function the dukpy helper process can import (it cannot import this module).
_times_two = functools.partial(operator.mul, 2)


@pytest.fixture(params=ENGINES)
def engine(request, monkeypatch):
    monkeypatch.delenv("PROXYLIB_JS_ENGINE", raising=False)
    return request.param


def test_runs_on_the_requested_engine(engine):
    script = PacScript('function FindProxyForURL(u, h) { return "PROXY p:1"; }', engine=engine)
    assert script.engine_name == engine
    assert script.find_proxy_for_url("http://x/", "x") == "PROXY p:1"


def test_builtins_are_callable_from_the_script(engine):
    js = """
    function FindProxyForURL(url, host) {
        if (isPlainHostName(host)) return "DIRECT";
        if (dnsDomainLevels(host) !== 2) return "PROXY wrong-levels:1";
        if (convert_addr("0.0.0.1") !== 1) return "PROXY wrong-convert:1";
        if (!localHostOrDomainIs("www", "www.example.com")) return "PROXY wrong-local:1";
        if (!shExpMatch(host, "*.example.com")) return "PROXY wrong-glob:1";
        getClientVersion();
        return "PROXY ok:1";
    }
    """
    proxymap = loads_pac(js, engine=engine)
    assert proxymap["http://plain/"] == (None,)
    assert proxymap["http://sub.example.com/"] == (Proxy("http", "ok", 1),)


def test_functions_add_to_and_override_builtins(engine):
    js = 'function FindProxyForURL(u, h) { return "PROXY p:" + compute(21) + (isPlainHostName("a.b") ? "" : "0"); }'
    script = PacScript(js, engine=engine, functions={"compute": _times_two})
    assert script.find_proxy_for_url("http://x/", "x") == "PROXY p:420"


def test_the_script_can_redefine_a_builtin(engine):
    js = 'function isPlainHostName(h) { return true; } function FindProxyForURL(u, h) { return isPlainHostName(h) ? "DIRECT" : "PROXY p:1"; }'
    assert PacScript(js, engine=engine).find_proxy_for_url("http://a.b/", "a.b") == "DIRECT"


def test_a_throwing_script_raises_pacerror(engine):
    script = PacScript("function FindProxyForURL(u, h) { throw new Error('boom'); }", engine=engine)
    with pytest.raises(PACError, match="boom"):
        script.find_proxy_for_url("http://x/", "x")
    # An error is not fatal: the next call runs again.
    with pytest.raises(PACError, match="boom"):
        script.find_proxy_for_url("http://x/", "x")


def test_a_script_without_the_function_raises_pacerror(engine):
    with pytest.raises(PACError):
        PacScript("var FindProxyForURL = 1;", engine=engine)


def test_an_endless_script_is_stopped_and_fails_fast_during_the_cooldown(engine):
    script = PacScript("function FindProxyForURL(u, h) { while (true) {} }", engine=engine, timeout=0.5)
    start = time.monotonic()
    with pytest.raises(PACError, match="longer than"):
        script.find_proxy_for_url("http://x/", "x")
    assert time.monotonic() - start < 3.0
    start = time.monotonic()
    with pytest.raises(PACError, match="failed earlier"):
        script.find_proxy_for_url("http://x/", "x")
    assert time.monotonic() - start < 0.5


def test_an_endless_top_level_is_stopped_while_loading(engine):
    with pytest.raises(PACError, match="loading"):
        PacScript("while (true) {} function FindProxyForURL(u, h) { return 'DIRECT'; }", engine=engine, timeout=0.5)


def test_one_script_is_safe_to_share_between_threads(engine):
    js = 'function FindProxyForURL(u, h) { if (isPlainHostName(h)) return "DIRECT"; if (dnsDomainIs(h, ".e.com")) return "PROXY a:1"; return "DIRECT"; }'
    proxymap = loads_pac(js, engine=engine)
    errors = []

    def worker(n):
        try:
            for i in range(200):
                assert proxymap[f"http://h{n}x{i}.e.com/"][0].host == "a"
        except Exception as exc:  # pragma: no cover - only on failure
            errors.append(exc)

    workers = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
    for w in workers:
        w.start()
    for w in workers:
        w.join()
    assert errors == []


# ---- engine selection and a missing engine ------------------------------------


def test_an_unknown_engine_name_is_an_error(monkeypatch):
    with pytest.raises(ValueError, match="nope"):
        PacScript("function FindProxyForURL(u, h) { return 'DIRECT'; }", engine="nope")
    monkeypatch.setenv("PROXYLIB_JS_ENGINE", "nope")
    with pytest.raises(ValueError, match="nope"):
        PacScript("function FindProxyForURL(u, h) { return 'DIRECT'; }")


def test_no_engine_raises_missing_extra_by_default(monkeypatch):
    monkeypatch.setattr(engines, "_installed", lambda name: False)
    with pytest.raises(MissingExtraError) as info:
        loads_pac("function FindProxyForURL(u, h) { return 'PROXY p:1'; }")
    assert info.value.extra == "pac"


def test_no_engine_can_fall_back_to_direct(monkeypatch):
    monkeypatch.setattr(engines, "_installed", lambda name: False)
    with pytest.warns(UserWarning, match="DIRECT"):
        proxymap = loads_pac("function FindProxyForURL(u, h) { return 'PROXY p:1'; }", on_missing_engine="direct")
    assert proxymap["http://x/"] == (None,)


def test_unpicklable_functions_are_refused(engine):
    with pytest.raises(TypeError, match="picklable"):
        PacScript("function FindProxyForURL(u, h) { return 'DIRECT'; }", engine=engine, functions={"f": lambda: 1})


def test_a_stalled_script_is_restarted_after_the_cooldown(engine, monkeypatch, tmp_path):
    import proxylib.pac.script as script_module

    import os.path

    # A flag file decides whether the script stalls, so the restarted helper
    # can behave differently from the first one.
    flag = tmp_path / "stall"
    flag.write_text("")
    js = (
        "function FindProxyForURL(u, h) {"
        "  if (stall(%r)) { while (true) {} }"
        '  return "PROXY p:1"; }' % str(flag)
    )
    script = PacScript(js, engine=engine, timeout=0.5, functions={"stall": os.path.exists})
    with pytest.raises(PACError, match="longer than"):
        script.find_proxy_for_url("http://x/", "x")
    flag.unlink()
    monkeypatch.setattr(script_module.time, "monotonic", lambda: float("inf"))
    assert script.find_proxy_for_url("http://x/", "x") == "PROXY p:1"


def test_dns_builtins_are_bounded(monkeypatch):
    from proxylib.pac import _functions

    seen = []
    monkeypatch.setattr(_functions._net, "resolve_ip", lambda host, **kw: seen.append(kw.get("timeout")))
    monkeypatch.setattr(_functions._net, "resolve_all", lambda host, **kw: seen.append(kw.get("timeout")) or [])
    _functions.myIpAddress()
    _functions.isResolvable("x.test")
    _functions.dnsResolveEx("x.test")
    _functions.dnsResolve("x.test", cache_ttl=0)
    assert seen == [_functions._DNS_TIMEOUT] * 4
