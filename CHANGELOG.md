# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [1.0.0] - 2026-07-11

### Added

- `ProxyDict` (in `proxylib.proxy`): the plain proxies-dict integration,
  renamed and moved out of the `requests` module since it never actually
  depended on requests — usable with anything that accepts a
  `{scheme: proxy_uri}` mapping.
- `first_working_proxy()` (in `proxylib.netutils`): failover helper that
  probes a `ProxyMap` result (`PROXY a; PROXY b; DIRECT`) in order and
  returns the first entry that accepts a TCP connection.
- WPAD discovery results (including failures) are now cached per fqdn for 5
  minutes (`discover(..., cache_ttl=...)` to tune or disable) — previously,
  "auto-detect on but no WPAD server" re-probed DNS/HTTP with multi-second
  timeouts on every call.
- `proxylib.__version__`, resolved lazily from the installed package metadata.
- `Documentation` project URL (the GitHub Pages docs site) in the package
  metadata shown on PyPI.
- PEP 639 `license = "MIT"` / `license-files` metadata (replaces the license
  classifier).
- `.github/workflows/test.yaml`: on-demand test matrix (workflow_dispatch or a
  throwaway `ci-*` tag push), separate from the release-gate test job — lets
  platform-specific code (GNOME/gsettings, macOS) be validated on real CI.
- `NO_PROXY` entries now accept CIDR notation (`10.0.0.0/8`, `2001:db8::/32`),
  matched against IP-literal request hosts.
- `proxylib.set_default_no_proxy()` / `get_default_no_proxy()`: process-wide
  default `NO_PROXY` rules, merged into every `EnvProxyConfig`.
- `WinHttpProxyMap` (`proxylib.os.nt`): a `ProxyMap` backed by WinHTTP's own
  `WinHttpGetProxyForUrl` autoproxy engine — WPAD/DHCP-252 discovery, NTLM/
  Kerberos SSO for fetching the PAC, and PAC JS execution all happen in the
  OS, so no `dukpy` is needed on Windows.
- `CFNetworkProxyMap` (`proxylib.os.darwin`): the macOS equivalent, backed by
  `CFNetworkCopyProxiesForURL`/`CFNetworkExecuteProxyAutoConfigurationURL`.
- `provider="system"` param on `auto_proxy()`/`system_proxy()`: opts into the
  two native resolvers above (or `LibProxyMap` on POSIX, if its shared
  library is loadable) instead of proxylib's own Python-side detection/PAC
  path, which remains the default (`provider="python"`).
- gsettings-based detection (GNOME/MATE) now reads via one
  `gsettings list-recursively` call instead of up to 7 single-key
  `gsettings get` calls; `shutil.which` lookups for `gsettings`/`nmcli`/
  `dbus-send` are now cached (clearable, for tests).
- `pac.load()` now caches genuine network downloads (not `file:`/inline-JS
  sources) for 5 minutes by default (`cache_ttl=` param).
- `PAC.dnsResolve` results are now cached for 30 seconds by default
  (`cache_ttl=` param) — real-world PAC scripts often call it repeatedly for
  the same host.
- `ChainProxyMap(*maps)` (in `proxylib.proxy`): sequential fallback across
  `ProxyMap`s — a `KeyError` (no opinion) tries the next one, a definitive
  `[None]`/`[Proxy]` result stops the chain.
- `ConfigurableProxyMap(proxymap, ...)` (in `proxylib.proxy`): decorates any
  `ProxyMap` with opt-in caching (`cache_ttl=`), active reachability probing
  (`probe=`/`probe_timeout=`, via `netutils.first_working_proxy`),
  round-robin selection (`round_robin=`), browser-style HTTPS privacy
  stripping (`browser_compatibility=`), and an implicit local-address bypass
  (`bypass_local=`) plus `no_proxy=` rules (merged with the global
  `set_default_no_proxy()` defaults).
- `netutils.is_loopback_or_link_local()`: shared helper (loopback +
  `169.254/16`/`fe80::/10`) used by both `EnvProxyConfig`'s `<local>`
  handling and `ConfigurableProxyMap`'s `bypass_local=`.
- Extensible patching registry (`proxylib.patching`): `patch(proxymap,
  targets=None)`/`unpatch()`/`register_patcher(name, patch_func,
  unpatch_func)` globally wire an active `ProxyMap` into third-party HTTP
  clients. Built-in targets: `"requests"` (newly constructed `Session`s
  mount a `ProxyMapAdapter`) and `"urllib"` (installs a global opener).
  `ProxyMap` instances are now usable as a context manager
  (`with proxymap as active: ...`) equivalent to `patch()`/`unpatch()`.
- Pluggable PAC JS engines (`proxylib.pac.engines`): `JSProxyAutoConfig`/
  `JSContext` now run against a small `JSEngine` interface instead of
  `dukpy` directly. New optional `quickjs` backend (`proxylib[quickjs]`
  extra) alongside the existing `dukpy` one (`proxylib[dukpy]`). Select
  with the `PROXYLIB_JS_ENGINE` env var (comma-separated priority list,
  e.g. `PROXYLIB_JS_ENGINE=quickjs,dukpy`); defaults to preferring `dukpy`.
  `proxylib[jspac]` is now a meta-extra for "any working engine" (currently
  aliases `proxylib[dukpy]`).
- WPAD discovery now fails fast on a hanging DNS lookup: `socket.gethostbyname`
  has no timeout parameter, so it's now run in a worker thread with a
  `future.result(timeout=...)` deadline (same `timeout` the HTTP fetch
  already used) instead of blocking indefinitely.
- `first_working_proxy()` now has a circuit breaker: a proxy that fails its
  probe is skipped (without re-probing) for 30 seconds by default
  (`circuit_breaker_ttl=`), shared with `ConfigurableProxyMap(probe=True)`.
- `JSProxyAutoConfig`/`JSContext` accept an `overrides=` dict
  (`JSProxyAutoConfig(js, overrides={"dnsResolve": fn, ...})`) to replace a
  PAC utility function's Python-fallback implementation per-instance —
  simplifies offline/sandboxed testing and DNS mocking. A PAC script that
  redefines the same name in JS still overrides it, same as any other
  exported function.
- `release.yaml` now scrapes the pushed tag's `CHANGELOG.md` section into
  the GitHub Release body (this repo pushes commits directly, so GitHub's
  own auto-generated release notes are thin on every release).

### Changed

- `pac.load()`/WPAD fetches now go through an explicit no-proxy opener
  instead of the default (env-var-honoring) one — fetching a PAC/WPAD
  script must never itself be routed through a configured proxy.
- `PAC` lookups now pass the **full request URL** (path and query included) to
  `FindProxyForURL`, per the PAC spec, instead of truncating to
  `scheme://netloc` — PAC scripts with path-based rules now work.
- `EnvProxyConfig` no longer resolves DNS on every lookup; resolution only
  happens when a `NO_PROXY` `<local>` entry actually needs it.
- libproxy's shared library is now located lazily on first use instead of at
  `import proxylib` time.
- `JSContext`-exported callables (`JSProxyAutoConfig`'s Python-backed PAC
  utility functions) are now pre-bound once at construction instead of a
  fresh closure allocated on every attribute access.
- `proxylib.requests`/`proxylib.urllib` moved to
  `proxylib.integrations.requests`/`proxylib.integrations.urllib` — no shim
  kept at the old module paths (pre-1.0 breaking change; top-level
  `from proxylib import ProxyMapAdapter, ProxyMapHandler` is unaffected).
- `ProxyDict` moved from `proxylib.proxy` to `proxylib.integrations.dict`,
  and no longer subclasses `ProxyMap` (composition instead — its
  `__getitem__` returns `str`, which was an LSP violation as a `ProxyMap`
  subclass). Top-level `from proxylib import ProxyDict` is unaffected.
- `EnvProxyConfig` now raises `KeyError` (instead of returning DIRECT) for a
  scheme with no configured env proxy, so a future `ChainProxyMap` can fall
  through to the next map instead of env "winning" by default.
- `get_local_interfaces()` results are now cached for 10s (`cache_ttl=`
  param) — interface enumeration blocks, and `<local>`-in-`NO_PROXY` lookups
  call it per request.
- `<local>` (`NO_PROXY`) now also bypasses link-local addresses
  (`169.254/16`, `fe80::/10`) unconditionally, not just when they happen to
  match a local interface's subnet.

### Removed

- `RequestsProxies` — renamed to `ProxyDict` (see Added); the old name is
  gone. Only ever published under a release candidate (`1.0.0-rc.1`), so no
  stable release carried it.
- `proxylib[requests]` extra. `requests` support has always worked whenever
  the package happens to be installed (guarded by `try/except ImportError`);
  installing `requests` isn't a proxylib feature, so there was nothing for
  this extra to add over `pip install requests` itself.

### Fixed

- `ProxyMapAdapter` no longer loses to environment-injected proxies:
  `requests.Session.merge_environment_settings` merges `HTTP_PROXY`/
  `HTTPS_PROXY` into the `proxies` dict at the *scheme* level before
  `adapter.send()` runs, so the old `proxies.setdefault(resolved.scheme, ...)`
  always lost when `trust_env=True` (the `requests` default), and a DIRECT
  result didn't disable the env proxy at all. Now writes the more-specific
  `scheme://hostname` key `select_proxy()` checks first. As a consequence,
  only an explicit `proxies=` entry at that *same* key still overrides the
  `ProxyMap`'s decision — a less-specific one (e.g. a bare `"http"` key)
  no longer does.
- Proxy URLs with a trailing slash (`HTTP_PROXY=http://proxy:8080/`, a very
  common shape) were misclassified as PAC-file URLs and routed to the PAC
  loader, which tried to fetch the proxy itself as a PAC script and failed.
  Both the `ProxyMap(...)` factory and `EnvProxyConfig` are fixed
  (`EnvProxyConfig` additionally never treats proxy values as PAC sources —
  `PROXY_PAC`/OS PAC settings cover that separately).
- `URL.from_str("example.com")` (bare hostname) now raises a clear
  `ValueError` instead of crashing with `AttributeError` later.
- `JSContextMeta` compared the first *character* of attribute names against
  `_JSCONTEXT_EXCLUDE` instead of the name itself (dormant — the exclude list
  was unused).
- `PAC.dnsDomainLevels` counted split-length instead of dots (`sub.example.com`
  wrongly returned 3 instead of 2, per the PAC spec's own definition).
- `PAC.localHostOrDomainIs` used a string-prefix check (`hostdom.startswith(host)`),
  so e.g. `"ww"` wrongly matched `"www.example.com"`; now compares the exact
  host part.

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

[Unreleased]: https://github.com/jose-pr/proxylib/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/jose-pr/proxylib/releases/tag/v1.0.0
[1.0.0-rc.1]: https://github.com/jose-pr/proxylib/releases/tag/v1.0.0-rc.1
