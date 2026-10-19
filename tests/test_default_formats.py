"""The default integration: every client keeps its own proxy choice, and
proxylib reads what the client cannot -- a PAC result or a gateway in a proxy
variable. Each check runs a fresh interpreter with PROXYLIB_* unset."""

import os
import subprocess
import sys
import textwrap

import pytest

ASYNC = """
import asyncio, aiohttp
async def main():
    async with aiohttp.ClientSession(trust_env=True) as session:
        async with session.get(URL) as response:
            return await response.text()
print(asyncio.run(main()))
"""

CLIENTS = {
    "requests": "import requests; print(requests.get(URL, timeout=10).text)",
    "urllib": "import urllib.request; print(urllib.request.urlopen(URL, timeout=10).read().decode())",
    "httpx": "import httpx; print(httpx.get(URL, timeout=10).text)",
    "aiohttp": ASYNC,
    "pip": (
        "from pip._internal.network.session import PipSession\n"
        "with PipSession() as s: print(s.get(URL, timeout=10).text)"
    ),
}
FAILS_OVER = ("requests", "httpx", "aiohttp", "pip")


def _run(client, url, **env):
    pytest.importorskip({"pip": "pip._vendor.requests"}.get(client, client))
    environ = {
        k: v for k, v in os.environ.items() if not k.lower().endswith("_proxy") and not k.startswith("PROXYLIB_")
    }
    environ.update(env)
    code = f"URL = {url!r}\n" + textwrap.dedent(CLIENTS[client])
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120, env=environ)
    return result.stdout.strip() or (result.stderr.strip().splitlines() or ["?"])[-1]


@pytest.mark.parametrize("client", FAILS_OVER)
def test_a_pac_result_in_http_proxy_is_followed_with_failover(client, recording_proxy, dead_port):
    chain = f"PROXY 127.0.0.1:{dead_port}; PROXY 127.0.0.1:{recording_proxy.port}"
    assert _run(client, "http://example.test/x", HTTP_PROXY=chain) == "via proxy"
    assert [target for _, target, _ in recording_proxy.seen] == ["http://example.test/x"]


def test_urllib_follows_a_pac_result_in_http_proxy(recording_proxy):
    chain = f"PROXY 127.0.0.1:{recording_proxy.port}; DIRECT"
    assert _run("urllib", "http://example.test/x", HTTP_PROXY=chain) == "via proxy"


@pytest.mark.parametrize("client", list(CLIENTS))
def test_direct_in_a_pac_result_is_direct(client, http_server):
    http_server.route("/x", b"direct")
    assert _run(client, http_server.url("/x"), HTTP_PROXY="DIRECT; PROXY 127.0.0.1:9") == "direct"


@pytest.mark.parametrize("client", list(CLIENTS))
def test_no_proxy_still_bypasses_a_pac_result(client, http_server, recording_proxy):
    http_server.route("/x", b"direct")
    chain = f"PROXY 127.0.0.1:{recording_proxy.port}"
    assert _run(client, http_server.url("/x"), HTTP_PROXY=chain, NO_PROXY="127.0.0.1") == "direct"
    assert recording_proxy.seen == []


@pytest.mark.parametrize("client", ["requests", "urllib", "httpx", "pip"])
def test_a_gateway_in_http_proxy_is_used(client, gateway):
    assert _run(client, "http://example.test/x", HTTP_PROXY=f"prefix+http://127.0.0.1:{gateway.port}/f/") == "via gateway"
    assert [target for _, target, _ in gateway.seen] == ["/f/http://example.test/x"]


@pytest.mark.parametrize("client", list(CLIENTS))
def test_a_plain_proxy_url_stays_the_clients_own(client, recording_proxy):
    assert _run(client, "http://example.test/x", HTTP_PROXY=f"http://127.0.0.1:{recording_proxy.port}") == "via proxy"
