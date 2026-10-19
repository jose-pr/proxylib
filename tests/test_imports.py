import os
import pathlib
import subprocess
import sys
import textwrap

# The checkout's src/, so the child imports the code under test whether or not
# proxylib is installed in this interpreter.
_SRC = str(pathlib.Path(__file__).resolve().parents[1] / "src")


def _run(code):
    env = dict(os.environ, PYTHONPATH=_SRC)
    return subprocess.run(
        [sys.executable, "-c", textwrap.dedent(code)],
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
    )


def test_import_proxylib_loads_no_optional_or_network_dependency():
    result = _run(
        """
        import sys
        import proxylib
        loaded = [m for m in ("requests", "urllib3", "ifaddr", "netimps", "httpx") if m in sys.modules]
        print(",".join(loaded))
        """
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == ""


def test_proxymapadapter_without_requests_raises_missing_extra():
    result = _run(
        """
        import sys
        sys.modules["requests"] = None  # makes "import requests" fail
        import proxylib
        try:
            proxylib.ProxyMapAdapter(proxylib.SimpleProxyMap("DIRECT"))
        except proxylib.MissingExtraError as exc:
            print(exc.name, isinstance(exc, ImportError))
        """
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "requests True"


def test_patch_skips_a_missing_client_unless_it_is_named():
    result = _run(
        """
        import sys
        sys.modules["requests"] = None
        import proxylib
        proxylib.patch(proxylib.SimpleProxyMap("DIRECT"))
        proxylib.unpatch()
        try:
            proxylib.patch(proxylib.SimpleProxyMap("DIRECT"), targets=["requests"])
        except proxylib.MissingExtraError:
            print("raised")
        """
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "raised"
