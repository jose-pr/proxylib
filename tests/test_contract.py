"""The structural ProxyMap contract: anything indexable by URL is a proxy map,
and lookup() reads every answer shape the same way (pathapi's provider shape)."""

import pytest

from proxylib import ChainProxyMap, Proxy, ProxyMap, SimpleProxyMap, lookup


class _HasURL:
    def __init__(self, url, username=None, password=None):
        self.url, self.username, self.password = url, username, password


def test_a_plain_dict_is_a_proxymap():
    assert isinstance({}, ProxyMap)
    assert isinstance(SimpleProxyMap(), ProxyMap)


def test_dict_keyed_by_full_url():
    assert lookup({"http://x/": "http://p:1"}, "http://x/") == (Proxy("http", "p", 1),)


@pytest.mark.parametrize("key", ["http://x", "http", "all://x", "all"])
def test_dict_keyed_like_requests(key):
    assert lookup({key: "http://p:1"}, "http://x/") == (Proxy("http", "p", 1),)


def test_requests_keys_are_tried_most_specific_first():
    proxies = {"all": "http://fallback:1", "http": "http://scheme:1", "http://x": "http://host:1"}
    assert lookup(proxies, "http://x/path")[0].host == "host"
    assert lookup(proxies, "http://other/")[0].host == "scheme"
    assert lookup(proxies, "https://other/")[0].host == "fallback"


def test_dict_none_value_is_direct_and_missing_key_is_no_opinion():
    assert lookup({"all": None}, "http://x/") == (None,)
    with pytest.raises(KeyError):
        lookup({"https": "http://p:1"}, "http://x/")


def test_empty_answer_is_direct():
    assert lookup(SimpleProxyMap([]), "http://x/") == (None,)
    assert lookup({"all": []}, "http://x/") == (None,)
    assert lookup({"all": ""}, "http://x/") == (None,)


def test_object_with_url_and_credentials():
    (proxy,) = lookup({"all": _HasURL("http://p:1", "u", "s")}, "http://x/")
    assert proxy == Proxy("http", "p", 1, username="u", password="s")


def test_credentials_in_the_url_win_over_attributes():
    (proxy,) = lookup({"all": _HasURL("http://a:b@p:1", "u", "s")}, "http://x/")
    assert (proxy.username, proxy.password) == ("a", "b")


def test_list_answer_keeps_order_and_direct_entries():
    answer = ["http://p1:1", None, Proxy("socks5", "s", 2), "PROXY p2:3"]
    assert lookup({"all": answer}, "http://x/") == (
        Proxy("http", "p1", 1),
        None,
        Proxy("socks5", "s", 2),
        Proxy("http", "p2", 3),
    )


def test_pac_result_strings_and_scheme_less_urls():
    assert lookup({"all": "PROXY a:1; DIRECT"}, "http://x/") == (Proxy("http", "a", 1), None)
    assert lookup({"all": "a:1"}, "http://x/") == (Proxy("http", "a", 1),)


def test_unreadable_answer_raises_typeerror():
    with pytest.raises(TypeError):
        lookup({"all": 42}, "http://x/")


def test_chain_accepts_dicts():
    chain = ChainProxyMap({}, {"http": "http://p:1"})
    assert chain["http://x/"] == (Proxy("http", "p", 1),)
    with pytest.raises(KeyError):
        ChainProxyMap({}, {"https": "http://p:1"})["http://x/"]


def test_a_non_mapping_without_opinion_is_not_asked_requests_keys():
    asked = []

    class NoOpinion:
        def __getitem__(self, url):
            asked.append(url)
            raise KeyError(url)

    with pytest.raises(KeyError):
        lookup(NoOpinion(), "http://x/")
    assert asked == ["http://x/"]
