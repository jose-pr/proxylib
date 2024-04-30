from typing import Sequence

from . import pac
from .proxy import Proxy, ProxyMap, UriSplit

__all__ = ["SimpleProxyMap", "get_local_interfaces", "get_proxymap_for"]


class SimpleProxyMap(ProxyMap):
    def __init__(self, proxy: "Proxy|Sequence[Proxy]|str" = None) -> None:
        if isinstance(proxy, str):
            proxy = Proxy.find_all(proxy, UriSplit.PAC)
        self.proxies: Sequence[Proxy] = (
            proxy if isinstance(proxy, Sequence) else (proxy,)
        )

    def __getitem__(self, uri: str):
        return self.proxies


def get_proxymap_for(src: "str|Proxy|None") -> ProxyMap:
    if isinstance(src, str):
        try:
            _proxy = Proxy.find_all(src)
        except:
            _proxy = ()
        if len(_proxy) == 1:
            _proxy = _proxy[0]
            netloc = _proxy.netloc

            if (
                _proxy.scheme in ["http", "https"]
                and not src.endswith(netloc)
                or src.endswith(netloc + "/")
            ):
                return pac.load(src)
    else:
        proxy = src

    return SimpleProxyMap(proxy)
