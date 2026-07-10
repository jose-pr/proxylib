"""NetworkManager proxy detection.

NetworkManager's own per-connection ``proxy`` setting (see the
`settings-proxy docs <https://networkmanager.dev/docs/api/latest/settings-proxy.html>`_,
exposed over D-Bus on ``org.freedesktop.NetworkManager.Settings.Connection``)
only supports ``method`` = ``"none"`` or ``"auto"`` -- there's no manual
host:port option at this layer, unlike the desktop-level backends.

Read via ``nmcli`` (NetworkManager's own CLI) when it's on ``PATH``; if it
isn't (a minimal install with just the daemon + D-Bus, no CLI tools),
fall back to talking to the same D-Bus interface directly via ``dbus-send``.
Neither needs a non-stdlib dependency (e.g. ``dbus-python``/``pydbus``).
"""

from __future__ import annotations

import re
import shutil
import subprocess
from typing import Dict, List, Optional

from ...pac.wpad import discover as _wpad_discover
from ...proxy import ProxyMap

__all__ = ("detect",)


# ---- nmcli ------------------------------------------------------------------

def _nmcli_get(*args: str) -> "List[str]":
    nmcli = shutil.which("nmcli")
    if not nmcli:
        return []
    try:
        result = subprocess.run(
            [nmcli, "-g", *args],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    return result.stdout.split("\n")


def _proxy_settings_via_nmcli() -> "Optional[Dict[str, str]]":
    if not shutil.which("nmcli"):
        return None
    active_uuids = [u.strip() for u in _nmcli_get("UUID", "connection", "show", "--active") if u.strip()]
    if not active_uuids:
        return None
    fields = _nmcli_get(
        "proxy.method,proxy.pac-url,proxy.pac-script", "connection", "show", active_uuids[0]
    )
    if len(fields) < 3:
        return None
    return {
        "method": fields[0].strip(),
        "pac-url": fields[1].strip(),
        "pac-script": fields[2].strip(),
    }


# ---- dbus-send fallback -------------------------------------------------------
# dbus-send's --print-reply output is a debug pretty-printer, not a
# machine-friendly format -- this is a narrowly-targeted scrape (object
# paths, and string values inside the "proxy" settings group specifically),
# not a general D-Bus variant parser. Any surprise in the output just makes
# these return None/empty, same as "nothing configured" -- never raises.

_NM_DEST = "org.freedesktop.NetworkManager"


def _dbus_send(*args: str) -> "Optional[str]":
    dbus_send = shutil.which("dbus-send")
    if not dbus_send:
        return None
    try:
        result = subprocess.run(
            [dbus_send, "--system", "--print-reply", f"--dest={_NM_DEST}", *args],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout


def _object_paths(reply: str) -> "List[str]":
    return re.findall(r'object path "([^"]+)"', reply)


def _proxy_group_values(get_settings_reply: str) -> "Dict[str, str]":
    """Pull string values out of the "proxy" dict-entry group in a
    Settings.Connection.GetSettings() dbus-send reply."""
    start = get_settings_reply.find('string "proxy"')
    if start == -1:
        return {}
    group_start = get_settings_reply.find("[", start)
    if group_start == -1:
        return {}
    depth = 0
    end = group_start
    for end in range(group_start, len(get_settings_reply)):
        char = get_settings_reply[end]
        if char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
            if depth == 0:
                break
    group_text = get_settings_reply[group_start : end + 1]

    return {
        key: value
        for key, value in re.findall(
            r'string "([^"]+)"\s*variant\s+string "([^"]*)"', group_text
        )
    }


def _proxy_settings_via_dbus_send() -> "Optional[Dict[str, str]]":
    if not shutil.which("dbus-send"):
        return None

    active_reply = _dbus_send(
        "/org/freedesktop/NetworkManager",
        "org.freedesktop.DBus.Properties.Get",
        f"string:{_NM_DEST}",
        "string:ActiveConnections",
    )
    if not active_reply:
        return None

    for active_path in _object_paths(active_reply):
        connection_reply = _dbus_send(
            active_path,
            "org.freedesktop.DBus.Properties.Get",
            f"string:{_NM_DEST}.Connection.Active",
            "string:Connection",
        )
        settings_paths = _object_paths(connection_reply) if connection_reply else []
        if not settings_paths:
            continue

        settings_reply = _dbus_send(
            settings_paths[0], f"{_NM_DEST}.Settings.Connection.GetSettings"
        )
        if not settings_reply:
            continue

        proxy_group = _proxy_group_values(settings_reply)
        if proxy_group:
            return proxy_group

    return None


def _resolve(settings: "Dict[str, str]") -> "ProxyMap|str|None":
    if settings.get("method") != "auto":
        return None
    pac_url = settings.get("pac-url", "")
    if pac_url:
        return pac_url
    pac_script = settings.get("pac-script", "")
    if pac_script:
        # pac.load() detects inline JS source (vs. a URL) via this substring.
        return pac_script if "FindProxyForURL(" in pac_script else None
    return _wpad_discover()


def detect() -> "ProxyMap|str|None":
    settings = _proxy_settings_via_nmcli() or _proxy_settings_via_dbus_send()
    return _resolve(settings) if settings else None
