from proxylib.pac import PAC
from proxylib.pac.wpad import _candidate_domains, discover


def test_candidate_domains_walks_up_skipping_bare_tld():
    domains = list(_candidate_domains("host.corp.example.com"))
    assert domains == ["corp.example.com", "example.com"]


def test_candidate_domains_short_fqdn_yields_nothing():
    assert list(_candidate_domains("host.com")) == []


def test_discover_returns_none_when_no_wpad_host_resolves(monkeypatch):
    monkeypatch.setattr(
        "socket.gethostbyname", lambda host: (_ for _ in ()).throw(OSError())
    )
    assert discover("host.corp.example.com") is None


def test_discover_loads_pac_from_first_resolving_wpad_host(monkeypatch):
    monkeypatch.setattr(
        "socket.gethostbyname",
        lambda host: "10.0.0.1" if host == "wpad.example.com" else (_ for _ in ()).throw(OSError()),
    )

    sentinel = PAC()

    def fake_load(url, **kwargs):
        assert url == "http://wpad.example.com/wpad.dat"
        return sentinel

    monkeypatch.setattr("proxylib.pac.wpad.load", fake_load)

    result = discover("host.corp.example.com")
    assert result is sentinel
