"""Shared gsettings-based desktop proxy schema reader, used by :mod:`.gnome`
and :mod:`.mate` -- their schemas are identical in shape (MATE forked
GNOME 2's), only the schema id differs.
"""

from __future__ import annotations

import subprocess
from typing import Dict, Tuple

from ...env import EnvProxyConfig
from ...pac.wpad import discover as _wpad_discover
from ...proxy import ProxyMap
from . import _which

__all__ = ("read_desktop_proxy",)

# schema -> {(schema_or_child, key): raw value}, memoized per base schema for
# the process lifetime. clear_gsettings_cache() is the seam tests use.
_recursive_cache: "Dict[str, Dict[Tuple[str, str], str]]" = {}


def clear_gsettings_cache() -> None:
    _recursive_cache.clear()


def _base_schema(schema: str) -> str:
    """Strip a ``.http``/``.https`` child-schema suffix, e.g. for
    ``org.gnome.system.proxy.http`` -> ``org.gnome.system.proxy``."""
    for suffix in (".https", ".http"):
        if schema.endswith(suffix):
            return schema[: -len(suffix)]
    return schema


def _parse_gsettings_recursive(output: str) -> "Dict[Tuple[str, str], str]":
    """Parse ``gsettings list-recursively <schema>`` output.

    Each line is ``<schema> <key> <GVariant-formatted value>`` -- split on
    the first two whitespace runs only, since the value itself can contain
    spaces (list literals, quoted strings). Values are normalized the same
    way the old single-key ``gsettings get`` path was (``strip("'")``);
    callers that need to parse a list/bool literal do so themselves, same
    as before batching.
    """
    values: "Dict[Tuple[str, str], str]" = {}
    for line in output.splitlines():
        parts = line.strip().split(None, 2)
        if len(parts) < 3:
            continue
        schema, key, value = parts
        values[(schema, key)] = value.strip().strip("'")
    return values


def _gsettings_list_recursively(schema: str) -> "Dict[Tuple[str, str], str]":
    if schema in _recursive_cache:
        return _recursive_cache[schema]
    values: "Dict[Tuple[str, str], str]" = {}
    gsettings = _which.which("gsettings")
    if gsettings:
        try:
            result = subprocess.run(
                [gsettings, "list-recursively", schema],
                capture_output=True,
                text=True,
                timeout=5,
                check=True,
            )
            values = _parse_gsettings_recursive(result.stdout)
        except (OSError, subprocess.SubprocessError):
            values = {}
    _recursive_cache[schema] = values
    return values


def _gsettings_get(schema: str, key: str) -> "str|None":
    """Look up one gsettings key, batching reads via ``list-recursively``.

    One recursive call on the base schema (``org.gnome.system.proxy``)
    covers the whole tree if child schemas (``.http``/``.https``) are
    included in its recursive listing -- unverified from this dev box, see
    the Phase 1 CI diagnostic step. If a requested child-schema key isn't
    present in that result, falls back to one additional recursive call
    scoped to the child schema itself (worst case 3 calls total instead of
    up to 7 single-key ``gsettings get`` calls).
    """
    base = _base_schema(schema)
    values = _gsettings_list_recursively(base)
    if schema != base and (schema, key) not in values:
        child_values = _gsettings_list_recursively(schema)
        if child_values:
            values = {**values, **child_values}
            _recursive_cache[base] = values
    return values.get((schema, key))


def read_desktop_proxy(schema: str) -> "ProxyMap|str|None":
    """Read a GNOME/MATE-shaped ``<schema>``/``<schema>.http``/``<schema>.https`` proxy config."""
    mode = _gsettings_get(schema, "mode")
    if mode is None:
        return None
    if mode == "auto":
        pac_url = _gsettings_get(schema, "autoconfig-url")
        if pac_url:
            return pac_url
        # "Automatic" with a blank Configuration URL means "discover the PAC
        # URL via WPAD" (the convention this desktop's own proxy resolution,
        # libproxy, follows too) -- not "nothing configured".
        return _wpad_discover()
    if mode != "manual":
        return None

    def host_port(protocol: str) -> "str|None":
        host = _gsettings_get(f"{schema}.{protocol}", "host")
        port = _gsettings_get(f"{schema}.{protocol}", "port")
        return f"http://{host}:{port}" if host else None

    http_proxy = host_port("http")
    https_proxy = host_port("https") or http_proxy
    if not (http_proxy or https_proxy):
        return None
    ignore_hosts = _gsettings_get(schema, "ignore-hosts") or "[]"
    overrides = [h.strip(" '\"") for h in ignore_hosts.strip("[]").split(",") if h.strip(" '\"")]
    return EnvProxyConfig(http_proxy or https_proxy, https_proxy, overrides)
