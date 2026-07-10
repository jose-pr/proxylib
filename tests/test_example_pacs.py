"""End-to-end coverage: load the example PAC files in examples/ through the
real dukpy JS engine and exercise every PAC utility function via
FindProxyForURL, not just the Python-level unit tests in test_pac.py.

The main thing these catch that direct unit tests can't: a PAC utility
function that isn't correctly exported into the JS engine (JSContextMeta
bugs, a missing/misnamed export) raises inside dukpy the moment a real PAC
script calls it -- these tests call every function via an actual script.
"""

import pytest

pytest.importorskip("dukpy")

from proxylib import Proxy, load_pac


def _proxy_names(result):
    return [None if p is None else p.host for p in result]


# ---- examples/time_restricted.pac (weekdayRange, dateRange, timeRange) -------


@pytest.fixture(scope="module")
def time_restricted():
    return load_pac("file:examples/time_restricted.pac")


def test_time_restricted_intranet_always_direct(time_restricted):
    # Deterministic regardless of current date/time/weekday.
    assert time_restricted["https://build.intranet.example.com/"] == [None]


def test_time_restricted_external_host_does_not_crash(time_restricted):
    # weekdayRange/dateRange/timeRange all get exercised for this lookup;
    # the actual outcome depends on when the test runs, so just check it
    # resolves to a well-formed result (DIRECT, or a PROXY;DIRECT chain).
    result = time_restricted["https://example.com/"]
    assert isinstance(result, list) and len(result) >= 1
    assert result[-1] is None  # every branch ends in a DIRECT fallback
    assert all(p is None or isinstance(p, Proxy) for p in result)


# ---- examples/enterprise_loadbalance.pac (shExpMatch, isInNet+myIpAddress) ---


@pytest.fixture(scope="module")
def enterprise():
    return load_pac("file:examples/enterprise_loadbalance.pac")


def test_enterprise_internal_domain_is_direct(enterprise):
    assert enterprise["https://build.corp.example.com/"] == [None]
    assert enterprise["https://plainhost/"] == [None]


def test_enterprise_shexpmatch_routes_by_destination(enterprise):
    assert _proxy_names(enterprise["https://shop.example.com/"]) == [
        "proxy1.example.com",
        "proxy4.example.com",
    ]
    assert _proxy_names(enterprise["https://library.some.edu/"]) == [
        "proxy2.example.com",
        "proxy4.example.com",
    ]


def test_enterprise_client_subnet_fallback_does_not_crash(enterprise):
    # Exercises myIpAddress()+isInNet() from JS; which chain wins depends on
    # the machine's real IP, so only check it's well-formed.
    result = enterprise["https://other.net/"]
    assert len(result) == 2
    assert all(isinstance(p, Proxy) for p in result)


# ---- examples/ms_extensions.pac (the Microsoft *Ex extensions) ---------------


@pytest.fixture(scope="module")
def ms_extensions():
    return load_pac("file:examples/ms_extensions.pac")


def test_ms_extensions_plain_hostname_is_direct(ms_extensions):
    assert ms_extensions["https://plainhost/"] == [None]


def test_ms_extensions_unresolvable_host_hits_fallback(ms_extensions):
    # DNS for made-up hostnames reliably fails in this environment (and any
    # sandboxed/offline CI runner), so isResolvableEx() deterministically
    # returns false here -- exercises getClientVersion, isPlainHostName,
    # and isResolvableEx/dnsResolveEx from JS.
    result = ms_extensions["https://this-host-does-not-exist.invalid.example/"]
    assert _proxy_names(result) == ["unreachable-fallback.example.com"]


def test_ms_extensions_resolvable_host_exercises_ex_functions(ms_extensions):
    # localhost resolves in any environment -- reaches sortIpAddressList,
    # dnsResolveEx, isInNetEx, and myIpAddressEx.
    result = ms_extensions["https://localhost/"]
    assert isinstance(result, list) and len(result) >= 1
    assert all(p is None or isinstance(p, Proxy) for p in result)
