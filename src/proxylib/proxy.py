import re
from abc import ABC
from enum import Enum
from socket import getservbyname
from typing import Iterable, NamedTuple, Protocol, overload, runtime_checkable

ALPHA = r"A-Za-z"
DIGIT = r"0-9"
SCHEME = rf"[{ALPHA}][{ALPHA}{DIGIT}+-.]*"
PORT = rf"[{DIGIT}]*"
NON_BREAKING = rf"[^:@/;]"
AUTHORITY = (
    rf"(?:({NON_BREAKING}*)(?::({NON_BREAKING}*))?@)?({NON_BREAKING}+)(?::({PORT}))?"
)
DELIM = r"(?:;|^)\s*"


__all__ = ["Proxy", "ProxyMap", "UriSplit"]


class UriSplit(Enum):
    Default = re.compile(rf"{DELIM}(?:(?:({SCHEME})://)?(?:{AUTHORITY})?\s*)")
    PAC = re.compile(rf"{DELIM}({SCHEME})(?:\s+(?:{AUTHORITY})?\s*)?")

    def match(self, uri: str):
        return self.value.match(uri)

    def findall(self, uri: str):
        return self.value.findall(uri)


class _URI(NamedTuple):
    scheme: str
    username: str
    password: str
    host: str
    port: "int|None"

    @property
    def netloc(self):
        if self.port:
            return f"{self.host}:{self.port}"
        else:
            return self.host

    def resolved(self):
        if self.port:
            return self
        else:
            self.__class__(
                self.scheme,
                self.username,
                self.password,
                self.host,
                getservbyname(self.scheme),
            )

    def as_uri(self):
        authority = self.netloc
        userinfo = ""
        if self.username:
            userinfo = self.username
            if self.password:
                userinfo = userinfo + ":" + self.password

        if userinfo:
            authority = userinfo + "@" + self.netloc
        if self.scheme:
            return self.scheme + "://" + authority
        else:
            return "//" + authority

    @classmethod
    def from_str(
        cls,
        uri: str,
        format: UriSplit = UriSplit.Default,
    ):
        return cls(*format.match(uri).groups()) if uri else None

    @classmethod
    def find_all(cls, uris: str, format: UriSplit = UriSplit.Default):
        return [cls(*uri) for uri in format.findall(uris)] if uris else []


class URL(_URI):
    _DEFAULT_SCHEME = "http"

    def __new__(
        cls, scheme: str, username: str, password: str, host: str, port: str
    ) -> "Proxy":
        scheme = scheme.lower()
        if not scheme:
            scheme = cls._DEFAULT_SCHEME

        if port:
            port = int(port)

        return super().__new__(cls, scheme, username, password, host, port)


class Proxy(_URI):
    _DEFAULT_SCHEME = "http"

    def __new__(
        cls, scheme: str, username: str, password: str, host: str, port: str
    ) -> "Proxy":
        scheme = scheme.lower()
        if scheme == "direct":
            return None
        elif scheme == "proxy":
            scheme = "http"
        elif scheme == "socks":
            scheme = "socks4"
        elif not scheme:
            scheme = cls._DEFAULT_SCHEME

        if port:
            port = int(port)

        return super().__new__(cls, scheme, username, password, host, port)

    @property
    def url(self):
        return f"{self.scheme}://{self.netloc}"


@runtime_checkable
class ProxyMap(Protocol):
    def __getitem__(self, uri: str) -> Iterable[Proxy]:
        raise NotImplementedError()
