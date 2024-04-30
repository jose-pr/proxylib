import typing as ty

from .proxy import ProxyMap

__all__ = ("RequestsProxies",)


class RequestsProxies:
    __slots__ = "proxymap"

    def __init__(self, proxymap: ProxyMap) -> None:
        self.proxymap = proxymap
        pass

    def __getitem__(self, uri: str):
        try:
            proxy = next(iter(self.proxymap[uri]))
            if proxy is None:
                raise KeyError(uri)
            return proxy.as_uri()
        except StopIteration:
            raise KeyError(uri)

    def copy(self):
        return RequestsProxies(self.proxymap)

    def setdefault(self, url: str, value: str):
        pass

    def __contains__(self, key: object) -> bool:
        try:
            self[key]
            return True
        except KeyError:
            return False

    def get(self, uri: str, default: str | None = None):
        try:
            return self[uri]
        except KeyError:
            return default
