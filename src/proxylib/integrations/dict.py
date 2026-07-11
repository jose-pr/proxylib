"""Plain proxies-dict integration: ``ProxyDict`` duck-types the
``{scheme_or_url: "proxy://uri"}`` mapping ``requests`` and similar
libraries accept, resolving from a ``ProxyMap``.
"""

from __future__ import annotations

from ..proxy import ProxyMap

__all__ = ("ProxyDict",)


class ProxyDict:
    """Duck-types the plain ``{scheme_or_url: "proxy://uri"}`` proxies dict that
    ``requests`` and similar libraries accept, resolving from a ``ProxyMap``.

    The simpler integration when a Transport Adapter/handler isn't wanted::

        requests.get(url, proxies=ProxyDict(proxymap))

    Consumers of a proxies dict look keys up by scheme/host, not the full
    request URL, so path-dependent rules (most PAC scripts) won't apply --
    use ``ProxyMapAdapter``/``ProxyMapHandler`` when that fidelity matters.

    Lookups return the first proxy's URI string; DIRECT raises ``KeyError``
    (a missing key means "no proxy", matching the dict convention).

    Deliberately **composes** a ``ProxyMap`` rather than subclassing it --
    ``__getitem__`` here returns a ``str`` (a proxy URI), not
    ``Iterable[Optional[Proxy]]``, which would be an LSP violation if this
    were treated as one.
    """

    __slots__ = ("proxymap",)

    def __init__(self, proxymap: ProxyMap) -> None:
        self.proxymap = proxymap

    def __getitem__(self, uri: str) -> str:
        try:
            proxy = next(iter(self.proxymap[uri]))
            if proxy is None:
                raise KeyError(uri)
            return proxy.as_uri()
        except StopIteration:
            raise KeyError(uri)

    def get(self, uri: str, default=None):
        try:
            return self[uri]
        except KeyError:
            return default

    def __contains__(self, key: object) -> bool:
        try:
            self[key]
            return True
        except KeyError:
            return False

    def copy(self) -> "ProxyDict":
        return type(self)(self.proxymap)

    def setdefault(self, url: str, value: str) -> None:
        """No-op: requests calls this to merge env proxies; the ProxyMap wins."""
