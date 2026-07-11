"""Extensible patching registry: globally wire an active ``ProxyMap`` into
third-party HTTP clients (``requests``, ``urllib``, ...) without every
caller needing to know each integration's specific mounting API.

Built-in targets: ``"requests"`` (wraps ``requests.Session.__init__`` so
newly created sessions mount a ``ProxyMapAdapter`` for ``http://``/
``https://`` -- sessions created *before* :func:`patch` are untouched) and
``"urllib"`` (installs a global opener via ``urllib.request.install_opener``).
Register your own with :func:`register_patcher`.
"""

from __future__ import annotations

import threading
import warnings
from typing import Callable, Dict, List, Optional, Tuple

from .proxy import ProxyMap

__all__ = ("patch", "unpatch", "register_patcher")

PatchFunc = Callable[[ProxyMap], None]
UnpatchFunc = Callable[[], None]

_lock = threading.Lock()
_active_map: "Optional[ProxyMap]" = None
_active_targets: "List[str]" = []
_registry: "Dict[str, Tuple[PatchFunc, UnpatchFunc]]" = {}


def register_patcher(name: str, patch_func: PatchFunc, unpatch_func: UnpatchFunc) -> None:
    """Register a named integration for :func:`patch`/:func:`unpatch` to drive.

    ``patch_func(proxymap)`` applies the integration; ``unpatch_func()``
    undoes it (no arguments -- capture whatever state you need in a
    closure). Re-registering an existing ``name`` replaces it.
    """
    _registry[name] = (patch_func, unpatch_func)


def patch(proxymap: ProxyMap, targets: "Optional[List[str]]" = None) -> None:
    """Globally wire ``proxymap`` into ``targets`` (default: every registered target).

    Calling this while already patched **replaces** the previous patch
    (with a warning) rather than stacking -- there is one active resolver
    at a time, not a layered set.
    """
    global _active_map, _active_targets
    with _lock:
        if _active_map is not None:
            warnings.warn(
                "proxylib.patch() called while already patched -- replacing "
                "the previous patch instead of stacking.",
                stacklevel=2,
            )
            _unpatch_locked()

        names = list(targets) if targets is not None else list(_registry)
        applied: "List[str]" = []
        try:
            for name in names:
                if name not in _registry:
                    raise KeyError(f"No patcher registered for {name!r}")
                patch_func, _ = _registry[name]
                patch_func(proxymap)
                applied.append(name)
        except BaseException:
            # Partial failure: undo whatever *did* apply before propagating,
            # so a failed patch() doesn't leave a half-patched process.
            for name in reversed(applied):
                _registry[name][1]()
            raise

        _active_map = proxymap
        _active_targets = applied


def _unpatch_locked() -> None:
    global _active_map, _active_targets
    for name in reversed(_active_targets):
        _, unpatch_func = _registry[name]
        unpatch_func()
    _active_map = None
    _active_targets = []


def unpatch() -> None:
    """Undo whatever :func:`patch` last applied, in reverse order.

    Idempotent: calling it when nothing is patched is a no-op.
    """
    with _lock:
        _unpatch_locked()


# ---- built-in targets ---------------------------------------------------------

_requests_original_init: "Optional[Callable]" = None


def _patch_requests(proxymap: ProxyMap) -> None:
    global _requests_original_init
    import requests

    from .integrations.requests import ProxyMapAdapter

    original_init = requests.Session.__init__
    _requests_original_init = original_init

    def patched_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        adapter = ProxyMapAdapter(proxymap)
        self.mount("http://", adapter)
        self.mount("https://", adapter)

    requests.Session.__init__ = patched_init


def _unpatch_requests() -> None:
    global _requests_original_init
    import requests

    if _requests_original_init is not None:
        requests.Session.__init__ = _requests_original_init
        _requests_original_init = None


try:
    import requests as _requests  # noqa: F401

    register_patcher("requests", _patch_requests, _unpatch_requests)
except ImportError:
    pass


_urllib_original_opener = None


def _patch_urllib(proxymap: ProxyMap) -> None:
    global _urllib_original_opener
    import urllib.request

    from .integrations.urllib import ProxyMapHandler

    _urllib_original_opener = urllib.request._opener
    urllib.request.install_opener(urllib.request.build_opener(ProxyMapHandler(proxymap)))


def _unpatch_urllib() -> None:
    global _urllib_original_opener
    import urllib.request

    urllib.request.install_opener(_urllib_original_opener)
    _urllib_original_opener = None


register_patcher("urllib", _patch_urllib, _unpatch_urllib)
