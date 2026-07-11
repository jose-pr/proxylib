import pytest

import proxylib.pac.engines as engines


@pytest.fixture(autouse=True)
def clear_proxylib_js_engine_env(monkeypatch):
    monkeypatch.delenv("PROXYLIB_JS_ENGINE", raising=False)


def test_default_priority_is_quickjs_then_dukpy():
    assert engines._priority() == ["quickjs", "dukpy"]


def test_env_var_overrides_priority(monkeypatch):
    monkeypatch.setenv("PROXYLIB_JS_ENGINE", "dukpy,quickjs")
    assert engines._priority() == ["dukpy", "quickjs"]


def test_env_var_is_comma_separated_only(monkeypatch):
    # One delimiter -- not space/colon/semicolon/os.pathsep.
    monkeypatch.setenv("PROXYLIB_JS_ENGINE", " dukpy , quickjs ")
    assert engines._priority() == ["dukpy", "quickjs"]


def test_get_engine_class_prefers_quickjs_over_dukpy_when_both_available(monkeypatch):
    quickjs_stub = type("QuickJSStub", (), {})
    dukpy_stub = type("DukpyStub", (), {})
    monkeypatch.setattr(engines, "_ENGINES", {"quickjs": quickjs_stub, "dukpy": dukpy_stub})
    assert engines.get_engine_class() is quickjs_stub


def test_get_engine_class_honors_env_priority(monkeypatch):
    monkeypatch.setenv("PROXYLIB_JS_ENGINE", "quickjs")
    cls = engines.get_engine_class()
    assert cls is not None
    assert cls.__name__ == "QuickJSEngine"


def test_get_engine_class_skips_unavailable_entries(monkeypatch):
    monkeypatch.setattr(engines, "_ENGINES", {"nonexistent": None, "dukpy": engines.DukpyEngine})
    monkeypatch.setenv("PROXYLIB_JS_ENGINE", "nonexistent,dukpy")
    assert engines.get_engine_class() is engines.DukpyEngine


def test_get_engine_class_returns_none_when_nothing_available(monkeypatch):
    monkeypatch.setattr(engines, "_ENGINES", {"dukpy": None, "quickjs": None})
    assert engines.get_engine_class() is None


pytest.importorskip("quickjs")


def test_quickjs_engine_export_eval_and_call():
    from proxylib.pac.engines.quickjs import QuickJSEngine

    engine = QuickJSEngine()
    engine.export_function("add", lambda a, b: a + b)
    engine.eval("var unused = 1;")
    assert engine.call("add", 2, 3) == 5


def test_quickjs_engine_call_honors_js_override():
    from proxylib.pac.engines.quickjs import QuickJSEngine

    engine = QuickJSEngine()
    engine.export_function("compute", lambda n: n + 1)
    assert engine.call("compute", 41) == 42

    engine.eval("function compute(n) { return n * 2; }")
    assert engine.call("compute", 21) == 42
