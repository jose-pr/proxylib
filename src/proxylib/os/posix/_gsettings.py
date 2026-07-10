"""Shared gsettings-based desktop proxy schema reader, used by :mod:`.gnome`
and :mod:`.mate` -- their schemas are identical in shape (MATE forked
GNOME 2's), only the schema id differs.
"""

from __future__ import annotations

import shutil
import subprocess

from ...env import EnvProxyConfig
from ...pac.wpad import discover as _wpad_discover
from ...proxy import ProxyMap

__all__ = ("read_desktop_proxy",)


def _gsettings_get(schema: str, key: str) -> "str|None":
    gsettings = shutil.which("gsettings")
    if not gsettings:
        return None
    try:
        result = subprocess.run(
            [gsettings, "get", schema, key],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip().strip("'")


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
