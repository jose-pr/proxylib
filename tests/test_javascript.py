import pytest

pytest.importorskip("dukpy")

from proxylib.pac import JSProxyAutoConfig
from proxylib.pac.javascript import JSContext


class Calculator(JSContext):
    @staticmethod
    def compute(n):
        return n + 1  # Python fallback, used unless JS overrides `compute`.


def test_jscontext_exported_function_falls_back_to_python():
    # The loaded script doesn't define `compute`, so the JS stub calls back into Python.
    instance = Calculator("var unused = 1;")
    assert instance.compute(41) == 42


def test_jscontext_js_can_override_exported_function():
    # The loaded script redefines `compute` in JS, overriding the Python fallback.
    instance = Calculator("function compute(n) { return n * 2; }")
    assert instance.compute(21) == 42


def test_jscontext_exported_function_is_prebound_not_reallocated():
    # Repeated attribute access must return the same callable, not a fresh
    # closure each time -- the whole point of pre-binding in __init__.
    instance = Calculator("var unused = 1;")
    assert instance.compute is instance.compute


def test_jscontext_overrides_replaces_python_fallback():
    # overrides= swaps compute's Python-side implementation, without the
    # loaded script needing to redefine it in JS.
    instance = Calculator("var unused = 1;", overrides={"compute": lambda n: n * 10})
    assert instance.compute(4) == 40


def test_jscontext_overrides_does_not_leak_to_other_instances():
    overridden = Calculator("var unused = 1;", overrides={"compute": lambda n: n * 10})
    plain = Calculator("var unused = 1;")

    assert overridden.compute(4) == 40
    assert plain.compute(4) == 5  # unaffected: still the Python fallback (+1)


def test_jscontext_js_still_overrides_a_python_override():
    # JS-in-the-loaded-script still wins over an overrides= callable too --
    # overrides only replaces the *Python fallback*, same override-wins
    # semantics as the class's own methods.
    instance = Calculator(
        "function compute(n) { return n * 100; }",
        overrides={"compute": lambda n: n * 10},
    )
    assert instance.compute(4) == 400


def test_jscontext_overrides_can_add_a_new_exported_name():
    instance = Calculator("var unused = 1;", overrides={"customHelper": lambda: 99})
    assert instance.customHelper() == 99


# ---- Same JSContext behavior, forced onto the quickjs engine -----------------
# JSContext is written against the pluggable JSEngine interface, not dukpy
# specifically -- these confirm that's actually true rather than assumed.

pytest.importorskip("quickjs")


def test_jscontext_falls_back_to_python_on_quickjs(monkeypatch):
    monkeypatch.setenv("PROXYLIB_JS_ENGINE", "quickjs")
    instance = Calculator("var unused = 1;")
    assert instance.compute(41) == 42


def test_jscontext_js_can_override_exported_function_on_quickjs(monkeypatch):
    monkeypatch.setenv("PROXYLIB_JS_ENGINE", "quickjs")
    instance = Calculator("function compute(n) { return n * 2; }")
    assert instance.compute(21) == 42


def test_jsproxyautoconfig_runs_utility_functions_from_js():
    js = """
    function FindProxyForURL(url, host) {
        if (isPlainHostName(host)) {
            return "DIRECT";
        }
        return "PROXY wcg1.example.com:8080";
    }
    """
    pac = JSProxyAutoConfig(js)
    assert pac["http://plain/"] == [None]
    proxies = pac["http://sub.example.com/"]
    assert proxies[0].host == "wcg1.example.com"


def test_jsproxyautoconfig_can_call_ms_extension_functions():
    js = """
    function FindProxyForURL(url, host) {
        var v = getClientVersion();
        return "DIRECT";
    }
    """
    pac = JSProxyAutoConfig(js)
    assert pac["http://example.com/"] == [None]


def test_jsproxyautoconfig_dns_domain_levels_and_convert_addr_and_local_host():
    # The remaining PAC utility functions the example .pac files don't
    # happen to exercise -- confirm they're at least callable from real JS.
    js = """
    function FindProxyForURL(url, host) {
        if (dnsDomainLevels(host) !== 2) {
            return "PROXY wrong-levels.example.com:8080";
        }
        if (convert_addr("0.0.0.1") !== 1) {
            return "PROXY wrong-convert-addr.example.com:8080";
        }
        if (!localHostOrDomainIs("www", "www.example.com")) {
            return "PROXY wrong-local-host.example.com:8080";
        }
        return "DIRECT";
    }
    """
    pac = JSProxyAutoConfig(js)
    assert pac["http://sub.example.com/"] == [None]
