"""Bypass, Cached, RoundRobin, Probed and configure(): each alone, and composed."""

import threading

import pytest

from proxylib import (
    Bypass,
    BypassRules,
    Cached,
    NoReachableProxyError,
    Probed,
    Proxy,
    RoundRobin,
    SimpleProxyMap,
    configure,
)
from proxylib import _net

P = Proxy("http", "p", 80)


class Counting:
    """Records each URL it is asked; answers a fixed result."""

    def __init__(self, result=(P,)):
        self.result = result
        self.calls = []

    def __getitem__(self, url):
        self.calls.append(url)
        return self.result


class NoOpinion:
    def __getitem__(self, url):
        raise KeyError(url)


def _hosts(answer):
    return [p.host if p else None for p in answer]


# ---- Bypass ----------------------------------------------------------------------


def test_bypass_takes_no_proxy_text_or_rules():
    assert Bypass({"all": "http://p:1"}, "example.com")["http://example.com/"] == (None,)
    rules = BypassRules.parse("*.corp", dialect="wininet")
    inner = Counting()
    bypass = Bypass(inner, rules)
    assert bypass["http://a.corp/"] == (None,)
    assert bypass["http://other.com/"] == (P,)
    assert inner.calls == ["http://other.com/"]


def test_bypass_skips_loopback_unless_told_not_to():
    assert Bypass(Counting(), [])["http://127.0.0.1/"] == (None,)
    assert Bypass(Counting(), "<-loopback>")["http://127.0.0.1/"] == (P,)


def test_bypass_passes_no_opinion_through():
    with pytest.raises(KeyError):
        Bypass(NoOpinion(), "example.com")["http://other.com/"]


# ---- Cached ----------------------------------------------------------------------


def test_cached_asks_the_inner_map_once_per_url_within_ttl(monkeypatch):
    import proxylib.wrappers as wrappers

    now = [1000.0]
    monkeypatch.setattr(wrappers.time, "monotonic", lambda: now[0])
    inner = Counting()
    cached = Cached(inner, ttl=60)
    cached["http://x/"], cached["http://x/"], cached["http://y/"]
    assert inner.calls == ["http://x/", "http://y/"]
    now[0] += 61
    cached["http://x/"]
    assert inner.calls[-1] == "http://x/" and len(inner.calls) == 3


def test_cached_is_bounded_and_drops_the_least_recent():
    inner = Counting()
    cached = Cached(inner, ttl=60, maxsize=10)
    for i in range(1000):
        cached[f"http://h{i}/"]
    assert len(cached) <= 10

    small = Cached(Counting(), ttl=60, maxsize=2)
    small["http://a/"], small["http://b/"], small["http://a/"], small["http://c/"]
    small.inner.calls.clear()
    small["http://a/"], small["http://b/"]
    assert small.inner.calls == ["http://b/"]


def test_cached_does_not_cache_no_opinion_and_can_be_cleared():
    with pytest.raises(KeyError):
        Cached(NoOpinion(), ttl=60)["http://x/"]
    inner = Counting()
    cached = Cached(inner, ttl=60)
    cached["http://x/"]
    cached.clear()
    cached["http://x/"]
    assert inner.calls == ["http://x/", "http://x/"]


def test_cached_rejects_nonsense():
    with pytest.raises(ValueError):
        Cached(Counting(), ttl=0)
    with pytest.raises(ValueError):
        Cached(Counting(), ttl=1, maxsize=0)


# ---- RoundRobin ------------------------------------------------------------------


def test_round_robin_rotates_cached_answers():
    proxymap = RoundRobin(Cached(SimpleProxyMap("PROXY a:1; PROXY b:1; PROXY c:1"), ttl=60))
    assert [proxymap["http://x/"][0].host for _ in range(4)] == ["a", "b", "c", "a"]


def test_round_robin_shares_one_rotation_per_answer_and_keeps_fallbacks():
    proxymap = RoundRobin(SimpleProxyMap("PROXY a:1; PROXY b:1; DIRECT"))
    assert _hosts(proxymap["http://x/"]) == ["a", "b", None]
    assert _hosts(proxymap["http://other/"]) == ["b", None, "a"]


def test_round_robin_leaves_a_single_entry_alone():
    proxymap = RoundRobin(Counting())
    assert proxymap["http://x/"] == (P,) == proxymap["http://x/"]


def test_round_robin_is_thread_safe():
    proxymap = RoundRobin(SimpleProxyMap("PROXY a:1; PROXY b:1"))
    firsts = []

    def worker():
        for _ in range(500):
            firsts.append(proxymap["http://x/"][0].host)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(set(firsts)) == ["a", "b"] and abs(firsts.count("a") - firsts.count("b")) == 0


# ---- Probed ----------------------------------------------------------------------


def test_probed_answers_the_first_reachable(monkeypatch):
    seen = {}

    def first(proxies, timeout):
        seen["timeout"] = timeout
        return proxies[1]

    monkeypatch.setattr(_net, "first_working_proxy", first)
    proxymap = Probed(SimpleProxyMap("PROXY a:1; PROXY b:1"), timeout=1.5)
    assert _hosts(proxymap["http://x/"]) == ["b"]
    assert seen == {"timeout": 1.5}


def test_probed_raises_when_nothing_is_reachable(monkeypatch):
    def nothing(proxies, timeout):
        raise NoReachableProxyError("none")

    monkeypatch.setattr(_net, "first_working_proxy", nothing)
    with pytest.raises(NoReachableProxyError) as info:
        Probed(SimpleProxyMap("PROXY a:1"))["http://x/"]
    assert not isinstance(info.value, KeyError)


def test_probed_passes_no_opinion_through():
    with pytest.raises(KeyError):
        Probed(NoOpinion())["http://x/"]


# ---- configure -------------------------------------------------------------------


def test_configure_with_nothing_is_the_inner_map():
    inner = Counting()
    assert configure(inner) is inner


def test_configure_bypass_runs_first():
    inner = Counting()
    proxymap = configure(inner, bypass="example.com", cache_ttl=60, round_robin=True)
    assert proxymap["http://example.com/"] == (None,)
    assert inner.calls == []


def test_configure_probes_the_rotated_answer(monkeypatch):
    monkeypatch.setattr(_net, "first_working_proxy", lambda proxies, timeout: proxies[0])
    inner = Counting(Proxy.parse_pac_result("PROXY a:1; PROXY b:1"))
    proxymap = configure(inner, cache_ttl=60, round_robin=True, probe=True)
    assert [proxymap["http://x/"][0].host for _ in range(3)] == ["a", "b", "a"]
    assert len(inner.calls) == 1


def test_configure_caches_the_probed_answer_without_rotation(monkeypatch):
    probes = []
    monkeypatch.setattr(_net, "first_working_proxy", lambda proxies, timeout: probes.append(1) or proxies[0])
    proxymap = configure(Counting(), cache_ttl=60, probe=True)
    proxymap["http://x/"], proxymap["http://x/"]
    assert probes == [1]
