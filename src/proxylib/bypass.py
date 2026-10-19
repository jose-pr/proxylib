"""Proxy bypass rules: which request URLs go DIRECT, in each OS's own syntax.

``BypassRules.parse(text, dialect=...)`` reads a bypass list written for
``NO_PROXY`` (curl), the Windows ``ProxyOverride`` setting (WinINet), the macOS
``ExceptionsList``, GNOME/MATE ``ignore-hosts`` (GLib) or KDE ``NoProxyFor``;
``rules.matches(url)`` says whether ``url`` bypasses the proxy.

Rule kinds, in every dialect unless noted:

- a host name: exact match, or (``no_proxy``/``kde``, and any entry written
  with a leading ``.`` or ``*.``) the name and every subdomain;
- a glob with ``*`` and ``?`` (``[`` is literal), matched case-insensitively
  against the host;
- an IP network in CIDR form (``10.0.0.0/8``, abbreviated ``169.254/16``,
  ``2001:db8::/32``), matched against IP-literal hosts only;
- an optional ``:port`` after a host, matched against the request's port
  (the scheme's default port when the URL has none);
- ``<local>``: a host name with no dot (WinINet meaning);
- ``<subnet>``: a host that resolves to a loopback or link-local address or to
  an address on the same network as a local interface;
- ``<-loopback>``: turns off the implicit loopback bypass;
- ``*`` as the whole list: every host.

``localhost``, ``*.localhost``, ``127.0.0.0/8`` and ``::1`` always bypass
unless ``<-loopback>`` is given, as in Chromium and Go.
"""

from __future__ import annotations

import ipaddress as _ip
import re
import warnings
from functools import lru_cache
from typing import Callable, Iterable, List, Optional, Tuple, Union
from urllib.parse import urlsplit

from . import _net

__all__ = ("BypassRules", "Dialect")

Dialect = str
"""One of ``"no_proxy"``, ``"wininet"``, ``"macos"``, ``"gsettings"``, ``"kde"``."""

_DIALECTS = ("no_proxy", "wininet", "macos", "gsettings", "kde")
_SEPARATORS = {
    "no_proxy": r"[,\s]+",
    "wininet": r"[;\s]+",
    "macos": r"[,\s]+",
    "gsettings": r"[,\s]+",
    "kde": r"[,\s]+",
}

_Network = Union[_ip.IPv4Network, _ip.IPv6Network]
_Address = Union[_ip.IPv4Address, _ip.IPv6Address]
# (scheme, host, port): host lower-cased with IPv6 brackets removed; port is
# the explicit one or the scheme's default.
_Target = Tuple[str, str, Optional[int]]
_Rule = Callable[[_Target], bool]

_LOOPBACK_NETWORKS = (_ip.ip_network("127.0.0.0/8"), _ip.ip_network("::1/128"))


@lru_cache(maxsize=512)
def _glob(pattern: str) -> "re.Pattern[str]":
    parts = (".*" if c == "*" else "." if c == "?" else re.escape(c) for c in pattern)
    return re.compile("".join(parts), re.IGNORECASE | re.DOTALL)


def _ip_of(host: str) -> "Optional[_Address]":
    try:
        return _ip.ip_address(host.split("%", 1)[0])
    except ValueError:
        return None


def _network(text: str) -> _Network:
    address, _, prefix = text.partition("/")
    octets = address.split(".")
    if len(octets) < 4 and all(octet.isdigit() for octet in octets):
        address = ".".join(octets + ["0"] * (4 - len(octets)))
    return _ip.ip_network(f"{address}/{prefix}", strict=False)


def _port_ok(want: "Optional[int]", target: _Target) -> bool:
    return want is None or want == target[2]


def _exact(host: str, port: "Optional[int]") -> _Rule:
    return lambda t: t[1] == host and _port_ok(port, t)


def _suffix(domain: str, port: "Optional[int]") -> _Rule:
    dotted = "." + domain
    return lambda t: (t[1] == domain or t[1].endswith(dotted)) and _port_ok(port, t)


def _glob_rule(pattern: str, port: "Optional[int]") -> _Rule:
    regex = _glob(pattern)
    return lambda t: regex.fullmatch(t[1]) is not None and _port_ok(port, t)


def _cidr(network: _Network, port: "Optional[int]") -> _Rule:
    def rule(t: _Target) -> bool:
        address = _ip_of(t[1])
        return address is not None and address in network and _port_ok(port, t)

    return rule


def _address_rule(address: "_Address", port: "Optional[int]") -> _Rule:
    return lambda t: _ip_of(t[1]) == address and _port_ok(port, t)


def _local(t: _Target) -> bool:
    return "." not in t[1] and _ip_of(t[1]) is None


def _subnet(t: _Target) -> bool:
    address = _net.resolve_ip(t[1], ipv6=None)
    if address is None:
        return False
    if _net.is_link_scoped(address):
        return True
    return any(address in network.network for network in _net.local_networks())


def _everything(t: _Target) -> bool:
    return True


def _is_loopback(t: _Target) -> bool:
    host = t[1]
    if host == "localhost" or host.endswith(".localhost"):
        return True
    address = _ip_of(host)
    return address is not None and any(address in net for net in _LOOPBACK_NETWORKS)


def _split_port(entry: str) -> "Optional[Tuple[str, Optional[int]]]":
    """``host[:port]`` with IPv6 brackets; a host containing glob characters
    is split on its last colon only when what follows is a port."""
    if "*" in entry or "?" in entry:
        host, sep, port = entry.rpartition(":")
        if sep and port.isdigit() and host:
            return host, int(port)
        return entry, None
    return _net.split_host_port(entry)


class BypassRules:
    """An immutable list of bypass rules; see the module docstring.

    ``rules.matches(url)`` is true when ``url`` should go DIRECT. ``a | b``
    combines two lists; ``bool(rules)`` is false for an empty list (which
    still bypasses loopback unless ``<-loopback>`` was given).
    """

    __slots__ = ("_rules", "_text", "_loopback", "_reversed")

    NONE: "BypassRules"

    def __init__(
        self,
        rules: "Iterable[_Rule]" = (),
        *,
        text: "Tuple[Tuple[str, str], ...]" = (),
        loopback: bool = True,
        reversed: bool = False,
    ) -> None:
        object.__setattr__(self, "_rules", tuple(rules))
        object.__setattr__(self, "_text", tuple(text))
        object.__setattr__(self, "_loopback", loopback)
        object.__setattr__(self, "_reversed", reversed)

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError("BypassRules is immutable")

    def __repr__(self) -> str:
        flags = "" if self._loopback else ", loopback=False"
        flags += ", reversed=True" if self._reversed else ""
        return f"BypassRules({[entry for _, entry in self._text]!r}{flags})"

    def __bool__(self) -> bool:
        return bool(self._rules)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, BypassRules):
            return NotImplemented
        return (self._text, self._loopback, self._reversed) == (
            other._text,
            other._loopback,
            other._reversed,
        )

    def __hash__(self) -> int:
        return hash((self._text, self._loopback, self._reversed))

    def __or__(self, other: "BypassRules") -> "BypassRules":
        if not isinstance(other, BypassRules):
            return NotImplemented
        if self._reversed or other._reversed:
            raise ValueError("a reversed (KDE ReversedException) list cannot be combined")
        return BypassRules(
            self._rules + other._rules,
            text=self._text + other._text,
            loopback=self._loopback and other._loopback,
        )

    @classmethod
    def parse(
        cls,
        text: "Union[str, Iterable[str], None]",
        *,
        dialect: Dialect = "no_proxy",
        reversed: bool = False,
    ) -> "BypassRules":
        """Parse a bypass list written in ``dialect``. ``text`` is the list as
        one string, or its entries. Unparsable entries are skipped with one
        warning naming them. ``reversed=True`` (KDE ``ReversedException``)
        makes the list name the hosts that use the proxy."""
        if dialect not in _DIALECTS:
            raise ValueError(f"unknown bypass dialect {dialect!r}; expected one of {_DIALECTS}")
        if reversed and dialect != "kde":
            raise ValueError("reversed= applies to the kde dialect only")
        if text is None:
            entries: "List[str]" = []
        elif isinstance(text, str):
            entries = [e for e in re.split(_SEPARATORS[dialect], text.strip()) if e]
        else:
            entries = [e.strip() for e in text if e and e.strip()]

        rules: "List[_Rule]" = []
        kept: "List[Tuple[str, str]]" = []
        bad: "List[str]" = []
        loopback = True
        whole_star = entries == ["*"]
        for entry in entries:
            token = entry.lower()
            if token == "<-loopback>":
                loopback = False
                kept.append((dialect, entry))
                continue
            if token == "*" and not whole_star:
                warnings.warn(
                    "bypass entry '*' among other entries: "
                    + ("ignored, as curl and requests do" if dialect == "no_proxy" else "it matches every host"),
                    stacklevel=2,
                )
                if dialect == "no_proxy":
                    continue
            rule = _parse_entry(entry, dialect)
            if rule is None:
                bad.append(entry)
                continue
            rules.append(rule)
            kept.append((dialect, entry))
        if bad:
            warnings.warn(f"ignoring unparsable bypass entries: {bad!r}", stacklevel=2)
        return cls(rules, text=tuple(kept), loopback=loopback, reversed=reversed)

    def matches(self, url: str) -> bool:
        """Whether ``url`` should go DIRECT. A URL with no host never matches."""
        target = _target(url)
        if target is None:
            return False
        if self._loopback and _is_loopback(target):
            return True
        listed = any(rule(target) for rule in self._rules)
        return not listed if self._reversed else listed


BypassRules.NONE = BypassRules()


def _target(url: str) -> "Optional[_Target]":
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return None
    if not parts.hostname:
        return None
    scheme = parts.scheme.lower()
    return (scheme, parts.hostname, port if port is not None else _net.default_port(scheme))


def _strip_scheme(entry: str) -> str:
    # WinINet and KDE lists sometimes carry "http://host" entries.
    _, sep, rest = entry.partition("://")
    return rest.rstrip("/") if sep else entry


def _parse_entry(entry: str, dialect: Dialect) -> "Optional[_Rule]":
    token = entry.lower()
    if token == "*":
        return _everything
    if token == "<local>":
        return _local
    if token == "<subnet>":
        return _subnet
    entry = _strip_scheme(entry)
    if "/" in entry:
        try:
            return _cidr(_network(entry), None)
        except ValueError:
            return None
    split = _split_port(entry)
    if split is None or not split[0]:
        return None
    host, port = split
    host = host.lower()
    if host.startswith("*.") and "*" not in host[2:] and "?" not in host[2:]:
        return _suffix(host[2:], port)
    if "*" in host or "?" in host:
        return _glob_rule(host, port)
    if host.startswith("."):
        return _suffix(host.lstrip("."), port)
    address = _ip_of(host)
    if address is not None:
        return _address_rule(address, port)
    if dialect in ("no_proxy", "kde"):
        return _suffix(host, port)
    return _exact(host, port)
