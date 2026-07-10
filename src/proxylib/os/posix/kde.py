"""KDE desktop proxy detection via ``kioslaverc``."""

from __future__ import annotations

import configparser
import os
from pathlib import Path
from typing import Optional

from ...env import EnvProxyConfig
from ...pac.wpad import discover as _wpad_discover
from ...proxy import ProxyMap

__all__ = ("detect",)

# ProxyType values from kioslaverc's [Proxy Settings] section.
_KDE_PROXY_NONE = "0"
_KDE_PROXY_MANUAL = "1"
_KDE_PROXY_PAC_SCRIPT = "2"
_KDE_PROXY_WPAD = "3"
_KDE_PROXY_ENV_VARS = "4"


def _kioslaverc_path() -> Path:
    config_home = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return Path(config_home) / "kioslaverc"


def _read_proxy_settings() -> "Optional[configparser.SectionProxy]":
    path = _kioslaverc_path()
    if not path.is_file():
        return None
    # interpolation=None: PAC URLs/proxy values may contain literal "%"
    # (e.g. percent-encoded paths), which ConfigParser's default
    # interpolation would otherwise choke on.
    parser = configparser.ConfigParser(interpolation=None)
    try:
        parser.read(path, encoding="utf-8")
    except (OSError, configparser.Error):
        return None
    return parser["Proxy Settings"] if parser.has_section("Proxy Settings") else None


def _host_port(section: "configparser.SectionProxy", key: str) -> "str|None":
    # KDE stores these as "scheme://host port" (space-separated port, not a
    # "host:port" URL) -- e.g. "http://proxy.example.com 8080".
    parts = section.get(key, "").split()
    if not parts:
        return None
    return f"{parts[0]}:{parts[1]}" if len(parts) > 1 else parts[0]


def detect() -> "ProxyMap|str|None":
    section = _read_proxy_settings()
    if section is None:
        return None
    proxy_type = section.get("proxytype", _KDE_PROXY_NONE)

    if proxy_type == _KDE_PROXY_WPAD:
        return _wpad_discover()
    if proxy_type == _KDE_PROXY_PAC_SCRIPT:
        pac_url = section.get("proxy config script", "")
        return pac_url or None
    if proxy_type != _KDE_PROXY_MANUAL:
        # none (0), environment variables (4, handled by system_proxy()'s
        # own env var fallback), or an unrecognized value.
        return None

    http_proxy = _host_port(section, "httpproxy")
    https_proxy = _host_port(section, "httpsproxy") or http_proxy
    if not (http_proxy or https_proxy):
        return None
    overrides = [h.strip() for h in section.get("noproxyfor", "").split(",") if h.strip()]
    return EnvProxyConfig(http_proxy or https_proxy, https_proxy, overrides)
