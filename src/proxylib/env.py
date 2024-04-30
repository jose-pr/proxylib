import os
import re
from typing import Iterable as _Iter

from .netutils import get_ip, get_local_interfaces
from .proxy import URL, Proxy, ProxyMap
from .utils import get_proxymap_for

__all__ = ("EnvProxyConfig",)


class EnvProxyConfig(ProxyMap):
    __slots__ = ("http_proxy", "https_proxy", "no_proxy")

    def __init__(
        self,
        http_proxy: "str|Proxy|None",
        https_proxy: "str|Proxy|None",
        no_proxy: "_Iter[str]",
    ) -> None:
        self.http_proxy = get_proxymap_for(http_proxy)
        self.https_proxy = get_proxymap_for(https_proxy)
        self.no_proxy = (
            [
                re.compile(re.escape(_no) + ".*") if _no != "<local>" else None
                for _no in set(no_proxy)
            ]
            if no_proxy
            else []
        )

    def __getitem__(self, url: str) -> _Iter[Proxy]:
        uri = URL.from_str(url)
        url = f"{uri.scheme}://{uri.netloc}"
        ip = get_ip(uri.host)
        for _no in self.no_proxy:
            if _no is None:
                for _if in get_local_interfaces():
                    if ip in _if.network:
                        return [None]
            else:
                if _no.match(url):
                    return [None]
        return self.https_proxy[url] if uri.scheme == "https" else self.http_proxy[url]

    @staticmethod
    def from_env():
        https = os.environ.get("HTTPS_PROXY", None)
        if not https:
            https = os.environ.get("https_proxy")

        http = os.environ.get("HTTP_PROXY", None)
        if not http:
            http = os.environ.get("http_proxy")

        no_proxy = os.environ.get("NO_PROXY", None)
        if not no_proxy:
            no_proxy = os.environ.get("no_proxy")

        return EnvProxyConfig(http, https, no_proxy)
