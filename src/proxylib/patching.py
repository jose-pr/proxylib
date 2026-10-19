"""Wire proxy maps into HTTP clients: ``requests``, ``urllib``, ``httpx`` and
``aiohttp`` built in, others through :func:`register_patcher`.

Each client gets proxylib's integration once, when it is imported, in any
program of the environment: proxylib's ``importpatch`` entry points run at
interpreter start, and importing proxylib registers the same hooks. The
integration asks the client's *active map*: the newest :func:`patch` that
covers it, else its default.

``PROXYLIB_IMPORTPATCH`` chooses the defaults, as syshttp's
``SYSHTTP_IMPORTPATCH`` does: ``1``/``true``/``yes``/``on`` for every target,
or target names separated by commas or spaces (``requests, httpx``; a client's
module name, such as ``urllib.request``, works too). A named target's default is
:func:`~proxylib.auto_proxy`. Unset or empty, nothing is named: ``requests`` and
``urllib`` still get the integration, with a default that has no opinion, so
they choose their proxy exactly as without proxylib; ``httpx`` and
``aiohttp``, whose integration would change that, get none.
``0``/``false``/``no``/``off`` installs nothing until :func:`patch` is called.
"""

from __future__ import annotations

import importlib.util
import os
import re
import sys
import threading
import warnings
from typing import Callable, Dict, FrozenSet, Iterable, List, NamedTuple, Optional, Tuple

import importpatch

from .exceptions import MissingExtraError
from .proxy import Proxy, ProxyMap, lookup

__all__ = ("Patch", "active", "patch", "register_patcher", "targets", "unpatch")

InstallFunc = Callable[[ProxyMap], None]
UninstallFunc = Callable[[], None]

_SETTING = "PROXYLIB_IMPORTPATCH"
# The importpatch patcher (also proxylib's entry point); it calls _on_import.
_AUTOPATCH = "proxylib.integrations.autopatch"
_TRUE = ("1", "true", "yes", "on")
_FALSE = ("0", "false", "no", "off")


class _Target(NamedTuple):
    module: str
    install: InstallFunc
    uninstall: UninstallFunc
    # Installed without being named: its integration keeps the client's own
    # behaviour under a default with no opinion.
    unnamed: bool


_lock = threading.RLock()
_registry: "Dict[str, _Target]" = {}
_installed: "set[str]" = set()
_hooked: "set[str]" = set()
_frames: "List[Patch]" = []


class _Setting(NamedTuple):
    off: bool
    named: "FrozenSet[str]"


def _setting() -> _Setting:
    """``PROXYLIB_IMPORTPATCH``, read when a client is imported."""
    raw = os.environ.get(_SETTING, "").strip()
    if raw.lower() in _FALSE:
        return _Setting(True, frozenset())
    if raw.lower() in _TRUE:
        return _Setting(False, frozenset(_registry))
    by_module = {target.module: name for name, target in _registry.items()}
    by_module["urllib.request"] = "urllib"
    names = set()
    for part in re.split(r"[\s,]+", raw):
        if not part:
            continue
        name = by_module.get(part, part)
        if name in _registry:
            names.add(name)
        else:
            warnings.warn(f"{_SETTING} names {part!r}, which is not one of {', '.join(_registry)}", stacklevel=3)
    return _Setting(False, frozenset(names))


class _NoOpinion:
    """The default of a target not named: every lookup has no opinion, so the
    client decides."""

    __slots__ = ()

    def __repr__(self) -> str:
        return "<no proxylib opinion>"

    def __getitem__(self, url: str) -> "Tuple[Optional[Proxy], ...]":
        raise KeyError(url)


class _AutoProxy:
    """``auto_proxy()``, built on the first lookup; shared by every named
    target."""

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


_NO_OPINION = _NoOpinion()
_AUTO_PROXY = _AutoProxy()


def _default_map(target: str) -> ProxyMap:
    return _AUTO_PROXY if target in _setting().named else _NO_OPINION


class _ActiveMap:
    """What an installed client asks: the newest patch covering it, else its
    default."""

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
    return _default_map(target)


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


def _wanted(name: str) -> bool:
    """Whether ``name`` is installed when its client is imported."""
    with _lock:
        if any(handle.targets is None or name in handle.targets for handle in _frames):
            return True
    setting = _setting()
    return not setting.off and (_registry[name].unnamed or name in setting.named)


def _on_import(module_name: str) -> None:
    """Install every wanted target whose client is ``module_name``."""
    for name, target in list(_registry.items()):
        if target.module == module_name and _wanted(name):
            _install(name)


def _install_ready() -> None:
    """Install every wanted target whose client is fully imported. An install
    attempted while proxylib itself was still being imported (from a hook on
    a module proxylib imports) fails and is retried here."""
    for name, target in list(_registry.items()):
        module = sys.modules.get(target.module)
        if module is None or getattr(getattr(module, "__spec__", None), "_initializing", False):
            continue
        if _wanted(name):
            _install(name)


def _hook(name: str) -> None:
    """Install ``name`` now if its client is imported, else when it is."""
    with _lock:
        if name in _hooked:
            return
        _hooked.add(name)
        module = _registry[name].module
    # importpatch runs it at once when the client is already imported.
    importpatch.add(module, _AUTOPATCH)


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
    # Clients already imported, which the hook saw before this patch wanted them.
    _install_ready()
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
    unnamed: bool = False,
    replace: bool = False,
) -> None:
    """Register a client integration. ``install(proxymap)`` is called once,
    when ``module`` (the client) has been imported and the target is wanted
    (named in ``PROXYLIB_IMPORTPATCH``, patched from code, or ``unnamed=True``:
    an integration that keeps the client's own behaviour while its map has no
    opinion), with a map that always answers as the active map does;
    ``uninstall()`` removes it. An existing ``name`` raises ``ValueError``
    unless ``replace=True``."""
    with _lock:
        if name in _registry and not replace:
            raise ValueError(f"patch target {name!r} is already registered")
        _registry[name] = _Target(module, install, uninstall, unnamed)
        _hooked.discard(name)
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


_httpx_inits: "List[Tuple[type, Callable]]" = []


def _install_httpx(proxymap: ProxyMap) -> None:
    """``httpx.Client`` and ``AsyncClient`` made without ``transport``,
    ``proxy``, ``proxies`` or ``mounts`` get a proxylib transport over the
    active map; ``verify``, ``cert``, ``http1``, ``http2``, ``limits`` and
    ``trust_env`` go to its inner transports."""
    import httpx

    from .integrations.httpx import AsyncProxyTransport, ProxyTransport

    for client_class, transport_class in ((httpx.Client, ProxyTransport), (httpx.AsyncClient, AsyncProxyTransport)):
        original = client_class.__init__

        def __init__(self, *args, __original=original, __transport=transport_class, **kwargs):
            if not any(kwargs.get(key) is not None for key in ("transport", "proxy", "proxies", "mounts")):
                inner = {k: kwargs[k] for k in ("verify", "cert", "http1", "http2", "limits", "trust_env") if k in kwargs}
                kwargs["transport"] = __transport(proxymap, **inner)
            __original(self, *args, **kwargs)

        __init__.__wrapped__ = original  # type: ignore[attr-defined]
        client_class.__init__ = __init__
        _httpx_inits.append((client_class, original))


def _uninstall_httpx() -> None:
    while _httpx_inits:
        client_class, original = _httpx_inits.pop()
        client_class.__init__ = original


_aiohttp_request: "Optional[Callable]" = None


def _install_aiohttp(proxymap: ProxyMap) -> None:
    """``ClientSession`` requests take ``proxy=`` from the active map, with
    failover; a proxy URL the caller gives is aiohttp's own."""
    global _aiohttp_request
    import aiohttp

    from .integrations.aiohttp import _routed

    original = aiohttp.ClientSession._request

    async def _request(self, method, str_or_url, **kwargs):
        async def send(**proxy_kwargs):
            return await original(self, method, str_or_url, **{**kwargs, **proxy_kwargs})

        return await _routed(send, proxymap, str(str_or_url), kwargs.pop("proxy", None))

    _request.__wrapped__ = original  # type: ignore[attr-defined]
    _aiohttp_request = original
    aiohttp.ClientSession._request = _request


def _uninstall_aiohttp() -> None:
    global _aiohttp_request
    if _aiohttp_request is not None:
        import aiohttp

        aiohttp.ClientSession._request = _aiohttp_request
        _aiohttp_request = None


register_patcher("requests", _install_requests, _uninstall_requests, module="requests.sessions", unnamed=True)
register_patcher("urllib", _install_urllib, _uninstall_urllib, module="urllib.request", unnamed=True)
register_patcher("httpx", _install_httpx, _uninstall_httpx, module="httpx")
register_patcher("aiohttp", _install_aiohttp, _uninstall_aiohttp, module="aiohttp")
