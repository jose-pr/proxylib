"""ProxySession: per-request resolution and failover over aiohttp."""

import asyncio
import os
import pathlib
import subprocess
import sys

import pytest

from proxylib import SimpleProxyMap

aiohttp = pytest.importorskip("aiohttp")

from proxylib.integrations.aiohttp import ProxySession  # noqa: E402


class NoOpinion:
    def __getitem__(self, url):
        raise KeyError(url)


def _spy(monkeypatch):
    """The proxy= of every ClientSession.request call."""
    used = []
    original = aiohttp.ClientSession.request

    def request(self, method, url, **kwargs):
        used.append(kwargs.get("proxy"))
        return original(self, method, url, **kwargs)

    monkeypatch.setattr(aiohttp.ClientSession, "request", request)
    return used


def test_a_dead_proxy_fails_over_and_is_skipped_next_time(http_server, dead_port, no_proxy_env, monkeypatch):
    http_server.route("/ok", b"fine")
    used = _spy(monkeypatch)
    dead = f"http://127.0.0.1:{dead_port}"

    async def main():
        async with ProxySession(SimpleProxyMap(f"PROXY 127.0.0.1:{dead_port}; DIRECT")) as session:
            async with session.get(http_server.url("/ok")) as response:
                first = await response.text()
            second = await session.get(http_server.url("/ok"))
            second.release()
            return first, second.status

    assert asyncio.run(main()) == ("fine", 200)
    assert used == [dead, None, None]


def test_without_failover_the_connection_error_is_raised(http_server, dead_port, no_proxy_env):
    async def main():
        async with ProxySession(SimpleProxyMap(f"PROXY 127.0.0.1:{dead_port}; DIRECT"), failover=False) as session:
            await session.get(http_server.url("/ok"))

    with pytest.raises(aiohttp.ClientConnectorError):
        asyncio.run(main())


def test_a_chain_given_as_proxy_is_resolved(http_server, dead_port, no_proxy_env, monkeypatch):
    http_server.route("/ok", b"fine")
    used = _spy(monkeypatch)

    async def main():
        async with ProxySession(NoOpinion()) as session:
            async with session.get(http_server.url("/ok"), proxy=f"PROXY 127.0.0.1:{dead_port}; DIRECT") as response:
                return response.status

    assert asyncio.run(main()) == 200
    assert used == [f"http://127.0.0.1:{dead_port}", None]


def test_no_opinion_sends_as_aiohttp_would(http_server, no_proxy_env, monkeypatch):
    http_server.route("/ok", b"fine")
    used = _spy(monkeypatch)

    async def main():
        async with ProxySession(NoOpinion()) as session:
            async with session.post(http_server.url("/ok"), data=b"x") as response:
                return response.status

    asyncio.run(main())
    assert used == [None]


def test_a_session_passed_in_is_not_closed(http_server, no_proxy_env):
    http_server.route("/ok", b"fine")

    async def main():
        async with aiohttp.ClientSession() as inner:
            async with ProxySession(SimpleProxyMap("DIRECT"), inner) as session:
                async with session.get(http_server.url("/ok")) as response:
                    await response.read()
            return inner.closed

    assert asyncio.run(main()) is False
    with pytest.raises(TypeError):
        ProxySession(SimpleProxyMap("DIRECT"), object(), timeout=1)


def test_without_aiohttp_constructing_a_session_names_it():
    code = (
        "import sys; sys.modules['aiohttp'] = None\n"
        "import proxylib\n"
        "from proxylib.integrations.aiohttp import ProxySession\n"
        "try:\n    ProxySession(proxylib.SimpleProxyMap('DIRECT'))\n"
        "except proxylib.MissingExtraError as exc:\n    print(exc.extra, exc.name)\n"
    )
    env = dict(os.environ, PYTHONPATH=str(pathlib.Path(__file__).resolve().parents[1] / "src"))
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60, env=env)
    assert result.stdout.strip() == "None aiohttp", result.stderr


def test_the_aiohttp_patch_target_routes_plain_sessions(http_server, dead_port, no_proxy_env):
    from proxylib import _net, patch

    http_server.route("/ok", b"fine")

    async def main():
        async with aiohttp.ClientSession() as session:
            async with session.get(http_server.url("/ok")) as response:
                return response.status

    with patch(SimpleProxyMap(f"PROXY 127.0.0.1:{dead_port}; DIRECT"), targets=["aiohttp"]):
        assert asyncio.run(main()) == 200
    assert ("127.0.0.1", dead_port) in _net._circuit_breaker


def test_a_proxysession_choice_is_not_routed_again_by_the_patch_target(http_server, dead_port, no_proxy_env):
    from proxylib import patch

    http_server.route("/ok", b"fine")

    async def main():
        async with ProxySession(SimpleProxyMap("DIRECT")) as session:
            async with session.get(http_server.url("/ok")) as response:
                return response.status

    with patch(SimpleProxyMap(f"PROXY 127.0.0.1:{dead_port}"), targets=["aiohttp"]):
        assert asyncio.run(main()) == 200