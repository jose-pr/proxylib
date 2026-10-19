"""`libproxy <https://libproxy.github.io/libproxy/>`_, the desktop-independent
resolver on Linux, through ``ctypes`` bindings to its C API. It reads the
desktop's settings and runs PAC and WPAD itself, per URL."""

from __future__ import annotations

import ctypes
import threading
from ctypes.util import find_library
from typing import Optional, Tuple

from ...proxy import Proxy, ProxyMap

__all__ = ("LibProxyMap",)


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


# Loaded on first use, so importing proxylib never searches the linker path;
# tests set _libproxy directly.
_UNLOADED = object()
_libproxy: "Optional[ctypes.CDLL]" = _UNLOADED  # type: ignore[assignment]


def _get_libproxy() -> "Optional[ctypes.CDLL]":
    global _libproxy
    if _libproxy is _UNLOADED:
        _libproxy = _load_libproxy()
    return _libproxy


class LibProxyMap(ProxyMap):
    """A proxy map answered by libproxy (``px_proxy_factory_get_proxies``).

    ``lib`` is the loaded library; by default it is found on the linker path.
    When libproxy is not installed, or cannot answer, a lookup has no opinion
    (``KeyError``) rather than DIRECT.

    One libproxy factory, made on the first lookup, serves every lookup so
    its PAC and settings caches are reused; :meth:`close` releases it
    (garbage collection does too).
    """

    __slots__ = ("_lib", "_factory", "_lock")

    def __init__(self, lib: "Optional[ctypes.CDLL]" = None) -> None:
        self._lib = lib if lib is not None else _get_libproxy()
        self._factory = None
        self._lock = threading.Lock()

    def close(self) -> None:
        with self._lock:
            factory, self._factory = self._factory, None
        if factory and self._lib is not None:
            self._lib.px_proxy_factory_free(factory)

    def __del__(self) -> None:
        try:
            self.close()
        except AttributeError:  # __init__ did not finish
            pass

    def __getitem__(self, uri: str) -> "Tuple[Optional[Proxy], ...]":
        lib = self._lib
        if lib is None:
            raise KeyError(uri)

        with self._lock:
            if not self._factory:
                self._factory = lib.px_proxy_factory_new()
            if not self._factory:
                raise KeyError(uri)
            proxies_array = lib.px_proxy_factory_get_proxies(self._factory, uri.encode("utf-8"))
        if not proxies_array:
            # libproxy failed to answer, which is not a DIRECT decision.
            raise KeyError(uri)
        try:
            results: "list[Optional[Proxy]]" = []
            i = 0
            while proxies_array[i] is not None:
                entry = proxies_array[i].decode("utf-8")
                results.append(None if entry.startswith("direct://") else Proxy.parse(entry))
                i += 1
            return tuple(results) or (None,)
        finally:
            lib.px_proxy_factory_free_proxies(proxies_array)

