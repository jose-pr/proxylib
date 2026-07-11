import urllib.request

import pytest

import proxylib.patching as patching
from proxylib import Proxy, SimpleProxyMap, patch, register_patcher, unpatch


@pytest.fixture(autouse=True)
def clean_patch_state():
    # register_patcher() mutates the shared module-level registry -- save
    # and restore it (not just unpatch()) so a test's fake registrations
    # (e.g. "fake", "target-a") don't leak into later tests' default
    # (targets=None -> "every registered target") behavior.
    unpatch()
    original_registry = dict(patching._registry)
    yield
    unpatch()
    patching._registry.clear()
    patching._registry.update(original_registry)


@pytest.fixture
def fake_target():
    calls = {"patch": [], "unpatch": 0}

    def patch_func(proxymap):
        calls["patch"].append(proxymap)

    def unpatch_func():
        calls["unpatch"] += 1

    register_patcher("fake", patch_func, unpatch_func)
    return calls


def test_patch_calls_registered_patch_func(fake_target):
    proxymap = SimpleProxyMap("DIRECT")
    patch(proxymap, targets=["fake"])

    assert fake_target["patch"] == [proxymap]


def test_unpatch_calls_registered_unpatch_func(fake_target):
    patch(SimpleProxyMap("DIRECT"), targets=["fake"])
    unpatch()

    assert fake_target["unpatch"] == 1


def test_unpatch_is_idempotent(fake_target):
    unpatch()
    unpatch()

    assert fake_target["unpatch"] == 0


def test_patch_only_applies_requested_targets():
    calls = {"a": 0, "b": 0}
    register_patcher("target-a", lambda pm: calls.__setitem__("a", calls["a"] + 1), lambda: None)
    register_patcher("target-b", lambda pm: calls.__setitem__("b", calls["b"] + 1), lambda: None)

    patch(SimpleProxyMap("DIRECT"), targets=["target-a"])

    assert calls == {"a": 1, "b": 0}


def test_patch_unknown_target_raises_keyerror():
    with pytest.raises(KeyError):
        patch(SimpleProxyMap("DIRECT"), targets=["does-not-exist"])


def test_patch_partial_failure_rolls_back_already_applied_targets():
    applied = []
    register_patcher("ok", lambda pm: applied.append("ok"), lambda: applied.remove("ok"))

    with pytest.raises(KeyError):
        patch(SimpleProxyMap("DIRECT"), targets=["ok", "does-not-exist"])

    # "ok" was applied then rolled back when "does-not-exist" failed.
    assert applied == []


def test_patch_again_while_active_warns_and_replaces(fake_target):
    first = SimpleProxyMap("DIRECT")
    second = SimpleProxyMap(Proxy.from_str("http://p:80"))
    patch(first, targets=["fake"])

    with pytest.warns(UserWarning, match="already patched"):
        patch(second, targets=["fake"])

    assert fake_target["patch"] == [first, second]
    assert fake_target["unpatch"] == 1  # first patch's undo ran before the second applied


def test_unpatch_runs_in_reverse_order():
    order = []
    register_patcher("first", lambda pm: order.append("patch-first"), lambda: order.append("unpatch-first"))
    register_patcher("second", lambda pm: order.append("patch-second"), lambda: order.append("unpatch-second"))

    patch(SimpleProxyMap("DIRECT"), targets=["first", "second"])
    order.clear()
    unpatch()

    assert order == ["unpatch-second", "unpatch-first"]


# ---- built-in "requests" target -------------------------------------------------

requests = pytest.importorskip("requests")


def test_requests_target_mounts_adapter_on_new_sessions():
    from proxylib.integrations.requests import ProxyMapAdapter

    proxymap = SimpleProxyMap(Proxy.from_str("http://p:80"))
    patch(proxymap, targets=["requests"])

    session = requests.Session()
    try:
        assert isinstance(session.get_adapter("http://example.com"), ProxyMapAdapter)
        assert isinstance(session.get_adapter("https://example.com"), ProxyMapAdapter)
    finally:
        session.close()


def test_requests_target_does_not_affect_pre_existing_sessions():
    from proxylib.integrations.requests import ProxyMapAdapter

    pre_existing = requests.Session()
    try:
        patch(SimpleProxyMap("DIRECT"), targets=["requests"])
        assert not isinstance(pre_existing.get_adapter("http://example.com"), ProxyMapAdapter)
    finally:
        pre_existing.close()


def test_requests_target_unpatch_restores_default_init():
    original_init = requests.Session.__init__
    patch(SimpleProxyMap("DIRECT"), targets=["requests"])
    assert requests.Session.__init__ is not original_init

    unpatch()
    assert requests.Session.__init__ is original_init


# ---- built-in "urllib" target --------------------------------------------------


def test_urllib_target_installs_global_opener():
    from proxylib.integrations.urllib import ProxyMapHandler

    patch(SimpleProxyMap("DIRECT"), targets=["urllib"])

    opener = urllib.request._opener
    assert any(isinstance(h, ProxyMapHandler) for h in opener.handlers)


def test_urllib_target_unpatch_restores_prior_opener():
    prior = urllib.request._opener
    patch(SimpleProxyMap("DIRECT"), targets=["urllib"])
    unpatch()

    assert urllib.request._opener is prior


# ---- ProxyMap context manager --------------------------------------------------


def test_proxymap_context_manager_patches_and_unpatches(fake_target):
    proxymap = SimpleProxyMap("DIRECT")

    with proxymap as active:
        assert active is proxymap
        # __enter__ calls patch(self) with targets=None -- every registered
        # target (including this test's "fake" one) gets applied.
        assert fake_target["patch"] == [proxymap]

    # __exit__ called unpatch() -- nothing left active.
    assert fake_target["unpatch"] == 1
    assert patching._active_map is None
