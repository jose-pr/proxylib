"""libproxy integration, via ``ctypes`` bindings to its C API directly
(no subprocess, no non-stdlib dependency).

`libproxy <https://libproxy.github.io/libproxy/>`_ is itself a cross-desktop
proxy-resolution engine -- it already knows how to read GNOME/KDE/env vars/
PAC/WPAD/etc, generally with more fidelity than proxylib's own best-effort
per-desktop probes (:mod:`.gnome`, :mod:`.kde`, ...). When its shared library
is loadable, :mod:`..posix` prefers it over those probes.

Unlike the other backends, this isn't a "read the config once at startup"
detector -- resolution is per-URL, so :class:`LibProxyMap` is its own
:class:`~proxylib.proxy.ProxyMap` implementation that calls into libproxy
fresh for every lookup: a new ``pxProxyFactory`` per call (matching
libproxy's own API contract -- see ``px_proxy_factory_free`` -- and
sidestepping any question of whether a shared factory is safe to reuse
across threads).
"""

from __future__ import annotations

import ctypes
from ctypes.util import find_library
from typing import Iterable, Optional

from ...proxy import Proxy, ProxyMap

__all__ = ("LibProxyMap", "detect")


def _load_libproxy() -> "Optional[ctypes.CDLL]":
    lib_path = find_library("proxy")
    if not lib_path:
        return None
    try:
        lib = ctypes.CDLL(lib_path)
        lib.px_proxy_factory_new.argtypes = []
        lib.px_proxy_factory_new.restype = ctypes.c_void_p
        lib.px_proxy_factory_get_proxies.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        lib.px_proxy_factory_get_proxies.restype = ctypes.POINTER(ctypes.c_char_p)
        lib.px_proxy_factory_free_proxies.argtypes = [ctypes.POINTER(ctypes.c_char_p)]
        lib.px_proxy_factory_free_proxies.restype = None
        lib.px_proxy_factory_free.argtypes = [ctypes.c_void_p]
        lib.px_proxy_factory_free.restype = None
    except (OSError, AttributeError):
        return None
    return lib


# Loaded lazily on first use (and memoized): `import proxylib` shouldn't
# scan the dynamic linker's search paths on platforms where libproxy will
# never exist. Tests monkeypatch `_libproxy` directly, which takes
# precedence over the lazy load.
_UNLOADED = object()
_libproxy: "Optional[ctypes.CDLL]" = _UNLOADED  # type: ignore[assignment]


def _get_libproxy() -> "Optional[ctypes.CDLL]":
    global _libproxy
    if _libproxy is _UNLOADED:
        _libproxy = _load_libproxy()
    return _libproxy


class LibProxyMap(ProxyMap):
    """Resolves each request URL via libproxy's C API.

    Construct with no arguments to use the auto-detected shared library;
    ``__getitem__`` raises ``KeyError`` (like any other resolution failure)
    if libproxy isn't available, rather than erroring at construction time.
    """

    __slots__ = ("_lib",)

    def __init__(self, lib: "Optional[ctypes.CDLL]" = None) -> None:
        self._lib = lib if lib is not None else _get_libproxy()

    def __getitem__(self, uri: str) -> "Iterable[Optional[Proxy]]":
        lib = self._lib
        if lib is None:
            raise KeyError(uri)

        factory = lib.px_proxy_factory_new()
        if not factory:
            raise KeyError(uri)
        try:
            proxies_array = lib.px_proxy_factory_get_proxies(factory, uri.encode("utf-8"))
            if not proxies_array:
                return [None]
            try:
                results: "list[Optional[Proxy]]" = []
                i = 0
                while proxies_array[i] is not None:
                    entry = proxies_array[i].decode("utf-8")
                    results.append(
                        None if entry.startswith("direct://") else Proxy.from_str(entry)
                    )
                    i += 1
                return results or [None]
            finally:
                lib.px_proxy_factory_free_proxies(proxies_array)
        finally:
            lib.px_proxy_factory_free(factory)


def detect() -> "Optional[LibProxyMap]":
    lib = _get_libproxy()
    return LibProxyMap(lib) if lib is not None else None
