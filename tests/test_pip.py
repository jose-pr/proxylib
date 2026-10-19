"""The pip patch target: pip's vendored requests routed through the active map."""

import os
import subprocess
import sys

import pytest

import proxylib
from proxylib import Proxy, SimpleProxyMap

pytest.importorskip("pip._vendor.requests")
from pip._internal.network.session import PipSession  # noqa: E402
from pip._vendor.urllib3 import __version__ as pip_urllib3_version  # noqa: E402

INDEX = "http://example.test/simple/"


def _targets(server):
    return [target for _, target, _ in server.seen]


def test_a_pip_session_routes_through_the_patched_map(recording_proxy, dead_port, no_proxy_env):
    pac = f"PROXY 127.0.0.1:{dead_port}; PROXY 127.0.0.1:{recording_proxy.port}"
    with proxylib.patch(SimpleProxyMap(pac), targets=["pip"]):
        with PipSession() as session:
            assert session.get(INDEX + "a/", timeout=10).text == "via proxy"
    assert _targets(recording_proxy) == [INDEX + "a/"]


@pytest.mark.skipif(
    pip_urllib3_version.startswith("1."),
    reason="pip with urllib3 1.x fails HTTPS through a proxy with its own ssl_context, proxylib or not",
)
def test_a_pip_session_sends_proxy_headers_and_keeps_pips_tls_context(
    recording_proxy, tls_server, no_proxy_env
):
    import ssl

    proxy = Proxy("http", "127.0.0.1", recording_proxy.port, headers={"X-Proxy-Token": "s3cret"})
    # pip's own TLS context, the one that trusts the test certificate: it must
    # reach the tunnelled connection unchanged.
    context = ssl.create_default_context(cafile=tls_server.cafile)
    with proxylib.patch(SimpleProxyMap(proxy), targets=["pip"]):
        with PipSession(ssl_context=context) as session:
            response = session.get(f"https://127.0.0.1:{tls_server.port}/x", timeout=10)
    assert response.text == "tls ok"
    [(method, _, headers)] = recording_proxy.seen
    assert method == "CONNECT" and headers["x-proxy-token"] == "s3cret"
    [(_, _, reached)] = tls_server.seen
    assert "x-proxy-token" not in reached


def test_pips_caching_adapter_routes_through_the_map(recording_proxy, tmp_path, no_proxy_env):
    # CacheControlAdapter calls HTTPAdapter.send with positional arguments.
    with proxylib.patch(SimpleProxyMap(f"PROXY 127.0.0.1:{recording_proxy.port}"), targets=["pip"]):
        with PipSession(cache=str(tmp_path / "cache"), trusted_hosts=["example.test"]) as session:
            assert type(session.get_adapter(INDEX)).__name__.endswith("CacheControlAdapter")
            assert session.get(INDEX + "c/", timeout=10).text == "via proxy"
    assert _targets(recording_proxy) == [INDEX + "c/"]


def test_a_session_that_does_not_trust_the_environment_is_left_to_pip(
    recording_proxy, http_server, no_proxy_env
):
    http_server.route("/direct", b"direct")
    with proxylib.patch(SimpleProxyMap(f"PROXY 127.0.0.1:{recording_proxy.port}"), targets=["pip"]):
        with PipSession() as session:
            session.trust_env = False  # what pip --proxy and --no-proxy-env do
            assert session.get(http_server.url("/direct"), timeout=10).text == "direct"
    assert recording_proxy.seen == []


def test_a_patch_that_leaves_pip_out_does_not_route_it(recording_proxy, http_server, no_proxy_env):
    http_server.route("/direct", b"direct")
    with proxylib.patch(SimpleProxyMap(f"PROXY 127.0.0.1:{recording_proxy.port}"), targets=["requests"]):
        with PipSession() as session:
            assert session.get(http_server.url("/direct"), timeout=10).text == "direct"
    assert recording_proxy.seen == []


def _pip_download(tmp_path, *args, **env):
    environ = {k: v for k, v in os.environ.items() if not k.lower().endswith("_proxy") and not k.startswith("PROXYLIB_")}
    environ.update(env)
    command = [
        sys.executable, "-m", "pip", "download", "somepkg", "--no-deps", "--cache-dir", str(tmp_path / "cache"),
        "--disable-pip-version-check", "--retries", "0", "--timeout", "5",
        "--index-url", INDEX, "--trusted-host", "example.test", "-d", str(tmp_path), *args,
    ]
    return subprocess.run(command, capture_output=True, text=True, timeout=120, env=environ)


def test_pip_download_follows_a_proxy_variable_pip_cannot_read_itself(
    tmp_path, recording_proxy, dead_port, no_proxy_env
):
    chain = f"PROXY 127.0.0.1:{dead_port}; PROXY 127.0.0.1:{recording_proxy.port}"
    without = _pip_download(tmp_path, HTTP_PROXY=chain, PROXYLIB_IMPORTPATCH="requests")
    assert recording_proxy.seen == [], without.stderr
    _pip_download(tmp_path, HTTP_PROXY=chain)
    assert INDEX + "somepkg/" in _targets(recording_proxy)


def test_pip_proxy_option_wins_over_the_map(tmp_path, recording_proxy, gateway, no_proxy_env):
    result = _pip_download(
        tmp_path,
        "--proxy", f"http://127.0.0.1:{gateway.port}",
        HTTP_PROXY=f"PROXY 127.0.0.1:{recording_proxy.port}",
        PROXYLIB_AUTOPROXY="pip",
    )
    assert INDEX + "somepkg/" in _targets(gateway), result.stderr
    assert recording_proxy.seen == []
