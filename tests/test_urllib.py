import urllib.request

from proxylib import Proxy, ProxyMapHandler, SimpleProxyMap


def test_proxymaphandler_injects_resolved_proxy():
    proxymap = SimpleProxyMap(Proxy.from_str("http://proxy.example.com:8080"))
    handler = ProxyMapHandler(proxymap)

    req = urllib.request.Request("http://example.com/foo")
    result = handler.http_open(req)

    assert result is None  # falls through to the default (now-proxying) handler
    assert req.host == "proxy.example.com:8080"


def test_proxymaphandler_direct_leaves_request_untouched():
    handler = ProxyMapHandler(SimpleProxyMap("DIRECT"))

    req = urllib.request.Request("http://example.com/foo")
    result = handler.http_open(req)

    assert result is None
    assert req.host == "example.com"


def test_proxymaphandler_https_open_injects_resolved_proxy():
    # https doesn't take the request-type-mismatch recursion path (it always
    # returns None to let the same handler chain continue, tunneling via
    # CONNECT), so this is directly exercisable without a registered opener.
    proxymap = SimpleProxyMap(Proxy.from_str("http://proxy.example.com:8080"))
    handler = ProxyMapHandler(proxymap)

    req = urllib.request.Request("https://example.com/foo")
    result = handler.https_open(req)

    assert result is None
    assert req.host == "proxy.example.com:8080"


def test_proxymaphandler_ftp_open_is_same_resolver_as_http_open():
    # ftp with a mismatched proxy scheme recurses through self.parent.open(),
    # which needs a real registered opener (and would attempt a real
    # connection) -- out of scope here. Just confirm the three protocol
    # hooks share the same resolution logic.
    proxymap = SimpleProxyMap(Proxy.from_str("http://proxy.example.com:8080"))
    handler = ProxyMapHandler(proxymap)

    assert handler.ftp_open.__func__ is handler.http_open.__func__
    assert handler.https_open.__func__ is handler.http_open.__func__


def test_proxymaphandler_uses_full_url_not_just_scheme(monkeypatch):
    calls = []

    class RecordingProxyMap:
        def get(self, url, default=None):
            calls.append(url)
            return [Proxy.from_str("http://proxy:8080")]

    handler = ProxyMapHandler(RecordingProxyMap())
    req = urllib.request.Request("http://example.com/some/path?query=1")
    handler.http_open(req)

    assert calls == ["http://example.com/some/path?query=1"]


def test_proxymaphandler_does_not_shadow_methods_with_env_proxies(monkeypatch):
    # ProxyHandler.__init__(proxies=None) defaults to getproxies() and would
    # setattr per-protocol instance methods that shadow ours -- make sure
    # constructing with an env HTTP_PROXY set doesn't break this.
    monkeypatch.setenv("HTTP_PROXY", "http://from-env:9999")
    proxymap = SimpleProxyMap(Proxy.from_str("http://from-proxymap:8080"))
    handler = ProxyMapHandler(proxymap)

    req = urllib.request.Request("http://example.com/foo")
    handler.http_open(req)

    assert req.host == "from-proxymap:8080"


def test_proxymaphandler_build_opener_installs_handler():
    proxymap = SimpleProxyMap("DIRECT")
    opener = urllib.request.build_opener(ProxyMapHandler(proxymap))
    assert any(isinstance(h, ProxyMapHandler) for h in opener.handlers)
