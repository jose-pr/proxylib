"""alookup(): lookup() for asyncio code."""

import asyncio

import pytest

from proxylib import Proxy, SimpleProxyMap, alookup


def test_alookup_answers_like_lookup():
    assert asyncio.run(alookup({"all": "http://p:1"}, "http://x/")) == (Proxy.parse("http://p:1"),)
    assert asyncio.run(alookup(SimpleProxyMap("PROXY a:1; DIRECT"), "http://x/")) == (Proxy("http", "a", 1), None)


def test_alookup_keeps_no_opinion_a_keyerror():
    with pytest.raises(KeyError):
        asyncio.run(alookup({}, "http://x/"))


def test_alookup_runs_the_map_off_the_event_loop():
    loop_threads = []

    class Recording:
        def __getitem__(self, url):
            import threading

            loop_threads.append(threading.current_thread() is threading.main_thread())
            return None

    asyncio.run(alookup(Recording(), "http://x/"))
    assert loop_threads == [False]
