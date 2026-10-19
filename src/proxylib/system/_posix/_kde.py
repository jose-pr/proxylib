"""KDE proxy settings, from ``kioslaverc``'s ``[Proxy Settings]`` section."""

from __future__ import annotations

import configparser
import os
from pathlib import Path
from typing import Optional

from ...bypass import BypassRules
from .. import _run
from .._config import ProxyConfig, proxy_from

__all__ = ("read_config",)

# ProxyType values.
_NONE = "0"
_MANUAL = "1"
_PAC_URL = "2"
_AUTO_DETECT = "3"
_ENVIRONMENT = "4"

# (setting, ProxyConfig key, proxy scheme). KIO's SOCKS proxy is SOCKS v5.
_PROXIES = (
    ("httpproxy", "http", "http"),
    ("httpsproxy", "https", "http"),
    ("ftpproxy", "ftp", "http"),
    ("socksproxy", "socks", "socks5"),
)


def _kioslaverc_path() -> Path:
    config_home = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return Path(config_home) / "kioslaverc"


def _read_proxy_settings() -> "Optional[configparser.SectionProxy]":
    path = _kioslaverc_path()
    if not path.is_file():
        return None
    # No interpolation: a URL may hold a literal "%".
    parser = configparser.ConfigParser(interpolation=None)
    try:
        parser.read(path, encoding="utf-8")
    except (OSError, configparser.Error, UnicodeDecodeError) as exc:
        _run.log.debug("cannot read %s: %s", path, exc)
        return None
    return parser["Proxy Settings"] if parser.has_section("Proxy Settings") else None


def _setting(section: "configparser.SectionProxy", key: str) -> str:
    # KDE writes "scheme://host port", the port after a space.
    parts = section.get(key, "").split()
    if not parts:
        return ""
    return f"{parts[0]}:{parts[1]}" if len(parts) > 1 else parts[0]


def read_config() -> "Optional[ProxyConfig]":
    """``NoProxyFor`` is a KDE bypass list; with ``ReversedException=true`` it
    lists the hosts that use the proxy. ``ProxyType=4`` defers to the
    environment variables, which :func:`~proxylib.auto_proxy` reads first, so
    it is ``None`` here like a missing file."""
    section = _read_proxy_settings()
    if section is None:
        return None
    proxy_type = section.get("proxytype", _NONE).strip()
    if proxy_type == _NONE:
        return ProxyConfig(source="kde", state="direct")
    if proxy_type == _AUTO_DETECT:
        return ProxyConfig(source="kde", state="configured", auto_detect=True)
    if proxy_type == _PAC_URL:
        pac_url = section.get("proxy config script", "").strip()
        return ProxyConfig(source="kde", state="configured", pac_url=pac_url) if pac_url else None
    if proxy_type != _MANUAL:
        return None

    proxies = {}
    for setting, key, scheme in _PROXIES:
        proxy = proxy_from(_setting(section, setting), scheme)
        if proxy is not None:
            proxies[key] = proxy
    overrides = [h.strip() for h in section.get("noproxyfor", "").split(",") if h.strip()]
    reversed_list = section.get("reversedexception", "false").strip().lower() == "true"
    return ProxyConfig(
        source="kde",
        state="configured" if proxies else "direct",
        proxies=proxies,
        bypass=BypassRules.parse(overrides, dialect="kde", reversed=reversed_list),
    )
