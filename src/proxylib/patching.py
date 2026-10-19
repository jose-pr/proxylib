"""Wire proxy maps into HTTP clients: ``requests`` and ``urllib.request``
built in, others through :func:`register_patcher`.

Each client gets proxylib's integration once, when proxylib and the client
are both imported (with the ``proxylib[patch]`` extra, whenever the client is
imported, in any program). The integration asks a map that stands for "the
active map": the newest :func:`patch` that covers the client, else the
default. The default has no opinion, so a client behaves exactly as it would
without proxylib; with ``PROXYLIB_AUTO_PATCH=1`` it is :func:`auto_proxy`, and
with ``PROXYLIB_AUTO_PATCH=0`` nothing is installed until :func:`patch` is
called.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import threading
import warnings
from typing import Callable, Dict, FrozenSet, Iterable, List, NamedTuple, Optional, Tuple

from . import _importhook
from .exceptions import MissingExtraError
from .proxy import Proxy, ProxyMap, lookup

__all__ = ("Patch", "active", "patch", "register_patcher", "targets", "unpatch")

InstallFunc = Callable[[ProxyMap], None]
UninstallFunc = Callable[[], None]

_TRUE = ("1", "true", "yes", "on")
_FALSE = ("0", "false", "no", "off")


class _Target(NamedTuple):
    module: str
    install: InstallFunc
    uninstall: UninstallFunc


_lock = threading.RLock()
_registry: "Dict[str, _Target]" = {}
_installed: "set[str]" = set()
_hooked: "set[str]" = set()
_frames: "List[Patch]" = []
_default: "Optional[ProxyMap]" = None


def _mode() -> str:
    """``PROXYLIB_AUTO_PATCH``: ``"auto"`` (true), ``"off"`` (false) or
    ``"default"`` (unset or empty)."""
    value = os.environ.get("PROXYLIB_AUTO_PATCH", "").strip().lower()
    if value in _TRUE:
        return "auto"
    if value in _FALSE:
        return "off"
    if value:
        warnings.warn(
            f"PROXYLIB_AUTO_PATCH={value!r} is not a boolean (1/0, true/false, yes/no, on/off); ignored",
            stacklevel=3,
        )
    return "default"


class _NoOpinion:
    """The default map: every lookup has no opinion, so the client decides."""

    __slots__ = ()

    def __repr__(self) -> str:
        return "<no proxylib opinion>"

    def __getitem__(self, url: str) -> "Tuple[Optional[Proxy], ...]":
        raise KeyError(url)


class _AutoProxy:
    """``auto_proxy()``, built on the first lookup."""

    __slots__ = ("_map", "_lock")

    def __init__(self) -> None:
        self._map: "Optional[ProxyMap]" = None
        self._lock = threading.Lock()

    def __repr__(self) -> str:
        return "<auto_proxy()>"

    def __getitem__(self, url: str) -> "Tuple[Optional[Proxy], ...]":
        if self._map is None:
            with self._lock:
                if self._map is None:
                    from .system import auto_proxy

                    self._map = auto_proxy()
        return lookup(self._map, url)


def _default_map() -> ProxyMap:
    global _default
    with _lock:
        if _default is None:
            _default = _AutoProxy() if _mode() == "auto" else _NoOpinion()
        return _default


class _ActiveMap:
    """What an installed client asks: the newest patch covering it, else the
    default map."""

    __slots__ = ("target",)

    def __init__(self, target: str) -> None:
        self.target = target

    def __repr__(self) -> str:
        return f"<active proxy map for {self.target}>"

    def __getitem__(self, url: str) -> "Tuple[Optional[Proxy], ...]":
        return lookup(active(self.target), url)


def active(target: str) -> ProxyMap:
    """The map ``target``'s client uses now."""
    with _lock:
        for handle in reversed(_frames):
            if handle.targets is None or target in handle.targets:
                return handle.proxymap
    return _default_map()


def _install(name: str) -> None:
    with _lock:
        if name in _installed or name not in _registry:
            return
        try:
            _registry[name].install(_ActiveMap(name))
        except ImportError:
            return  # the client cannot be imported here
        except Exception as exc:
            # A client that is not what the integration expects must not
            # break the program's import of it.
            warnings.warn(f"proxylib could not patch {name}: {exc!r}", RuntimeWarning, stacklevel=2)
            return
        _installed.add(name)


def _on_import(module_name: str) -> None:
    """Install every target whose client is ``module_name``."""
    if _mode() == "off" and not _frames:
        return
    for name, target in list(_registry.items()):
        if target.module == module_name:
            _install(name)


def _install_ready() -> None:
    """Install every target whose client is fully imported. An install
    attempted while proxylib itself was still being imported (from a hook on
    a module proxylib imports) fails and is retried here."""
    if _mode() == "off" and not _frames:
        return
    for name, target in list(_registry.items()):
        module = sys.modules.get(target.module)
        if module is not None and not getattr(getattr(module, "__spec__", None), "_initializing", False):
            _install(name)


def _hook(name: str) -> None:
    """Install ``name`` now if its client is imported, else when it is."""
    with _lock:
        if name in _hooked:
            return
        _hooked.add(name)
        module = _registry[name].module
    _importhook.when_imported(module, _on_import)


class Patch:
    """A :func:`patch` in effect. :meth:`undo`, or leaving its ``with`` block,
    makes the map active before it active again."""

    __slots__ = ("proxymap", "targets")

    def __init__(self, proxymap: ProxyMap, targets: "Optional[FrozenSet[str]]") -> None:
        self.proxymap = proxymap
        self.targets = targets

    def __repr__(self) -> str:
        targets = "all" if self.targets is None else sorted(self.targets)
        return f"<Patch {self.proxymap!r} for {targets}>"

    @property
    def active(self) -> bool:
        with _lock:
            return self in _frames

    def undo(self) -> None:
        """End this patch. Patches end newest first: undoing one that a later
        patch still covers raises ``RuntimeError``. Undoing an ended patch
        does nothing."""
        with _lock:
            if self not in _frames:
                return
            if _frames[-1] is not self:
                raise RuntimeError("patches are undone newest first; a later patch is still in effect")
            _frames.pop()

    def __enter__(self) -> "Patch":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.undo()


def patch(proxymap: ProxyMap, *, targets: "Optional[Iterable[str]]" = None) -> Patch:
    """Make ``proxymap`` the map of every client in ``targets`` (default: all
    registered), until the returned :class:`Patch` is undone or
    :func:`unpatch` is called. Patches nest: the newest wins.

    A named target whose client is not installed raises
    :class:`MissingExtraError`; with the default, such clients are skipped.
    An unknown name raises ``ValueError``.
    """
    names = None if targets is None else frozenset(targets)
    for name in names or ():
        if name not in _registry:
            raise ValueError(f"no patch target {name!r}; registered: {tuple(_registry)}")
        top = _registry[name].module.partition(".")[0]
        if sys.modules.get(top) is None and importlib.util.find_spec(top) is None:
            raise MissingExtraError(f"the {name} patch target", name=top)
    handle = Patch(proxymap, names)
    with _lock:
        _frames.append(handle)
    for name in names if names is not None else list(_registry):
        if names is not None:
            importlib.import_module(_registry[name].module)
        _hook(name)
    return handle


def unpatch() -> None:
    """End every patch: each client is back on the default map."""
    with _lock:
        _frames.clear()


def register_patcher(
    name: str,
    install: InstallFunc,
    uninstall: UninstallFunc,
    *,
    module: str,
    replace: bool = False,
) -> None:
    """Register a client integration. ``install(proxymap)`` is called once,
    when ``module`` (the client) has been imported, with a map that always
    answers as the active map does; ``uninstall()`` removes it. An existing
    ``name`` raises ``ValueError`` unless ``replace=True``."""
    with _lock:
        if name in _registry and not replace:
            raise ValueError(f"patch target {name!r} is already registered")
        _registry[name] = _Target(module, install, uninstall)
        _hooked.discard(name)
    if _mode() != "off":
        _hook(name)


def targets() -> "Tuple[str, ...]":
    """The registered patch targets."""
    with _lock:
        return tuple(_registry)



def _uninstall() -> None:
    """Remove every installed integration and end every patch."""
    with _lock:
        for name in list(_installed):
            _registry[name].uninstall()
        _installed.clear()
        _frames.clear()


# ---- built-in targets ---------------------------------------------------------

_requests_init: "Optional[Callable]" = None


def _install_requests(proxymap: ProxyMap) -> None:
    global _requests_init
    # requests.sessions, not requests: the package is still initialising when
    # its own imports (urllib.request) load proxylib, and Session comes last.
    import requests.sessions as sessions

    original = sessions.Session.__init__

    def __init__(self, *args, **kwargs):
        from .integrations.requests import ProxyMapAdapter

        original(self, *args, **kwargs)
        self.mount("https://", ProxyMapAdapter(proxymap))
        self.mount("http://", ProxyMapAdapter(proxymap))

    __init__.__wrapped__ = original  # type: ignore[attr-defined]
    _requests_init = original
    sessions.Session.__init__ = __init__


def _uninstall_requests() -> None:
    global _requests_init
    if _requests_init is not None:
        import requests.sessions as sessions

        sessions.Session.__init__ = _requests_init
        _requests_init = None


_urllib_opener = None


def _install_urllib(proxymap: ProxyMap) -> None:
    global _urllib_opener
    import urllib.request as urllib_request

    from .integrations.urllib import ProxyMapHandler

    # A program that installed its own opener decides for urllib itself.
    if urllib_request._opener is not None:
        return
    _urllib_opener = urllib_request.build_opener(ProxyMapHandler(proxymap))
    urllib_request.install_opener(_urllib_opener)


def _uninstall_urllib() -> None:
    global _urllib_opener
    import urllib.request as urllib_request

    if _urllib_opener is not None and urllib_request._opener is _urllib_opener:
        urllib_request.install_opener(None)
    _urllib_opener = None


register_patcher("requests", _install_requests, _uninstall_requests, module="requests.sessions")
register_patcher("urllib", _install_urllib, _uninstall_urllib, module="urllib.request")
