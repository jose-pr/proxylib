"""Platform-agnostic proxy configuration: system/env proxy detection, PAC
evaluation (with WPAD discovery), and Transport Adapters for ``requests``/``urllib``."""

from .env import EnvProxyConfig as EnvProxyConfig
from .os import auto_proxy, system_proxy
from .os.posix.libproxy import LibProxyMap as LibProxyMap
from .pac import PAC as PAC
from .pac import JSProxyAutoConfig as JSProxyAutoConfig
from .pac import load as load_pac
from .pac.wpad import discover as discover_pac
from .proxy import *
from .requests import ProxyMapAdapter as ProxyMapAdapter
from .requests import RequestsProxies
from .urllib import ProxyMapHandler as ProxyMapHandler
