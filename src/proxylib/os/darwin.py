"""macOS system proxy detection via ``scutil --proxy`` (no extra dependency)."""

from __future__ import annotations

import subprocess
from typing import Any, Dict, List, Tuple

from ..env import EnvProxyConfig
from ..pac.wpad import discover as _wpad_discover
from ..proxy import ProxyMap, SimpleProxyMap

__all__ = ("system_proxy",)


def _parse_scutil_block(lines: "List[str]", pos: int) -> "Tuple[Dict[str, Any], int]":
    """Parse one ``{ ... }`` block of scutil's key/value dump into a dict (arrays become lists)."""
    result: "Dict[str, Any]" = {}
    while pos < len(lines):
        line = lines[pos].strip()
        pos += 1
        if line == "}":
            break
        if ":" not in line:
            continue
        key, _, rest = line.partition(":")
        key, rest = key.strip(), rest.strip()
        if rest in ("<dictionary> {", "<array> {"):
            value, pos = _parse_scutil_block(lines, pos)
            if rest == "<array> {" and all(k.isdigit() for k in value):
                value = [value[k] for k in sorted(value, key=int)]
            result[key] = value
        else:
            result[key] = rest
    return result, pos


def _read_scutil_proxy() -> "Dict[str, Any]":
    """Run and parse ``scutil --proxy`` into a nested dict; ``{}`` if unavailable."""
    try:
        output = subprocess.run(
            ["scutil", "--proxy"],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return {}

    lines = [ln.rstrip() for ln in output.splitlines()]
    start = next(
        (i + 1 for i, ln in enumerate(lines) if ln.strip().endswith("<dictionary> {")),
        0,
    )
    settings, _ = _parse_scutil_block(lines, start)
    return settings


def system_proxy() -> "ProxyMap|str":
    """Read proxy settings from macOS's System Configuration via ``scutil --proxy``.

    Mirrors macOS's own Network preferences precedence: if "Auto Proxy
    Discovery" (WPAD) is on, it's tried first; then Automatic Proxy
    Configuration (a PAC URL) if enabled; then a manual HTTP/HTTPS proxy;
    otherwise DIRECT.
    """
    settings = _read_scutil_proxy()

    if settings.get("ProxyAutoDiscoveryEnable") == "1":
        discovered = _wpad_discover()
        if discovered is not None:
            return discovered

    if settings.get("ProxyAutoConfigEnable") == "1":
        pac_url = settings.get("ProxyAutoConfigURLString")
        if pac_url:
            return pac_url

    http_enabled = settings.get("HTTPEnable") == "1"
    https_enabled = settings.get("HTTPSEnable") == "1"
    http_proxy = (
        f"http://{settings['HTTPProxy']}:{settings.get('HTTPPort', 80)}"
        if http_enabled and settings.get("HTTPProxy")
        else None
    )
    https_proxy = (
        f"http://{settings['HTTPSProxy']}:{settings.get('HTTPSPort', 443)}"
        if https_enabled and settings.get("HTTPSProxy")
        else None
    )
    if http_proxy or https_proxy:
        overrides = settings.get("ExceptionsList", [])
        return EnvProxyConfig(
            http_proxy or https_proxy, https_proxy or http_proxy, overrides
        )

    return SimpleProxyMap()
