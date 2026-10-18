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
from .os import auto_proxy as auto_proxy
from .os import system_proxy as system_proxy
from .os.posix.libproxy import LibProxyMap as LibProxyMap
from .pac import PAC as PAC
from .pac import JSProxyAutoConfig as JSProxyAutoConfig
from .pac import load as load_pac
from .pac.wpad import discover as discover_pac
from .patching import patch as patch
from .patching import register_patcher as register_patcher
from .patching import unpatch as unpatch
from .proxy import ChainProxyMap as ChainProxyMap
from .proxy import ConfigurableProxyMap as ConfigurableProxyMap
from .proxy import Proxy as Proxy
from .proxy import ProxyMap as ProxyMap
from .proxy import SimpleProxyMap as SimpleProxyMap
from .proxy import ProxyAnswer as ProxyAnswer
from .proxy import ProxyLike as ProxyLike
from .proxy import lookup as lookup

__all__ = (
    "BypassRules",
    "ChainProxyMap",
    "ConfigurableProxyMap",
    "EnvProxyConfig",
    "JSProxyAutoConfig",
    "LibProxyMap",
    "MissingExtraError",
    "NoReachableProxyError",
    "PAC",
    "PACError",
    "Proxy",
    "ProxyAnswer",
    "ProxyDict",
    "ProxyLike",
    "ProxyMap",
    "ProxyMapAdapter",
    "ProxyMapHandler",
    "ProxyParseError",
    "ProxylibError",
    "SimpleProxyMap",
    "auto_proxy",
    "clear_caches",
    "discover_pac",
    "load_pac",
    "lookup",
    "patch",
    "register_patcher",
    "system_proxy",
    "unpatch",
)


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
