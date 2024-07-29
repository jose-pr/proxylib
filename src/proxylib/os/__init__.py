import os

from ..env import EnvProxyConfig
from ..pac import load as load_pac
from ..proxy import ProxyMap

__all__ = ("system_proxy", "auto_proxy")

if os.name == "nt":
    from .nt import system_proxy
else:

    def system_proxy() -> "ProxyMap|str":
        return os.environ.get('PROXY_PAC') or EnvProxyConfig.from_env()


def auto_proxy(**urlopen_kwargs) -> ProxyMap:
    proxy = system_proxy()
    if isinstance(proxy, str):
        return load_pac(proxy, **urlopen_kwargs)
    else:
        return proxy
