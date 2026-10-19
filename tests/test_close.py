"""close(): every built-in map has it, and a map that wraps or chains others
closes them, ending any PAC helper process."""

import os
import pathlib
import subprocess
import sys
import textwrap

import pytest

from proxylib import (
    Bypass,
    Cached,
    ChainProxyMap,
    EnvProxyConfig,
    Probed,
    ProxyMap,
    RoundRobin,
    SimpleProxyMap,
    auto_proxy,
    loads_pac,
)
from proxylib.pac import engines

needs_engine = pytest.mark.skipif(not engines.names(), reason="no JS engine installed")
SCRIPT = 'function FindProxyForURL(u, h) { return "PROXY p:1"; }'


def _helper_alive(proxymap):
    proc = proxymap.script._runner._proc
    return proc.poll() is None


class Closable:
    def __init__(self):
        self.closed = 0

    def __getitem__(self, url):
        return None

    def close(self):
        self.closed += 1


def test_every_wrapper_and_chain_closes_what_it_wraps():
    inner = Closable()
    proxymap = Bypass(RoundRobin(Cached(Probed(inner), ttl=60)), "example.com")
    ChainProxyMap(proxymap, {"all": "http://p:1"}, SimpleProxyMap()).close()
    assert inner.closed == 1


@needs_engine
def test_closing_a_pac_map_ends_its_helper():
    proxymap = loads_pac(SCRIPT)
    proxymap["http://x/"]
    assert _helper_alive(proxymap)
    ChainProxyMap(Bypass(proxymap, "")).close()
    assert not _helper_alive(proxymap)


@needs_engine
def test_closing_maps_built_from_a_pac_location(tmp_path):
    pac = tmp_path / "proxy.pac"
    pac.write_text(SCRIPT, encoding="utf-8")
    lazy = ProxyMap(pac.as_uri())
    lazy["http://x/"]
    script = lazy._pac
    lazy.close()
    assert not _helper_alive(script)
    env = EnvProxyConfig({"HTTP_PROXY": pac.as_uri()})
    env["http://x/"]
    script = env._maps["http"]._pac
    env.close()
    assert not _helper_alive(script)


def test_auto_proxy_result_can_be_closed():
    auto_proxy(environ={"HTTP_PROXY": "http://p:1"}).close()


@needs_engine
def test_a_closed_script_leaves_no_open_pipes():
    code = textwrap.dedent(
        f"""
        import gc, warnings
        warnings.simplefilter("error", ResourceWarning)
        import proxylib
        m = proxylib.loads_pac({SCRIPT!r})
        m["http://x/"]
        m.close()
        del m
        # Never closed: garbage collection ends the helper and its pipes.
        unclosed = proxylib.loads_pac({SCRIPT!r})
        unclosed["http://x/"]
        del unclosed
        gc.collect()
        print("clean")
        """
    )
    env = dict(os.environ, PYTHONPATH=str(pathlib.Path(__file__).resolve().parents[1] / "src"), PYTHONWARNINGS="error::ResourceWarning")
    result = subprocess.run([sys.executable, "-X", "dev", "-c", code], capture_output=True, text=True, timeout=120, env=env)
    assert result.stdout.strip() == "clean", result.stderr
    assert "ResourceWarning" not in result.stderr


@needs_engine
@pytest.mark.parametrize(
    "broken",
    ["function FindProxyForURL(u, h) {", "throw 1; function FindProxyForURL(u, h) { return 'DIRECT'; }"],
    ids=["syntax-error", "throws-while-loading"],
)
def test_a_script_that_fails_to_load_leaves_no_helper(broken):
    import threading
    import time

    from proxylib import PACError

    def helpers():
        return [t for t in threading.enumerate() if t.name == "proxylib-pac-child"]

    before = len(helpers())
    with pytest.raises(PACError):
        loads_pac(broken)
    deadline = time.monotonic() + 5
    while len(helpers()) > before and time.monotonic() < deadline:
        time.sleep(0.05)
    assert len(helpers()) == before