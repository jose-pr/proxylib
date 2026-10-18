# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

Work toward 2.0, which breaks the 1.x API.

### Added

- `proxylib.exceptions`: `ProxylibError` and its subclasses `ProxyParseError`
  (also a `ValueError`), `PACError`, `NoReachableProxyError` (also a
  `LookupError`) and `MissingExtraError` (also an `ImportError`), re-exported at
  top level. None of them is a `KeyError`, which keeps meaning "no opinion".
- `proxylib.clear_caches()` drops every module-level cache in one call.
- `proxylib.__all__` declares the public surface.
- PAC is split into `pac.functions` (the builtins), `PacScript` (one script in a
  JS engine) and `PacProxyMap` (the map, which also takes a Python
  `FindProxyForURL` function). `pac.loads(text)` / `proxylib.loads_pac` load a
  script from text; `pac.engines.names()` lists the installed engines.
- PAC scripts run in a helper process with a time limit (`script_timeout=`,
  default 1 s per call): a script that hangs raises `PACError` and stays failed
  instead of hanging the program. Neither engine can be stopped in-process.
- `lookup(proxymap, url)` reads any proxy map's answer as a tuple of `Proxy` or
  `None` (DIRECT). It accepts every answer shape: `None`, a `Proxy`, a proxy URL,
  a PAC result string, any object with a `url` attribute, or an iterable of
  those; an empty answer is DIRECT. A plain mapping is also asked with the keys
  `requests` uses (`scheme://host`, `scheme`, `all://host`, `all`).
- `Proxy.parse(text)` and `Proxy.parse_pac_result(text)`, and the `ProxyLike` /
  `ProxyAnswer` type aliases.
- `BypassRules`: one bypass-list type with parsers for `NO_PROXY` (curl), Windows
  `ProxyOverride`, macOS `ExceptionsList`, GNOME `ignore-hosts` and KDE `NoProxyFor`
  (including `ReversedException`); IPv6 CIDR works. The OS backends now read their
  own bypass lists with their own syntax (a WinINet `*.corp;10.*` list, a macOS
  `*.local`, a KDE reversed list).

### Changed

- `ProxyMap` is a structural protocol with only `__getitem__`: a plain `dict`,
  or any object indexable by URL, is a proxy map. `get()`, `in` and the
  context manager (use `patch()`/`unpatch()`) are gone. `ProxyMap(src)` still
  builds a map from a configured value, now without any I/O: a PAC location is
  loaded on its first lookup, and an existing map is returned unchanged.
- `Proxy` is an immutable value class, `Proxy(scheme, host, port=None,
  username=None, password=None)`; absent port and credentials are `None`
  (1.x: `0` and `""`). `as_uri()` is now `uri()` and percent-encodes the
  credentials; `Proxy("direct", ...)` no longer returns `None`.
- Built-in maps return tuples. A malformed proxy or request URL raises
  `ProxyParseError` (a `ValueError`). Bracketed IPv6 hosts parse
  (`http://[::1]:8080`), and a scheme-less `host:port` is an `http` proxy.
- `EnvProxyConfig(env=None, *, proxies=None, no_proxy=None)` replaces the three
  positional arguments and `from_env()`: it reads `env` (default `os.environ`,
  any mapping accepted), with `proxies`/`no_proxy` applied over it. Every `<scheme>_proxy` is read, plus `all_proxy`; `ws`/`wss`
  use the `http`/`https` proxies; a lowercase name now wins over uppercase (stdlib
  and curl order); a PAC URL may be given as a proxy value.
- `<local>` in a bypass list now means a host name without a dot (its WinINet
  meaning); the 1.x meaning (loopback, link-local or same subnet) is `<subnet>`.
  `ConfigurableProxyMap(bypass_local=True)` uses `<subnet>`.
- Loopback (`localhost`, `127.0.0.0/8`, `::1`) bypasses the proxy wherever bypass
  rules apply, unless `<-loopback>` is listed. In `NO_PROXY`, `*` among other
  entries is ignored with a warning, as curl and requests do.
- `pac.load(location)` takes a URL or a path only; script text goes to
  `pac.loads()`. Download options are named (`timeout=`, `cache_ttl=`); the
  `**urllib_kwds` pass-through is gone. A body over 1 MiB, a script error, a
  script without `FindProxyForURL` and a time-limit overrun raise `PACError`.
- With no JS engine installed, loading a PAC raises `MissingExtraError`;
  `on_missing_engine="direct"` restores the old warn-and-DIRECT behaviour.
- `PROXYLIB_JS_ENGINE` or `engine=` naming an unknown engine raises `ValueError`
  (it was ignored). Engines are imported only when a script needs one.
- `wpad.discover()` returns a `PacProxyMap`, takes keyword-only options and skips
  a domain whose PAC fails to run.
- proxylib now depends on `netimps>=0.4.0,<0.5` for host:port handling, local
  interfaces (real prefix lengths on every OS, no extra needed), bounded name
  lookups and TCP probes. `import proxylib` imports neither it nor `requests`.
- Extras: `proxylib[pac]` installs the quickjs engine and `proxylib[dukpy]` the
  dukpy one; `jspac`, `quickjs` and `ifaddr` are gone.
- `ProxyMapAdapter` is always a class: constructing it without `requests`
  raises `MissingExtraError` instead of the name being `None`.
- `patch()` registers its `"requests"` target whether or not `requests` is
  installed; with no `targets` a missing client is skipped, and naming it
  raises `MissingExtraError`.
- WPAD and PAC `dnsResolve` lookups are bounded by a timeout.

### Removed

- `PAC`, `JSProxyAutoConfig`, `pac.javascript.JSContext`,
  `pac.clear_download_cache()`, `pac.clear_dns_cache()` and
  `pac.engines.get_engine_class()`: use `PacProxyMap` with a `PacScript` or a
  Python function, `proxylib.clear_caches()` and `pac.engines.get_engine()`.
- `set_default_no_proxy()` / `get_default_no_proxy()`: pass bypass rules where a
  map is built (`EnvProxyConfig(no_proxy=...)`, `ConfigurableProxyMap(no_proxy=...)`).
- `UriSplit`, `Proxy.from_str`, `Proxy.find_all` and `Proxy.as_uri`: use
  `Proxy.parse`, `Proxy.parse_pac_result` and `Proxy.uri`.
- `proxylib.netutils` and the top-level `first_working_proxy`; use
  `ConfigurableProxyMap(probe=True)` for reachability probing.

## [1.1.0] - 2026-10-18

### Added

- `ConfigurableProxyMap(cache_maxsize=1024)` bounds the per-URL cache (least
  recently used dropped first).
- `LibProxyMap.close()` frees the libproxy factory the map now keeps.
- `PAC` and `JSProxyAutoConfig` are `ProxyMap`s, so they gain the protocol's
  `with` support (see Fixed).

### Security

- `EnvProxyConfig.from_env()` ignores `HTTP_PROXY` inside a CGI request
  (`REQUEST_METHOD` set), where a client's `Proxy:` header can set it
  (httpoxy, CVE-2016-5385). Only an exact lowercase `http_proxy` is used there,
  as in `urllib.request.getproxies_environment`; on Windows, where environment
  names are case-insensitive, neither is.
- WPAD discovery no longer walks up to a public suffix: for
  `host.example.co.uk` it tries `wpad.example.co.uk` only, never
  `wpad.co.uk`, which anyone can register.
- `Proxy`'s `repr()` and `str()` show `password='***'` instead of the password.
  `as_uri()` still includes it.

### Fixed

- One PAC map shared between threads no longer crashes the interpreter. Both
  JS engines abort when two threads enter one context; calls into the engine
  are now serialised per PAC instance.
- macOS `system_proxy()` no longer raises on the default bypass list:
  abbreviated IPv4 CIDR such as `169.254/16` is accepted in every `NO_PROXY`
  list, and an entry that still cannot be parsed is skipped with a warning
  instead of failing the whole configuration.
- `pac.load()` downloads time out after 10 seconds unless `timeout=` is
  passed, refuse a body over 1 MiB (Chromium's limit) with `ValueError`, and
  decode a script that is not UTF-8 as Latin-1 instead of raising.
- `PAC` and `JSProxyAutoConfig` are `ProxyMap`s, as the docs always said:
  `isinstance(pac, ProxyMap)` is true and `with load_pac(...):` patches like any
  other map, so `with auto_proxy():` no longer fails when a PAC is in effect.
  `JSProxyAutoConfig.get()` no longer raises: it was being routed into the JS
  engine.
- A PAC result entry with an unknown keyword or no host (`"garbage"`,
  `"PROXY "`) is skipped, and a result with nothing usable left — including an
  empty string or a non-string return — means DIRECT, as in browsers. It
  previously produced host-less `Proxy` objects or an empty list.
- `PAC.shExpMatch` treats only `*` and `?` as wildcards and matches
  case-sensitively on every platform, as Mozilla and Chromium do. It used
  `fnmatch`, which is case-insensitive on Windows and reads `[...]` as a
  character class.
- `ProxyDict` treats a key its map cannot parse as a URL (`"http"`, `"all"`,
  which `requests` looks up first) as missing. `requests.get(...,
  proxies=ProxyDict(EnvProxyConfig.from_env()))` raised `ValueError`.
- `ConfigurableProxyMap(cache_ttl=..., round_robin=True)` rotates on every
  lookup; the cache had frozen the first rotation. The cache is bounded by the
  new `cache_maxsize=1024` keyword (least recently used dropped first).
- `ConfigurableProxyMap` applies the `set_default_no_proxy()` rules even when
  built without `no_proxy=` or `bypass_local=`.
- Windows: a WinHTTP answer listing several proxies (`p1:8080;p2:8080`) keeps
  every applicable entry in order; only the first was used. `WinHttpProxyMap`
  sets 10-second session timeouts, so a PAC fetch cannot hang on name
  resolution.
- macOS: an HTTPS proxy from `CFNetworkProxyMap` is returned as an `http://`
  proxy. It is a plain proxy reached with `CONNECT`, and clients were trying to
  speak TLS to it. An entry of an unknown type is skipped instead of meaning
  DIRECT.
- Linux: GNOME/MATE settings are re-read after 10 seconds instead of being
  cached for the life of the process; a `kioslaverc` that is not UTF-8 counts
  as not configured instead of raising; the `nmcli` path checks every active
  connection, as the D-Bus path does.
- `LibProxyMap` keeps one libproxy factory per map instead of building one per
  lookup (which re-fetched the PAC every time), frees it in the new `close()`,
  and treats a failed libproxy call as no opinion (`KeyError`) instead of
  DIRECT.
- `system_proxy()` and `auto_proxy()` raise `ValueError` for an unknown
  `provider`; a typo used to fall back to `"python"` silently.
- An IPv6 proxy host is bracketed in `Proxy.url` and `as_uri()`
  (`http://[::1]:8080`).
- `pac.load()` no longer caches a `file://` URL, as documented for file
  sources.
- Public annotations resolve with `typing.get_type_hints` on Python 3.9; they
  were written as `"X|None"` strings, which 3.9 cannot evaluate.

## [1.0.2] - 2026-08-16

### Added

- `NO_PROXY="*"` now bypasses the proxy for every host, matching curl,
  `requests.utils.should_bypass_proxies` and the stdlib's
  `urllib.request.proxy_bypass_environment`. It previously parsed to an ordinary
  host entry that could never match a real hostname, so the common "stop
  proxying everything right now" escape hatch silently did nothing. Works via
  `NO_PROXY`/`no_proxy`, an explicit `EnvProxyConfig(..., no_proxy=["*"])`,
  `ConfigurableProxyMap(no_proxy=["*"])`, and `set_default_no_proxy(["*"])`;
  it is an explicit DIRECT result, so it applies even when no proxy is
  configured for the scheme, and it is checked ahead of every other rule so it
  never triggers a `<local>` DNS lookup.

### Fixed

- URI scheme parsing no longer accepts a comma. The scheme character class was
  written `[A-Za-z0-9+-.]`, in which `+-.` is the *range* `0x2B`–`0x2E` and so
  also matched `,` (`0x2C`) — `http,x://host:1` parsed as a scheme of `http,x`.
  RFC 3986 allows `ALPHA`/`DIGIT`/`+`/`-`/`.` only.
- The GNOME/MATE gsettings backend no longer builds `http://host:None` when the
  schema has a proxy host but no usable port (key absent, or `0` for "never
  configured"); the port suffix is omitted so the scheme's default applies.
- Documentation drift that shipped in the wheel and rendered on the docs site:
  the `proxylib` API header no longer points at a repo-root `AGENTS.md` that
  doesn't exist (it links the project README instead), the `requests`
  integration no longer tells users to install a `proxylib[requests]` extra
  that was removed before 1.0 (`requests` support activates whenever `requests`
  is installed), the POSIX backend no longer claims libproxy is used via a
  `proxy` CLI (it binds the shared library through `ctypes`), and the PAC
  module/`load()` docstrings are engine-agnostic again — `dukpy` stopped being
  the only option when the engine split landed.

## [1.0.1] - 2026-07-11

### Changed

- `proxylib[quickjs]` now installs `quickjs-ng` (an actively maintained, drop-in-compatible
  fork — same `import quickjs`/API) on Python 3.10+, which ships wheels through 3.13/3.14;
  Python 3.9 keeps the original `quickjs` package, which still has a cp39 wheel. `quickjs`
  is consequently now part of the CI/release install lines.
- The default JS engine priority (`PROXYLIB_JS_ENGINE` unset) now prefers `quickjs` over
  `dukpy` when both are installed, instead of the other way around — `quickjs` is the
  closer-to-spec/faster engine when its dependency happens to be present. `dukpy` remains
  what `proxylib[jspac]` installs and the runtime fallback when quickjs isn't available.

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

[Unreleased]: https://github.com/jose-pr/proxylib/compare/v1.1.0...HEAD
[1.1.0]: https://github.com/jose-pr/proxylib/compare/v1.0.2...v1.1.0
[1.0.2]: https://github.com/jose-pr/proxylib/compare/v1.0.1...v1.0.2
[1.0.1]: https://github.com/jose-pr/proxylib/compare/v1.0.0...v1.0.1
[1.0.0]: https://github.com/jose-pr/proxylib/releases/tag/v1.0.0
[1.0.0-rc.1]: https://github.com/jose-pr/proxylib/releases/tag/v1.0.0-rc.1
