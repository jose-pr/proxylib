"""NetworkManager's per-connection proxy settings.

A connection's ``proxy.method`` is ``none`` or ``auto`` (with a PAC URL, a PAC
script, or neither for auto-detection); there is no manual proxy at this
layer (`settings-proxy
<https://networkmanager.dev/docs/api/latest/settings-proxy.html>`_). Read with
``nmcli`` when installed, else over D-Bus with ``dbus-send``.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional

from .. import _run
from .._config import ProxyConfig

__all__ = ("read_config", "config_from_settings")


# ---- nmcli ------------------------------------------------------------------


def _nmcli_get(*args: str) -> "List[str]":
    output = _run.run(["nmcli", "-g", *args])
    return output.split("\n") if output is not None else []


def _proxy_settings_via_nmcli() -> "Optional[Dict[str, str]]":
    if not _run.which("nmcli"):
        return None
    active_uuids = [u.strip() for u in _nmcli_get("UUID", "connection", "show", "--active") if u.strip()]
    # Every active connection is read: the proxy is often set on a VPN
    # connection that is not listed first.
    first: "Optional[Dict[str, str]]" = None
    for uuid in active_uuids:
        fields = _nmcli_get("proxy.method,proxy.pac-url,proxy.pac-script", "connection", "show", uuid)
        if len(fields) < 3:
            continue
        settings = {
            "method": fields[0].strip(),
            "pac-url": fields[1].strip(),
            "pac-script": fields[2].strip(),
        }
        if settings["method"] not in ("", "none"):
            return settings
        first = first or settings
    return first


# ---- dbus-send ----------------------------------------------------------------
# dbus-send --print-reply is a debug printer, not a stable format: this reads
# only object paths and the string values in the "proxy" settings group, and
# anything unexpected reads as "no settings".

_NM_DEST = "org.freedesktop.NetworkManager"


def _dbus_send(*args: str) -> "Optional[str]":
    return _run.run(["dbus-send", "--system", "--print-reply", f"--dest={_NM_DEST}", *args])


def _object_paths(reply: str) -> "List[str]":
    return re.findall(r'object path "([^"]+)"', reply)


def _proxy_group_values(get_settings_reply: str) -> "Dict[str, str]":
    """The string values in the "proxy" group of a
    ``Settings.Connection.GetSettings()`` reply."""
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
    return dict(re.findall(r'string "([^"]+)"\s*variant\s+string "([^"]*)"', group_text))


def _proxy_settings_via_dbus_send() -> "Optional[Dict[str, str]]":
    if not _run.which("dbus-send"):
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
        settings_reply = _dbus_send(settings_paths[0], f"{_NM_DEST}.Settings.Connection.GetSettings")
        if not settings_reply:
            continue
        proxy_group = _proxy_group_values(settings_reply)
        if proxy_group:
            return proxy_group
    return None


def config_from_settings(settings: "Dict[str, str]") -> "Optional[ProxyConfig]":
    """``None`` unless ``method`` is ``auto``: ``none`` is every connection's
    default, not a choice to go direct."""
    if settings.get("method") != "auto":
        return None
    pac_url = settings.get("pac-url", "").strip() or None
    pac_script = settings.get("pac-script", "").strip() or None
    if pac_script and "FindProxyForURL" not in pac_script:
        _run.log.debug("ignoring a NetworkManager pac-script with no FindProxyForURL")
        pac_script = None
    return ProxyConfig(
        source="networkmanager",
        state="configured",
        auto_detect=not (pac_url or pac_script),
        pac_url=pac_url,
        pac_script=pac_script,
    )


def read_config() -> "Optional[ProxyConfig]":
    settings = _proxy_settings_via_nmcli() or _proxy_settings_via_dbus_send()
    return config_from_settings(settings) if settings else None
