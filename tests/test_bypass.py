import warnings

import pytest

from proxylib import BypassRules

# ---- no_proxy (curl) dialect -----------------------------------------------------


@pytest.mark.parametrize(
    "no_proxy, url, expected",
    [
        ("example.com", "http://example.com/", True),
        ("example.com", "http://api.example.com/", True),
        ("example.com", "http://evilexample.com/", False),
        (".example.com", "http://example.com/", True),
        ("*.example.com", "http://api.example.com/", True),
        ("example.com:8080", "http://example.com:8080/", True),
        ("example.com:8080", "http://example.com/", False),
        ("10.0.0.0/8", "http://10.1.2.3/", True),
        ("10.0.0.0/8", "http://11.1.2.3/", False),
        ("169.254/16", "http://169.254.1.2/", True),
        ("2001:db8::/32", "http://[2001:db8::1]/", True),
        ("[::1]", "http://[::1]:8080/", True),
        ("*", "http://anything.test/", True),
        ("other.com,*", "http://example.com/", False),
    ],
)
def test_no_proxy_dialect(no_proxy, url, expected):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        rules = BypassRules.parse(no_proxy)
    assert rules.matches(url) is expected


def test_cidr_never_resolves_a_hostname(monkeypatch):
    import proxylib._net as net

    monkeypatch.setattr(net, "resolve_ip", lambda *a, **k: pytest.fail("resolved a name"))
    assert not BypassRules.parse("10.0.0.0/8").matches("http://example.com/")


def test_star_among_other_entries_warns_and_is_ignored():
    with pytest.warns(UserWarning, match="ignored"):
        rules = BypassRules.parse("other.com,*")
    assert not rules.matches("http://example.com/")


def test_unparsable_entries_warn_once_and_the_rest_apply():
    with pytest.warns(UserWarning, match="10.0.0.0/33"):
        rules = BypassRules.parse("10.0.0.0/33, host:abc, example.com")
    assert rules.matches("http://example.com/")


def test_loopback_bypasses_unless_turned_off():
    assert BypassRules.NONE.matches("http://localhost:8080/")
    assert BypassRules.parse("").matches("http://127.0.0.2/")
    assert BypassRules.parse("").matches("http://[::1]/")
    assert BypassRules.parse("").matches("http://app.localhost/")
    assert not BypassRules.parse("<-loopback>").matches("http://localhost/")


def test_local_means_a_dotless_host():
    rules = BypassRules.parse("<local>")
    assert rules.matches("http://intranet/")
    assert not rules.matches("http://intranet.corp/")
    assert not rules.matches("http://[fe80::1]/")


def test_subnet_matches_link_local_without_dns():
    assert BypassRules.parse("<subnet>").matches("http://169.254.10.10/")
    assert not BypassRules.parse("<subnet>").matches("http://8.8.8.8/")


def test_rules_combine_and_compare():
    a, b = BypassRules.parse("a.test"), BypassRules.parse("b.test")
    both = a | b
    assert both.matches("http://a.test/") and both.matches("http://b.test/")
    assert BypassRules.parse("a.test") == a and a != b
    assert not BypassRules.NONE and a


def test_unknown_dialect_is_an_error():
    with pytest.raises(ValueError):
        BypassRules.parse("x", dialect="winhttp")


# ---- OS dialects ----------------------------------------------------------------


def test_wininet_dialect():
    rules = BypassRules.parse("*.corp.example.com;10.*;<local>", dialect="wininet")
    for url in ("http://intranet/", "http://a.corp.example.com/", "http://10.1.2.3/"):
        assert rules.matches(url), url
    assert not rules.matches("http://example.com/")
    # A plain WinINet entry is exact, unlike curl's suffix match.
    exact = BypassRules.parse("corp.example.com", dialect="wininet")
    assert not exact.matches("http://a.corp.example.com/")


def test_macos_dialect():
    rules = BypassRules.parse(["169.254/16", "*.local"], dialect="macos")
    assert rules.matches("http://169.254.3.4/")
    assert rules.matches("http://printer.local/")
    assert not rules.matches("http://example.com/")


def test_gsettings_dialect():
    rules = BypassRules.parse(
        ["localhost", "::1", "*.local", "192.168.0.0/16"], dialect="gsettings"
    )
    assert rules.matches("http://[::1]:80/")
    assert rules.matches("http://a.local/")
    assert rules.matches("http://192.168.4.4/")


def test_kde_dialect_and_reversed_exception():
    assert BypassRules.parse("*.kde.org", dialect="kde").matches("http://www.kde.org/")
    reversed_rules = BypassRules.parse("*.kde.org", dialect="kde", reversed=True)
    assert not reversed_rules.matches("http://www.kde.org/")
    assert reversed_rules.matches("http://example.com/")


# ---- differential test against requests --------------------------------------

# (url, NO_PROXY) pairs where proxylib and requests.utils.should_bypass_proxies agree.
_SAME_AS_REQUESTS = [
    ("http://example.com/", "example.com"),
    ("http://api.example.com/", "example.com"),
    ("http://api.example.com/", ".example.com"),
    ("http://example.com:8080/", "example.com:8080"),
    ("http://example.com/", "example.com:8080"),
    ("http://10.1.2.3/", "10.0.0.0/8"),
    ("http://11.1.2.3/", "10.0.0.0/8"),
    ("http://10.1.2.3/", "10.1.2.3"),
    ("http://192.168.1.5:8080/", "192.168.0.0/16"),
    ("http://other.org/", "example.com,other.org"),
    ("http://x.other.org/", "example.com, other.org"),
    ("http://example.com/", "other.com,*"),
    ("http://EXAMPLE.com/", "example.com"),
    ("http://example.com.au/", "example.com"),
    ("http://foo/", "foo"),
    ("http://foo.bar/", "bar"),
    ("http://example.org/", ""),
    ("http://example.org/", "example.com"),
]

# requests 2.32 (the last release for Python 3.9) matched a bare suffix without
# a dot boundary and did not let ".example.com" match example.com itself;
# later releases agree with these answers, so only proxylib's side is checked.
_REQUESTS_VERSION_DEPENDENT = [
    ("http://evilexample.com/", "example.com", False),
    ("http://example.com/", ".example.com", True),
]

# Deliberate differences; the shipped header lists them too.
_DIFFERENT_FROM_REQUESTS = [
    # A URL without a port has the scheme's default port.
    ("https://example.com/", "example.com:443", True),
    # Entries are case-insensitive, as host names are.
    ("http://example.com/", "EXAMPLE.COM", True),
    # Loopback always bypasses (Chromium, Go), unless "<-loopback>".
    ("http://localhost/", "example.com", True),
    ("http://127.0.0.1/", "", True),
    # IPv6 CIDR entries match bracketed IPv6 hosts.
    ("http://[2001:db8::1]/", "2001:db8::/32", True),
]


@pytest.fixture
def should_bypass(monkeypatch):
    requests_utils = pytest.importorskip("requests.utils")
    # proxy_bypass() reads the OS settings; only the NO_PROXY text is compared.
    monkeypatch.setattr(requests_utils, "proxy_bypass", lambda host: False)
    return requests_utils.should_bypass_proxies


@pytest.mark.parametrize("url, no_proxy", _SAME_AS_REQUESTS)
def test_matches_requests(should_bypass, url, no_proxy):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        ours = BypassRules.parse(no_proxy).matches(url)
    assert ours is should_bypass(url, no_proxy=no_proxy)


@pytest.mark.parametrize("url, no_proxy, ours", _REQUESTS_VERSION_DEPENDENT)
def test_cases_older_requests_got_wrong(url, no_proxy, ours):
    assert BypassRules.parse(no_proxy).matches(url) is ours


@pytest.mark.parametrize("url, no_proxy, ours", _DIFFERENT_FROM_REQUESTS)
def test_known_differences_from_requests(should_bypass, url, no_proxy, ours):
    assert BypassRules.parse(no_proxy).matches(url) is ours
    assert should_bypass(url, no_proxy=no_proxy) is not ours
