"""Private: URI/authority regex grammar and the base ``_URI``/``URL`` tuple types.

Split out of ``proxy.py`` to decouple raw URI-string parsing from
proxy-mapping logic. ``UriSplit`` and ``_URI`` stay importable from
``proxy.py`` (tests import ``_URI`` from there) -- this module is private,
not a public API surface.
"""

from __future__ import annotations

import re
from enum import Enum
from typing import NamedTuple, Optional

from . import netutils

ALPHA = r"A-Za-z"
DIGIT = r"0-9"
# Dash LAST inside the class, deliberately: "+-." reads as the RANGE 0x2B-0x2E,
# which also matches "," (0x2C) and "-" is then a range operator rather than a
# literal. RFC 3986 scheme chars are ALPHA / DIGIT / "+" / "-" / "." only.
SCHEME = rf"[{ALPHA}][{ALPHA}{DIGIT}+.-]*"
PORT = rf"[{DIGIT}]*"
NON_BREAKING = rf"[^:@/;]"
AUTHORITY = (
    rf"(?:({NON_BREAKING}*)(?::({NON_BREAKING}*))?@)?({NON_BREAKING}+)(?::({PORT}))?"
)
DELIM = r"(?:;|^)\s*"


class UriSplit(Enum):
    """Regexes for splitting either a plain URI or a PAC ``PROXY ...; ...`` string."""

    Default = re.compile(rf"{DELIM}(?:(?:({SCHEME}):)?(?://{AUTHORITY})?\s*)")
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
    port: Optional[int]

    @property
    def netloc(self) -> str:
        if self.port:
            return f"{self.host}:{self.port}"
        else:
            return self.host

    def resolved(self) -> "_URI":
        """Return a copy with the scheme's conventional port filled in if missing."""
        if self.port:
            return self
        return self.__class__(
            self.scheme,
            self.username,
            self.password,
            self.host,
            netutils.get_default_port(self.scheme),
        )

    def as_uri(self) -> str:
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
    ) -> "Optional[_URI]":
        if not uri:
            return None
        match = format.match(uri)
        if not match or not any(match.groups()):
            # A bare hostname like "example.com" technically "matches" with
            # every group empty -- reject it clearly instead of building a
            # URI of Nones that crashes later.
            raise ValueError(f"Could not parse {uri!r} as a {format.name} URI")
        return cls(*match.groups())

    @classmethod
    def find_all(cls, uris: str, format: UriSplit = UriSplit.Default) -> "list[_URI]":
        return [cls(*uri) for uri in format.findall(uris)] if uris else []


class URL(_URI):
    _DEFAULT_SCHEME = "http"

    def __new__(
        cls, scheme: str, username: str, password: str, host: str, port: "str|int|None"
    ) -> "URL":
        scheme = (scheme or "").lower()
        if not scheme:
            scheme = cls._DEFAULT_SCHEME

        if port:
            port = int(port)

        return super().__new__(cls, scheme, username, password, host, port)
