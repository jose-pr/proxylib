"""The one way the system backends run a program (``scutil``, ``gsettings``,
``nmcli``, ``dbus-send``): resolved on ``PATH`` once, no stdin, the C locale,
a time limit, and ``None`` instead of an exception on any failure.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from typing import Dict, List, Optional

from .. import _net

__all__ = ("log", "run", "which")

log = logging.getLogger("proxylib.system")

# name -> resolved path, or None when the program is not installed.
_which_cache: "Dict[str, Optional[str]]" = {}


@_net.register_cache
def clear_which_cache() -> None:
    _which_cache.clear()


def which(name: str) -> "Optional[str]":
    if name not in _which_cache:
        _which_cache[name] = shutil.which(name)
    return _which_cache[name]


def run(argv: "List[str]", *, timeout: float = 5.0) -> "Optional[str]":
    """``argv``'s standard output, or ``None`` when the program is missing,
    fails, or runs longer than ``timeout`` seconds."""
    program = which(argv[0])
    if program is None:
        log.debug("%s is not installed", argv[0])
        return None
    try:
        result = subprocess.run(
            [program, *argv[1:]],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=timeout,
            env={**os.environ, "LC_ALL": "C"},
        )
    except (OSError, subprocess.SubprocessError) as exc:
        log.debug("%s failed: %s", argv[0], exc)
        return None
    if result.returncode != 0:
        log.debug("%s exited with %d", argv[0], result.returncode)
        return None
    return result.stdout.decode("utf-8", errors="replace")
