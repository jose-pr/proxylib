"""Platform-agnostic proxy configuration: system/env proxy detection, PAC
evaluation (with WPAD discovery), and Transport Adapters for ``requests``/``urllib``."""

from typing import Any

from ._net import clear_caches as clear_caches
from .bypass import BypassRules as BypassRules
from .env import EnvProxyConfig as EnvProxyConfig
from .exceptions import MissingExtraError as MissingExtraError
from .exceptions import NoReachableProxyError as NoReachableProxyError
from .exceptions import PACError as PACError
from .exceptions import ProxylibError as ProxylibError
from .exceptions import ProxyParseError as ProxyParseError
from .integrations.dict import ProxyDict as ProxyDict
from .integrations.urllib import ProxyMapHandler as ProxyMapHandler
from .pac import PacProxyMap as PacProxyMap
from .pac import PacScript as PacScript
from .pac import load as load_pac
from .pac import loads as loads_pac
from .pac.wpad import discover as discover_pac
from .patching import Patch as Patch
from .patching import patch as patch
from .patching import register_patcher as register_patcher
from .patching import unpatch as unpatch
from .proxy import ChainProxyMap as ChainProxyMap
from .proxy import Proxy as Proxy
from .proxy import ProxyMap as ProxyMap
from .proxy import SimpleProxyMap as SimpleProxyMap
from .proxy import ProxyAnswer as ProxyAnswer
from .proxy import ProxyLike as ProxyLike
from .proxy import alookup as alookup
from .proxy import lookup as lookup
from .system import ProxyConfig as ProxyConfig
from .system import auto_proxy as auto_proxy
from .system import system_config as system_config
from .wrappers import Bypass as Bypass
from .wrappers import Cached as Cached
from .wrappers import Probed as Probed
from .wrappers import RoundRobin as RoundRobin
from .wrappers import configure as configure

__all__ = (
    "Bypass",
    "BypassRules",
    "ChainProxyMap",
    "Cached",
    "EnvProxyConfig",
    "MissingExtraError",
    "NoReachableProxyError",
    "PacProxyMap",
    "PacScript",
    "Patch",
    "PACError",
    "Proxy",
    "ProxyAnswer",
    "ProxyConfig",
    "ProxyDict",
    "ProxyLike",
    "ProxyMap",
    "ProxyMapAdapter",
    "ProxyMapHandler",
    "ProxyParseError",
    "ProxylibError",
    "Probed",
    "RoundRobin",
    "SimpleProxyMap",
    "alookup",
    "auto_proxy",
    "clear_caches",
    "configure",
    "discover_pac",
    "load_pac",
    "loads_pac",
    "lookup",
    "patch",
    "register_patcher",
    "system_config",
    "unpatch",
)

# requests and urllib already imported get proxylib's integration now (the
# rest when they are imported; see proxylib.patching).
from .patching import _install_ready  # noqa: E402

_install_ready()
del _install_ready


def __getattr__(name: str) -> Any:
    # PEP 562. __version__ comes from the installed metadata, so it never
    # drifts from pyproject.toml. ProxyMapAdapter subclasses requests'
    # HTTPAdapter, so it is built (importing requests) on first use only.
    if name == "__version__":
        from importlib.metadata import version

        return version("proxylib")
    if name == "ProxyMapAdapter":
        from .integrations import requests as _requests_integration

        return _requests_integration.ProxyMapAdapter
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
