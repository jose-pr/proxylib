# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [1.0.0-rc.1] - 2026-07-09

First tracked release. `proxylib` graduates from a small proxy-string-parsing
utility into a platform-agnostic "what proxy should I use for this request"
library, with real system detection on every major OS/desktop, WPAD
discovery, full PAC compliance, and integrations for both `requests` and
`urllib`.

### Added

- Cross-platform system proxy auto-detection (`system_proxy()`/`auto_proxy()`):
  - **Windows**, via the WinHTTP API (`WinHttpGetIEProxyConfigForCurrentUser`) —
    respects "Automatically detect settings", the configured PAC script, and a
    manual proxy, in that precedence order.
  - **macOS**, via `scutil --proxy` — respects "Auto Proxy Discovery"
    (WPAD), "Automatic Proxy Configuration" (PAC), and a manual proxy.
  - **Linux**, via (in order) [libproxy](https://libproxy.github.io/libproxy/)
    (through direct `ctypes` bindings to its C API), GNOME/MATE (`gsettings`),
    KDE (`kioslaverc`), and NetworkManager (`nmcli`, or `dbus-send` directly
    if `nmcli` isn't installed) — plus the existing `HTTP_PROXY`/`HTTPS_PROXY`/
    `NO_PROXY`/`PROXY_PAC` env var fallback.
  - `LibProxyMap`, libproxy's own resolution, also available as a standalone
    `ProxyMap` usable directly on any platform.
- **WPAD** (Web Proxy Auto-Discovery) support via DNS + HTTP
  (`wpad.<domain>/wpad.dat`), used both by each platform's own auto-detect
  signal above and as a generic `auto_proxy()` fallback when nothing else is
  configured. DHCP-based discovery (option 252) is out of scope — no portable
  stdlib path to OS DHCP lease data.
- **`ProxyMapAdapter`**, a `requests` Transport Adapter that resolves the
  proxy from the real request URL (scheme, host, and path), not just
  scheme+host.
- **`ProxyMapHandler`**, the equivalent integration for `urllib.request`.
- Full Netscape PAC utility-function support: `dateRange`/`timeRange` are
  real implementations now (previously always returned `False`), and
  `isInNet` is IPv6-tolerant. Added the common Microsoft `*Ex` extensions
  real-world WPAD files rely on: `dnsResolveEx`, `myIpAddressEx`,
  `isResolvableEx`, `isInNetEx`, `sortIpAddressList`, `getClientVersion`.
- PEP 561 typing support (`py.typed`) and a full type-hint pass.
- Substantially expanded test suite (5 tests → 110+) and documentation
  (rewritten `README.md`, docstrings throughout).

### Changed

- **`requires-python` lowered from `>=3.11` to `>=3.9`.**
- `os/posix.py` restructured into an `os/posix/` package, one module per
  backend, now that there are five of them.
- New optional extra: `proxylib[requests]`, for `ProxyMapAdapter`.

### Fixed

Several of these change observable behavior for anyone relying on the old
(broken) results:

- `SimpleProxyMap(str)` always parsed with the PAC grammar (`PROXY host:port;
  DIRECT`), which has no concept of `"://"` — so `SimpleProxyMap("http://proxy:8080")`
  (the shape `HTTP_PROXY`/`HTTPS_PROXY` env vars actually use) silently
  produced a proxy with an **empty host**. This broke `EnvProxyConfig` for the
  common case.
- `SimpleProxyMap` treated a single `Proxy` as a sequence of its own tuple
  fields instead of wrapping it in a 1-tuple, since `Proxy` (a `NamedTuple`)
  is itself a `Sequence`.
- `_URI.resolved()` computed a corrected copy but never returned it.
- `EnvProxyConfig`'s `NO_PROXY` matching was anchored at the wrong position —
  a plain host entry like `example.com` could never match
  `https://example.com` at all. Separately, `from_env()` passed the raw,
  unsplit `NO_PROXY` string into a constructor expecting a list of entries.
  Also, `<local>` handling called `is_loopback()` as a method instead of a
  property, raising `TypeError` whenever it was actually exercised.
- `PAC.weekdayRange` indexed by weekday abbreviation instead of index.
- `netutils.get_default_port` relied solely on `socket.getservbyname`, which
  doesn't reliably know `https`/`socks4`/`socks5` across platforms.
- The `pac.load()` warning referenced installing `proxylib[pac]`; the real
  extra name is `proxylib[jspac]`.

[Unreleased]: https://github.com/jose-pr/proxylib/compare/v1.0.0-rc.1...HEAD
[1.0.0-rc.1]: https://github.com/jose-pr/proxylib/releases/tag/v1.0.0-rc.1
