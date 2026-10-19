"""The PAC time builtins under a frozen clock, and a failing PAC script through
every client integration."""

import asyncio
import datetime
import urllib.request

import pytest

import proxylib
import proxylib.pac._functions as functions_module
from proxylib import PACError, PacProxyMap, ProxyMapHandler, loads_pac
from proxylib.pac import engines
from proxylib.pac import functions as f

# Local time is Thursday 24 December 2026, 23:30:15; UTC is already Friday 25
# December, 04:30:15 (a UTC-5 zone), so "GMT" forms answer differently.
LOCAL = datetime.datetime(2026, 12, 24, 23, 30, 15)
UTC = datetime.datetime(2026, 12, 25, 4, 30, 15, tzinfo=datetime.timezone.utc)


@pytest.fixture
def frozen(monkeypatch):
    monkeypatch.setattr(functions_module, "_now", lambda gmt: UTC if gmt else LOCAL)


# Each case is from the PAC references' examples (Netscape, MDN), answered as
# Chromium's PAC library (shared with Firefox) answers at that moment.
@pytest.mark.parametrize(
    "args, expected",
    [
        (("THU",), True),
        (("FRI",), False),
        (("FRI", "GMT"), True),
        (("MON", "FRI"), True),
        (("FRI", "MON"), False),
        (("FRI", "MON", "GMT"), True),
        (("SAT", "THU"), True),
        (("thu",), True),
        (("XYZ",), False),
        (("MON", "XYZ"), False),
    ],
)
def test_weekdayRange(frozen, args, expected):
    assert f["weekdayRange"](*args) is expected


@pytest.mark.parametrize(
    "args, expected",
    [
        ((24,), True),
        ((25,), False),
        ((25, "GMT"), True),
        (("DEC",), True),
        (("NOV",), False),
        ((2026,), True),
        ((2025,), False),
        ((1, 24), True),
        ((1, 23), False),
        ((25, 3), False),
        (("JAN", "MAR"), False),
        (("NOV", "DEC"), True),
        (("NOV", "FEB"), True),
        ((2025, 2027), True),
        ((2027, 2028), False),
        ((1, "JUN", 15, "AUG"), False),
        ((1, "DEC", 31, "DEC"), True),
        ((25, "DEC", 1, "JAN"), False),
        ((25, "DEC", 1, "JAN", "GMT"), True),
        (("OCT", 2026, "MAR", 2027), True),
        (("OCT", 2025, "MAR", 2026), False),
        ((1, "JUN", 2026, 24, "DEC", 2026), True),
        ((1, "JUN", 2026, 23, "DEC", 2026), False),
        # Two values with a day keep both ends in the current month (Chromium).
        ((24, "DEC"), True),
        ((24, "JAN"), True),
        ((25, "DEC"), False),
        (("15",), False),
        (("24",), True),
        (("XYZ",), False),
        (("JAN", "XYZ"), False),
        ((), False),
    ],
)
def test_dateRange(frozen, args, expected):
    assert f["dateRange"](*args) is expected


@pytest.mark.parametrize(
    "args, expected",
    [
        ((23,), True),
        ((4,), False),
        ((4, "GMT"), True),
        ((9, 17), False),
        ((22, 23), True),
        ((23, 23), True),
        ((22, 6), False),  # the hour form does not wrap (Chromium)
        ((0, 6, "GMT"), True),
        ((23, 30, 23, 30), True),
        ((23, 0, 23, 29), False),
        ((22, 0, 6, 0), True),  # minute and second forms wrap
        ((4, 0, 5, 0, "GMT"), True),
        ((23, 30, 0, 23, 30, 14), False),
        ((23, 30, 15, 23, 30, 15), True),
        ((23, 31, 0, 23, 29, 0), False),
        ((23, 0, 0, 1, 0, 0), True),
        ((1, 2, 3), False),
    ],
)
def test_timeRange(frozen, args, expected):
    assert f["timeRange"](*args) is expected


# ---- a PAC script that throws, through every client ---------------------------------

needs_engine = pytest.mark.skipif(not engines.names(), reason="no JS engine installed")

THROWS = "function FindProxyForURL(url, host) { throw new Error('boom'); }"


@pytest.fixture
def throwing_pac():
    pac = loads_pac(THROWS)
    yield pac
    pac.close()


def _target(server):
    """A URL on ``server``, which records any request that reaches it."""
    return f"http://127.0.0.1:{server.port}/x"


@needs_engine
def test_a_throwing_pac_raises_pac_error_from_lookup(throwing_pac):
    with pytest.raises(PACError, match="boom"):
        proxylib.lookup(throwing_pac, "http://example.test/")


@needs_engine
def test_requests_raises_the_pac_error_and_sends_nothing(throwing_pac, recording_proxy, no_proxy_env):
    requests = pytest.importorskip("requests")
    from proxylib import ProxyMapAdapter

    with requests.Session() as session:
        session.trust_env = False
        session.mount("http://", ProxyMapAdapter(throwing_pac))
        with pytest.raises(PACError, match="boom"):
            session.get(_target(recording_proxy), timeout=10)
    assert recording_proxy.seen == []


@needs_engine
def test_a_patched_requests_raises_the_pac_error(throwing_pac, recording_proxy, no_proxy_env):
    requests = pytest.importorskip("requests")
    with proxylib.patch(throwing_pac, targets=["requests"]):
        with pytest.raises(PACError, match="boom"):
            requests.get(_target(recording_proxy), timeout=10)
    assert recording_proxy.seen == []


@needs_engine
def test_httpx_raises_the_pac_error_and_sends_nothing(throwing_pac, recording_proxy, no_proxy_env):
    httpx = pytest.importorskip("httpx")
    from proxylib.integrations.httpx import AsyncProxyTransport, ProxyTransport

    with httpx.Client(transport=ProxyTransport(throwing_pac)) as client:
        with pytest.raises(PACError, match="boom"):
            client.get(_target(recording_proxy), timeout=10)

    async def main():
        async with httpx.AsyncClient(transport=AsyncProxyTransport(throwing_pac)) as client:
            await client.get(_target(recording_proxy), timeout=10)

    with pytest.raises(PACError, match="boom"):
        asyncio.run(main())
    assert recording_proxy.seen == []


@needs_engine
def test_aiohttp_raises_the_pac_error_and_sends_nothing(throwing_pac, recording_proxy, no_proxy_env):
    pytest.importorskip("aiohttp")
    from proxylib.integrations.aiohttp import ProxySession

    async def main():
        async with ProxySession(throwing_pac) as session:
            async with session.get(_target(recording_proxy)) as response:
                return response.status

    with pytest.raises(PACError, match="boom"):
        asyncio.run(main())
    assert recording_proxy.seen == []


@needs_engine
def test_urllib_raises_the_pac_error_and_sends_nothing(throwing_pac, recording_proxy, no_proxy_env):
    opener = urllib.request.build_opener(ProxyMapHandler(throwing_pac))
    with pytest.raises(PACError, match="boom"):
        opener.open(_target(recording_proxy), timeout=10)
    assert recording_proxy.seen == []


def test_a_python_pac_that_raises_is_a_pac_error_too(recording_proxy, no_proxy_env):
    requests = pytest.importorskip("requests")
    from proxylib import ProxyMapAdapter

    def find_proxy(url, host):
        raise RuntimeError("boom")

    with requests.Session() as session:
        session.trust_env = False
        session.mount("http://", ProxyMapAdapter(PacProxyMap(find_proxy)))
        with pytest.raises(PACError, match="boom"):
            session.get(_target(recording_proxy), timeout=10)
    assert recording_proxy.seen == []
