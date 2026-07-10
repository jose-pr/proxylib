"""Platform-agnostic proxy configuration: system/env proxy detection, PAC
evaluation (with WPAD discovery), and Transport Adapters for ``requests``/``urllib``."""

from .env import EnvProxyConfig as EnvProxyConfig
from .netutils import first_working_proxy as first_working_proxy
from .os import auto_proxy, system_proxy
from .os.posix.libproxy import LibProxyMap as LibProxyMap
from .pac import PAC as PAC
from .pac import JSProxyAutoConfig as JSProxyAutoConfig
from .pac import load as load_pac
from .pac.wpad import discover as discover_pac
from .proxy import *
from .requests import ProxyMapAdapter as ProxyMapAdapter
from .urllib import ProxyMapHandler as ProxyMapHandler


def __getattr__(name: str):
    # PEP 562: resolve __version__ lazily from the installed metadata so it
    # never drifts from pyproject.toml and costs nothing at import time.
    if name == "__version__":
        from importlib.metadata import version

        return version("proxylib")
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
