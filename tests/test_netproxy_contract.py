"""What netproxy (an asyncio proxy server routing egress through proxylib)
relies on. A failure here breaks a known consumer."""

import asyncio

import pytest

from proxylib import BypassRules, Proxy, ProxyMap, SimpleProxyMap, alookup, loads_pac, lookup
from proxylib.pac import engines


def test_proxy_strings_parse_as_netproxy_builds_them():
    assert lookup(SimpleProxyMap("PROXY a:1; DIRECT"), "http://x/") == (Proxy("http", "a", 1), None)
    assert lookup(SimpleProxyMap("direct"), "http://x/") == (None,)
    assert lookup(SimpleProxyMap("http://a:1"), "http://x/") == (Proxy("http", "a", 1),)
    assert lookup(ProxyMap("http://a:1"), "http://x/") == (Proxy("http", "a", 1),)


def test_no_opinion_is_keyerror():
    with pytest.raises(KeyError):
        lookup({}, "http://x/")


def test_a_password_never_reaches_repr_or_str():
    proxy = Proxy.parse("http://u:secret@a:1")
    assert "secret" not in repr(proxy) and "secret" not in str(proxy)
    assert "secret" in proxy.uri()


def test_bypass_rules_stand_alone():
    rules = BypassRules.parse("*.corp,10.0.0.0/8")
    assert rules.matches("http://a.corp/")
    assert rules.matches("http://10.1.2.3/")
    assert not rules.matches("http://example.com/")


PAC = """
function FindProxyForURL(url, host) {
    host = host.toLowerCase();
    if (shExpMatch(host, "*.internal")) return "DIRECT";
    return "PROXY egress:3128; DIRECT";
}
"""


@pytest.mark.skipif(not engines.names(), reason="no JS engine installed")
def test_a_pac_given_as_text_runs_and_answers_from_concurrent_tasks():
    proxymap = loads_pac(PAC)
    assert lookup(proxymap, "http://App.Internal/") == (None,)

    async def main():
        urls = [f"http://h{i}.example.com/" if i % 2 else f"http://h{i}.internal/" for i in range(8)]
        return await asyncio.gather(*(alookup(proxymap, url) for url in urls))

    answers = asyncio.run(main())
    assert answers == [(None,) if i % 2 == 0 else (Proxy("http", "egress", 3128), None) for i in range(8)]
