import subprocess
import sys

import pytest

import proxylib.pac.engines as engines


@pytest.fixture(autouse=True)
def clear_proxylib_js_engine_env(monkeypatch):
    monkeypatch.delenv("PROXYLIB_JS_ENGINE", raising=False)


def _installed(*names):
    return lambda name: name in names


def test_default_priority_is_quickjs_then_dukpy(monkeypatch):
    monkeypatch.setattr(engines, "_installed", _installed("quickjs", "dukpy"))
    assert engines.get_engine().name == "quickjs"
    assert engines.names() == ("quickjs", "dukpy")


def test_falls_back_to_dukpy_when_quickjs_is_missing(monkeypatch):
    monkeypatch.setattr(engines, "_installed", _installed("dukpy"))
    assert engines.get_engine().name == "dukpy"
    assert engines.names() == ("dukpy",)


def test_env_var_sets_the_priority(monkeypatch):
    monkeypatch.setattr(engines, "_installed", _installed("quickjs", "dukpy"))
    monkeypatch.setenv("PROXYLIB_JS_ENGINE", " dukpy , quickjs ")
    assert engines.get_engine().name == "dukpy"


def test_engine_argument_wins_over_the_env_var(monkeypatch):
    monkeypatch.setattr(engines, "_installed", _installed("quickjs", "dukpy"))
    monkeypatch.setenv("PROXYLIB_JS_ENGINE", "quickjs")
    assert engines.get_engine("dukpy").name == "dukpy"


def test_nothing_installed_is_none(monkeypatch):
    monkeypatch.setattr(engines, "_installed", _installed())
    assert engines.get_engine() is None
    assert engines.names() == ()


def test_unknown_names_are_errors(monkeypatch):
    with pytest.raises(ValueError, match="nope"):
        engines.get_engine("nope")
    monkeypatch.setenv("PROXYLIB_JS_ENGINE", "dukpy,nope")
    with pytest.raises(ValueError, match="nope"):
        engines.get_engine()


def test_importing_proxylib_imports_no_engine():
    code = "import sys, proxylib.pac; print([m for m in ('dukpy', 'quickjs', '_quickjs') if m in sys.modules])"
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60,
                            env={**__import__("os").environ, "PYTHONPATH": str(__import__("pathlib").Path(__file__).resolve().parents[1] / "src")})
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "[]"


@pytest.mark.skipif("quickjs" not in engines.names(), reason="quickjs not installed")
def test_quickjs_engine_export_eval_call_and_override():
    from proxylib.pac.engines._quickjs import QuickJSEngine

    engine = QuickJSEngine()
    engine.export_function("compute", lambda n: n + 1)
    assert engine.call("compute", 41) == 42
    engine.eval("function compute(n) { return n * 2; }")
    assert engine.call("compute", 21) == 42


@pytest.mark.skipif("dukpy" not in engines.names(), reason="dukpy not installed")
def test_dukpy_engine_export_eval_call_and_override():
    from proxylib.pac.engines._dukpy import DukpyEngine

    engine = DukpyEngine()
    engine.export_function("compute", lambda n: n + 1)
    assert engine.call("compute", 41) == 42
    engine.eval("function compute(n) { return n * 2; }")
    assert engine.call("compute", 21) == 42
