"""Every ```python block of the README runs, in a fresh interpreter, with
https://example.com pointed at a local HTTP server (and no proxy variables)."""

import os
import pathlib
import re
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
BLOCKS = re.findall(r"```python\n(.*?)```", (ROOT / "README.md").read_text(encoding="utf-8"), re.DOTALL)
PAC = b'function FindProxyForURL(url, host) { return "DIRECT"; }'


def test_the_readme_has_examples():
    assert len(BLOCKS) >= 8


@pytest.mark.parametrize("index", range(len(BLOCKS)), ids=[f"block{i}" for i in range(len(BLOCKS))])
def test_a_readme_example_runs(index, http_server, tmp_path):
    for module in ("requests", "httpx", "aiohttp"):
        if f"import {module}" in BLOCKS[index]:
            pytest.importorskip(module)
    if "pac" in BLOCKS[index]:
        from proxylib.pac import engines

        if not engines.names():
            pytest.skip("no JS engine installed")
    http_server.route("/", b"ok")
    http_server.route("/proxy.pac", PAC)
    code = BLOCKS[index].replace("https://example.com", http_server.url("").rstrip("/"))
    env = {k: v for k, v in os.environ.items() if not k.lower().endswith("_proxy") and not k.startswith("PROXYLIB_")}
    env["PYTHONPATH"] = str(ROOT / "src")
    result = subprocess.run(
        [sys.executable, "-W", "error::UserWarning", "-c", code],
        capture_output=True,
        text=True,
        timeout=120,
        cwd=str(tmp_path),
        env=env,
    )
    assert result.returncode == 0, f"block {index}:\n{code}\n{result.stderr}"
