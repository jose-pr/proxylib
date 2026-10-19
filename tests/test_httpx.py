"""ProxyTransport / AsyncProxyTransport: per-request resolution and failover."""

import asyncio
import os
import pathlib
import subprocess
import sys

import pytest

from proxylib import EnvProxyConfig, SimpleProxyMap
from proxylib.proxy import ChainProxyMap

httpx = pytest.importorskip("httpx")

from proxylib.integrations.httpx import AsyncProxyTransport, ProxyTransport  # noqa: E402


def _spy(transport):
    """The proxy URL (or None) of every inner transport the outer one used."""
    used = []
    get = transport._transports.get

    def spy(proxy):
        used.append(proxy.uri() if proxy is not None else None)
        return get(proxy)

    transport._transports.get = spy
    return used


def test_a_dead_proxy_fails_over_and_is_skipped_next_time(http_server, dead_port, no_proxy_env):
    http_server.route("/ok", b"fine")
    transport = ProxyTransport(SimpleProxyMap(f"PROXY 127.0.0.1:{dead_port}; DIRECT"))
    used = _spy(transport)
    with httpx.Client(transport=transport) as client:
        assert client.get(http_server.url("/ok")).text == "fine"
        assert used == [f"http://127.0.0.1:{dead_port}", None]
        used.clear()
        assert client.get(http_server.url("/ok")).status_code == 200
        assert used == [None]


def test_without_failover_the_first_error_is_raised(http_server, dead_port, no_proxy_env):
    transport = ProxyTransport(SimpleProxyMap(f"PROXY 127.0.0.1:{dead_port}; DIRECT"), failover=False)
    with httpx.Client(transport=transport) as client, pytest.raises((httpx.ProxyError, httpx.ConnectError)):
        client.get(http_server.url("/ok"))


def test_no_opinion_is_direct_and_the_environment_can_be_chained(http_server, no_proxy_env):
    http_server.route("/ok", b"fine")

    class NoOpinion:
        def __getitem__(self, url):
            raise KeyError(url)

    with httpx.Client(transport=ProxyTransport(NoOpinion())) as client:
        assert client.get(http_server.url("/ok")).status_code == 200
    transport = ProxyTransport(ChainProxyMap(EnvProxyConfig({"NO_PROXY": "*"}), SimpleProxyMap("DIRECT")))
    with httpx.Client(transport=transport) as client:
        assert client.get(http_server.url("/ok")).status_code == 200


def test_close_closes_every_inner_transport(http_server, dead_port, no_proxy_env):
    http_server.route("/ok", b"fine")
    transport = ProxyTransport(SimpleProxyMap(f"PROXY 127.0.0.1:{dead_port}; DIRECT"))
    with httpx.Client(transport=transport) as client:
        client.get(http_server.url("/ok"))
    assert transport._transports.pop_all() == []


def test_async_transport_fails_over(http_server, dead_port, no_proxy_env):
    http_server.route("/ok", b"fine")
    transport = AsyncProxyTransport(SimpleProxyMap(f"PROXY 127.0.0.1:{dead_port}; DIRECT"))
    used = _spy(transport)

    async def main():
        async with httpx.AsyncClient(transport=transport) as client:
            first = await client.get(http_server.url("/ok"))
            second = await client.get(http_server.url("/ok"))
        return first.text, second.status_code

    assert asyncio.run(main()) == ("fine", 200)
    assert used == [f"http://127.0.0.1:{dead_port}", None, None]


def test_async_without_failover_raises(http_server, dead_port, no_proxy_env):
    transport = AsyncProxyTransport(SimpleProxyMap(f"PROXY 127.0.0.1:{dead_port}"), failover=False)

    async def main():
        async with httpx.AsyncClient(transport=transport) as client:
            await client.get(http_server.url("/ok"))

    with pytest.raises((httpx.ProxyError, httpx.ConnectError)):
        asyncio.run(main())


def test_without_httpx_constructing_a_transport_names_it():
    code = (
        "import sys; sys.modules['httpx'] = None\n"
        "import proxylib\n"
        "from proxylib.integrations.httpx import ProxyTransport\n"
        "try:\n    ProxyTransport(proxylib.SimpleProxyMap('DIRECT'))\n"
        "except proxylib.MissingExtraError as exc:\n    print(exc.extra, exc.name)\n"
    )
    env = dict(os.environ, PYTHONPATH=str(pathlib.Path(__file__).resolve().parents[1] / "src"))
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60, env=env)
    assert result.stdout.strip() == "None httpx", result.stderr


def test_the_httpx_patch_target_gives_plain_clients_the_transport(http_server, dead_port, no_proxy_env):
    from proxylib import _net, patch

    http_server.route("/ok", b"fine")
    with patch(SimpleProxyMap(f"PROXY 127.0.0.1:{dead_port}; DIRECT"), targets=["httpx"]):
        with httpx.Client() as client:
            assert type(client._transport).__name__ == "ProxyTransport"
            assert client.get(http_server.url("/ok")).text == "fine"
        with httpx.Client(transport=httpx.HTTPTransport()) as client:
            assert type(client._transport).__name__ == "HTTPTransport"
    assert ("127.0.0.1", dead_port) in _net._circuit_breaker