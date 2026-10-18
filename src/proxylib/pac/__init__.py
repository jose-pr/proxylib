"""PAC (Proxy Auto-Config) support.

- :data:`functions` -- the PAC builtins (Netscape set plus Microsoft ``*Ex``).
- :class:`PacScript` -- a script running in a JavaScript engine
  (``proxylib[pac]`` for quickjs, ``proxylib[dukpy]`` for dukpy), with a time
  limit per evaluation.
- :class:`PacProxyMap` -- the proxy map a script (or a Python function)
  answers.
- :func:`load` / :func:`loads` -- a map from a file or URL, or from text.
"""

from __future__ import annotations

import os
from typing import Optional, Union

from ._functions import functions
from .map import PacProxyMap
from .script import MAX_PAC_BYTES, PacScript

__all__ = ("functions", "PacScript", "PacProxyMap", "load", "loads", "MAX_PAC_BYTES")


def load(
    location: "Union[str, os.PathLike]",
    *,
    timeout: float = 10.0,
    cache_ttl: "Optional[float]" = 300.0,
    script_timeout: float = 1.0,
    engine: "Optional[str]" = None,
    on_missing_engine: str = "raise",
) -> PacProxyMap:
    """A :class:`PacProxyMap` for the PAC file at ``location``: a URL
    (``http``, ``https``, ``file``) or a path. Never script text -- use
    :func:`loads`. A ``file:path`` without ``//`` is a path.

    ``timeout``, ``cache_ttl``: the download (see :meth:`PacScript.from_url`).
    ``script_timeout``, ``engine``, ``on_missing_engine``: the script (see
    :class:`PacScript`).
    """
    options = {"engine": engine, "on_missing_engine": on_missing_engine}
    if isinstance(location, str) and "://" in location:
        script = PacScript.from_url(
            location, timeout=timeout, cache_ttl=cache_ttl, script_timeout=script_timeout, **options
        )
    else:
        if isinstance(location, str) and location.startswith("file:"):
            location = location[len("file:"):]
        script = PacScript.from_file(location, timeout=script_timeout, **options)
    return PacProxyMap(script)


def loads(
    text: str,
    *,
    script_timeout: float = 1.0,
    engine: "Optional[str]" = None,
    on_missing_engine: str = "raise",
) -> PacProxyMap:
    """A :class:`PacProxyMap` for PAC script text."""
    return PacProxyMap(
        PacScript(text, timeout=script_timeout, engine=engine, on_missing_engine=on_missing_engine)
    )


def _load_any(source: str) -> PacProxyMap:
    # A configured value (an OS setting, a proxy variable) holds a PAC
    # location or, from NetworkManager, the script itself.
    if "FindProxyForURL" in source:
        return loads(source)
    return load(source)
