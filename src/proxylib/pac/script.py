"""``PacScript``: one PAC script running in its own JavaScript engine."""

from __future__ import annotations

import os
import pickle
import queue
import subprocess
import sys
import threading
import time
import warnings
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Optional, Tuple, Union
from urllib.request import ProxyHandler, build_opener

from .. import _net
from ..exceptions import MissingExtraError, PACError
from . import _child, engines

__all__ = ("PacScript", "MAX_PAC_BYTES")

# A PAC fetch never goes through a configured proxy, as in browsers: the
# proxy may be what the PAC is about to choose, and a local proxy that points
# the environment at itself would make the fetch recurse.
_urlopen = build_opener(ProxyHandler({})).open

# Chromium's PAC fetcher limit.
MAX_PAC_BYTES = 1024 * 1024
# Memory cap for engines that support one (quickjs).
_MEMORY_LIMIT = 64 * 1024 * 1024
# Seconds a dukpy helper process may take to start and load the script, on
# top of the script's own budget.
_CHILD_START_TIMEOUT = 30.0

# Seconds an overrun script answers PACError at once before it is started
# afresh: a hostile script costs one budget per cool-down, not one per call,
# and a script that stalled once (slow DNS) recovers.
_COOLDOWN = 30.0

# url -> (monotonic timestamp, script text) for downloaded scripts.
_download_cache: "Dict[str, Tuple[float, str]]" = {}


@_net.register_cache
def _clear_download_cache() -> None:
    _download_cache.clear()


class _Overrun(Exception):
    """The script ran past its budget; the runner cannot be used again."""


class _Runner:
    """A script's engine in a helper process (``pac._child``), killed on
    overrun. Neither engine can be stopped from inside this process: dukpy
    holds the GIL while it runs, and quickjs's time limit forbids the Python
    builtins."""

    def __init__(self, engine: str, source: str, extra: "Mapping[str, Callable]", timeout: float) -> None:
        self.timeout = timeout
        try:
            pickle.dumps(dict(extra))
        except Exception as exc:
            raise TypeError(
                "functions= must be picklable: module-level functions the "
                "PAC helper process can import"
            ) from exc
        package_root = str(Path(__file__).resolve().parents[2])
        env = dict(os.environ)
        env["PYTHONPATH"] = os.pathsep.join(p for p in (package_root, env.get("PYTHONPATH")) if p)
        self._proc = subprocess.Popen(
            [sys.executable, "-c", "from proxylib.pac._child import main; main()"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            env=env,
        )
        self._replies: "queue.Queue" = queue.Queue()
        threading.Thread(target=self._read, name="proxylib-pac-child", daemon=True).start()
        self._lock = threading.Lock()
        try:
            self._wait_reply(_CHILD_START_TIMEOUT)  # "ready": the helper has imported its engine
            self._request(("init", engine, source, dict(extra), _MEMORY_LIMIT), timeout)
        except BaseException:
            # The caller never gets this runner to close: end the helper here.
            self.close()
            raise

    def _read(self) -> None:
        stdout = self._proc.stdout
        while True:
            try:
                message = _child.read_frame(stdout)  # type: ignore[arg-type]
            except Exception:
                message = None
            self._replies.put(message)
            if message is None:
                return

    def _request(self, message: Any, timeout: float) -> Any:
        with self._lock:
            try:
                _child.write_frame(self._proc.stdin, message)  # type: ignore[arg-type]
            except (OSError, ValueError) as exc:  # ValueError: the pipe was closed
                raise PACError(f"the PAC helper process is gone: {exc}") from exc
            return self._wait_reply(timeout)

    def _wait_reply(self, timeout: float) -> Any:
        try:
            reply = self._replies.get(timeout=timeout)
        except queue.Empty:
            self.close()
            raise _Overrun() from None
        if reply is None:
            raise PACError("the PAC helper process exited")
        status, value = reply
        if status != "ok":
            raise PACError(f"the PAC script raised: {value}")
        return value

    def call(self, url: str, host: str) -> Any:
        return self._request(("call", url, host), self.timeout)

    def close(self) -> None:
        proc = getattr(self, "_proc", None)
        if proc is None:
            return
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        for pipe in (proc.stdin, proc.stdout):
            if pipe is not None:
                pipe.close()


class PacScript:
    """A PAC script, ready to answer ``FindProxyForURL``.

    ``source`` is the script text. ``engine`` names the JS engine (default:
    ``PROXYLIB_JS_ENGINE``, else quickjs, else dukpy; see
    :mod:`proxylib.pac.engines`). ``functions`` adds to or overrides the PAC
    builtins the script can call; the script runs in a helper process, so
    they must be picklable module-level functions it can import.
    ``timeout`` bounds each call in seconds (the builtins' own DNS lookups are
    bounded at 2 s each): a call that overruns raises :class:`PACError`, its
    helper process is ended, and for the next 30 seconds every call raises
    :class:`PACError` at once; after that the script is started afresh. A
    script that overruns while loading is not loaded.

    With no engine installed, ``on_missing_engine="raise"`` (the default)
    raises :class:`MissingExtraError`; ``"direct"`` warns and the script
    answers ``"DIRECT"`` to everything.

    A script error, a script that does not define ``FindProxyForURL`` and an
    overrun all raise :class:`PACError`. Safe to share between threads; calls
    are serialised. ``close()`` releases the engine (garbage collection does
    too).
    """

    def __init__(
        self,
        source: str,
        *,
        engine: "Optional[str]" = None,
        functions: "Optional[Mapping[str, Callable[..., Any]]]" = None,
        timeout: float = 5.0,
        on_missing_engine: str = "raise",
    ) -> None:
        if on_missing_engine not in ("raise", "direct"):
            raise ValueError("on_missing_engine must be 'raise' or 'direct'")
        if "FindProxyForURL" not in source:
            raise PACError("the script defines no FindProxyForURL")
        self.source = source
        self.timeout = timeout
        self.engine_name: "Optional[str]" = None
        self._failed: "Optional[str]" = None
        self._retry_at = 0.0
        self._functions = dict(functions or {})
        self._restart_lock = threading.Lock()
        self._runner: "Optional[_Runner]" = None

        engine_cls = engines.get_engine(engine)
        if engine_cls is None:
            if on_missing_engine == "raise":
                raise MissingExtraError("Running a PAC script", name="quickjs", extra="pac")
            warnings.warn(
                'no PAC JavaScript engine is installed (pip install "proxylib[pac]" '
                'or "proxylib[dukpy]"); this PAC answers DIRECT to everything',
                stacklevel=2,
            )
            return
        self.engine_name = engine_cls.name
        try:
            self._runner = _Runner(engine_cls.name, source, self._functions, timeout)
        except _Overrun:
            raise PACError(f"the PAC script ran longer than {timeout} s while loading") from None

    def __del__(self) -> None:
        self.close()

    def close(self) -> None:
        runner = getattr(self, "_runner", None)
        if runner is not None:
            runner.close()

    def __repr__(self) -> str:
        state = "failed" if self._failed else (self.engine_name or "no engine")
        return f"<PacScript {state}, {len(self.source)} chars>"

    def find_proxy_for_url(self, url: str, host: str) -> str:
        """Run ``FindProxyForURL(url, host)``. A result that is not a string
        is ``"DIRECT"``, as browsers treat it."""
        if self._runner is None:
            return "DIRECT"
        if self._failed:
            self._restart()
        runner = self._runner
        try:
            result = runner.call(url, host)
        except _Overrun:
            self._failed = f"it ran longer than {self.timeout} s"
            self._retry_at = time.monotonic() + _COOLDOWN
            runner.close()
            raise PACError(f"the PAC script ran longer than {self.timeout} s") from None
        return result if isinstance(result, str) else "DIRECT"

    def _restart(self) -> None:
        with self._restart_lock:
            if not self._failed:
                return  # another thread restarted it
            if time.monotonic() < self._retry_at:
                raise PACError(f"the PAC script failed earlier: {self._failed}")
            try:
                self._runner = _Runner(self.engine_name, self.source, self._functions, self.timeout)
            except _Overrun:
                self._retry_at = time.monotonic() + _COOLDOWN
                raise PACError(f"the PAC script ran longer than {self.timeout} s") from None
            self._failed = None

    @classmethod
    def from_file(
        cls, path: "Union[str, os.PathLike]", *, encoding: str = "utf-8-sig", **options: Any
    ) -> "PacScript":
        """Read a script from a file. ``options`` are those of ``PacScript``."""
        return cls(Path(path).read_text(encoding=encoding), **options)

    @classmethod
    def from_url(
        cls,
        url: str,
        *,
        timeout: float = 10.0,
        max_bytes: int = MAX_PAC_BYTES,
        cache_ttl: "Optional[float]" = 300.0,
        **options: Any,
    ) -> "PacScript":
        """Download a script, never through a proxy. ``timeout`` bounds the
        download; a body over ``max_bytes`` raises :class:`PACError`. A
        ``file://`` URL is read directly and never cached; downloaded text is
        kept for ``cache_ttl`` seconds (``0``/``None``: no cache). ``options``
        are those of ``PacScript``, whose ``timeout`` is spelled
        ``script_timeout`` here.
        """
        if "script_timeout" in options:
            options["timeout"] = options.pop("script_timeout")
        return cls(_fetch(url, timeout=timeout, max_bytes=max_bytes, cache_ttl=cache_ttl), **options)


def _fetch(url: str, *, timeout: float, max_bytes: int, cache_ttl: "Optional[float]") -> str:
    network = not url.lower().startswith("file:")
    if network and cache_ttl:
        cached = _download_cache.get(url)
        if cached is not None and time.monotonic() - cached[0] < cache_ttl:
            return cached[1]
    with _urlopen(url, timeout=timeout) as response:
        body = response.read(max_bytes + 1)
    if len(body) > max_bytes:
        raise PACError(f"the PAC script at {url} is larger than {max_bytes} bytes")
    try:
        text = body.decode("utf-8-sig")
    except UnicodeDecodeError:
        # Latin-1 maps every byte, so a legacy-encoded script still loads.
        text = body.decode("latin-1")
    if network and cache_ttl:
        _download_cache[url] = (time.monotonic(), text)
    return text
