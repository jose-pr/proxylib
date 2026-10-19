"""GNOME (``org.gnome.system.proxy``) and MATE (``org.mate.system.proxy``)
proxy settings, read with ``gsettings``; MATE's schema is GNOME 2's, so both
have the same keys."""

from __future__ import annotations

import time
from typing import Dict, List, Optional, Tuple

from ... import _net
from ...bypass import BypassRules
from .. import _run
from .._config import ProxyConfig, proxy_at

__all__ = ("read_config",)

# schema -> (monotonic timestamp, {(schema, key): value}). One `gsettings
# list-recursively` serves every key a lookup reads; _CACHE_TTL seconds lets
# a settings change take effect.
_recursive_cache: "Dict[str, Tuple[float, Dict[Tuple[str, str], str]]]" = {}
_CACHE_TTL = 10.0

# (child schema / ProxyConfig key, proxy scheme). The https and ftp hosts are
# HTTP proxies for those schemes; the socks host is SOCKS v5, as Chromium reads it.
_MANUAL = (("http", "http"), ("https", "http"), ("ftp", "http"), ("socks", "socks5"))


@_net.register_cache
def clear_gsettings_cache() -> None:
    _recursive_cache.clear()


def _base_schema(schema: str) -> str:
    """``org.gnome.system.proxy.http`` -> ``org.gnome.system.proxy``."""
    for suffix in (".https", ".http", ".ftp", ".socks"):
        if schema.endswith(suffix):
            return schema[: -len(suffix)]
    return schema


def _parse_gsettings_recursive(output: str) -> "Dict[Tuple[str, str], str]":
    """Each line is ``<schema> <key> <GVariant value>``; the value may hold
    spaces, so only the first two are split on. String quotes are dropped."""
    values: "Dict[Tuple[str, str], str]" = {}
    for line in output.splitlines():
        parts = line.strip().split(None, 2)
        if len(parts) < 3:
            continue
        schema, key, value = parts
        values[(schema, key)] = value.strip().strip("'")
    return values


def _gsettings_list_recursively(schema: str) -> "Dict[Tuple[str, str], str]":
    cached = _recursive_cache.get(schema)
    if cached is not None and time.monotonic() - cached[0] < _CACHE_TTL:
        return cached[1]
    output = _run.run(["gsettings", "list-recursively", schema])
    values = _parse_gsettings_recursive(output) if output is not None else {}
    _recursive_cache[schema] = (time.monotonic(), values)
    return values


def _gsettings_get(schema: str, key: str) -> "Optional[str]":
    """One key, from the base schema's recursive listing. Some gsettings
    versions leave child schemas out of it; those are then listed on their own."""
    base = _base_schema(schema)
    values = _gsettings_list_recursively(base)
    if schema != base and (schema, key) not in values:
        child_values = _gsettings_list_recursively(schema)
        if child_values:
            values = {**values, **child_values}
            _recursive_cache[base] = (time.monotonic(), values)
    return values.get((schema, key))


def _string_list(value: "Optional[str]") -> "List[str]":
    """A GVariant string array: ``['localhost', '*.internal']``, or ``@as []``
    when empty."""
    value = (value or "").strip()
    if value.startswith("@as "):
        value = value[len("@as "):]
    items = (item.strip(" '\"") for item in value.strip("[]").split(","))
    return [item for item in items if item]


def read_config(schema: str, source: str) -> "Optional[ProxyConfig]":
    """``mode`` is ``none``, ``manual`` or ``auto``; ``auto`` with a blank
    ``autoconfig-url`` means auto-detection (WPAD). ``None`` when gsettings or
    the schema is missing."""
    mode = _gsettings_get(schema, "mode")
    if mode is None:
        return None
    if mode == "none":
        return ProxyConfig(source=source, state="direct")
    if mode == "auto":
        pac_url = (_gsettings_get(schema, "autoconfig-url") or "").strip() or None
        return ProxyConfig(source=source, state="configured", auto_detect=pac_url is None, pac_url=pac_url)
    if mode != "manual":
        _run.log.debug("%s: unknown proxy mode %r", schema, mode)
        return None
    proxies = {}
    for key, scheme in _MANUAL:
        proxy = proxy_at(_gsettings_get(f"{schema}.{key}", "host"), _gsettings_get(f"{schema}.{key}", "port"), scheme)
        if proxy is not None:
            proxies[key] = proxy
    return ProxyConfig(
        source=source,
        state="configured" if proxies else "direct",
        proxies=proxies,
        bypass=BypassRules.parse(_string_list(_gsettings_get(schema, "ignore-hosts")), dialect="gsettings"),
    )
