# `proxylib` — public API header

Header-file-style reference for the `proxylib` package: every top-level export with its
signature, arguments, contract, and gotchas, so this module can be consumed without
reading its source. Kept current with the public API. For the project overview and
install instructions, see <https://github.com/jose-pr/proxylib#readme>.

A **proxy map** is anything indexable by request URL — a plain `dict` included; no
proxylib base class is needed. `proxymap[url]` answers with:

- `None` — DIRECT;
- one proxy — a `Proxy`, a proxy URL (`"http://user:pass@host:3128"`, scheme-less
  means `http`), a PAC result string (`"PROXY a:1; SOCKS5 b:2; DIRECT"`), or any
  object with a `url` attribute (credentials from the URL, else from its
  `username`/`password` attributes);
- an iterable of those, tried in order, where a `None` entry is DIRECT and an empty
  iterable is DIRECT;
- or it **raises `KeyError`**: no opinion (a chain asks the next map).

Read an answer with **`lookup(proxymap, url)`**, never by indexing yourself. Every
built-in map returns `tuple[Proxy | None, ...]`. `SimpleProxyMap` and `PacProxyMap` always
answer; `EnvProxyConfig` raises `KeyError` for a scheme with no proxy variable set.

## Core types (`proxylib.proxy`, re-exported at top level)

- **`Proxy(scheme, host, port=None, username=None, password=None)`** — one proxy;
  immutable, hashable, picklable. `scheme` is lower-cased (`"proxy"` → `"http"`,
  `"socks"` → `"socks4"`); an empty scheme or host, or a port outside 1–65535, raises
  `ProxyParseError`. Absent port and credentials are `None`.
  - `.url` — `scheme://host[:port]`, no credentials, IPv6 host bracketed; `str()` is
    the same.
  - `.uri()` — `.url` with the credentials, percent-encoded.
  - `repr()` shows `password='***'`, never the password.
  - **`Proxy.parse(text)`** — a proxy URL; scheme-less means `http`; `[::1]:8080`
    form for IPv6; a path other than `/` raises `ProxyParseError` (that is a PAC
    location).
  - **`Proxy.parse_pac_result(text) -> tuple[Proxy | None, ...]`** — a PAC
    `FindProxyForURL` result; keywords case-insensitive (`DIRECT`, `PROXY`, `HTTP`,
    `HTTPS`, `SOCKS` = `socks4`, `SOCKS4`, `SOCKS5`); an entry with an unknown
    keyword or no host is dropped with a `UserWarning`; nothing usable is `(None,)`.
- **`ProxyMap`** — `runtime_checkable` `Protocol` with only `__getitem__(url)`.
  `isinstance(x, ProxyMap)` is true for any object with `__getitem__` (a `dict`, and
  also a `str` — it checks the shape only).
- **`ProxyMap(src=None) -> ProxyMap`** — calling the protocol builds a map from a
  configured value, with no I/O: `None`, a proxy URL, a PAC result string, a `Proxy`
  or a list/tuple of them → `SimpleProxyMap`; a PAC location (`file:` URL, inline
  script, or `http(s)` URL with a path beyond `/`) → a map that loads it on first
  lookup; anything else with `__getitem__` is returned unchanged (never
  re-initialised).
- **`ProxyLike`**, **`ProxyAnswer`** — the type aliases for one proxy and for an
  answer, as listed above.
- **`lookup(proxymap, url) -> tuple[Proxy | None, ...]`** — never empty. A
  `Mapping` with no entry for the full URL is also asked with the keys `requests`
  uses, most specific first: `scheme://host`, `scheme`, `all://host`, `all`. Raises
  `KeyError` for no opinion, `TypeError` for an answer that names no proxy,
  `ProxyParseError` for malformed proxy text.
- **`async alookup(proxymap, url) -> tuple[Proxy | None, ...]`** — `lookup` run in a
  worker thread (`asyncio.to_thread`), for asyncio code; same answer and errors. Safe
  to call from many tasks at once on one map.
- **`SimpleProxyMap(proxy=None)`** — the same answer for every URL; takes anything
  `lookup` reads. `.proxies` is the parsed tuple.
- **`ChainProxyMap(*maps)`** — asks each map in order through `lookup`; the first
  with an opinion answers (DIRECT included). If every map has no opinion, neither
  does the chain. Links can be `dict`s.
- **Wrappers** (`proxylib.wrappers`, all at top level) — proxy maps over any inner map
  (a `dict` included), read through `lookup`; the inner map's `KeyError` (no opinion)
  passes through. Compose them in the order you mean: `RoundRobin(Cached(m, ttl=60))`
  rotates the cached answer.
  - **`Bypass(inner, rules)`** — `(None,)` for a URL `rules` matches (`BypassRules`,
    `NO_PROXY` text, or its entries; loopback included unless `<-loopback>`), else
    `lookup(inner, url)`. Loopback/link-local/same-subnet hosts: the `<subnet>` token.
  - **`Cached(inner, *, ttl, maxsize=1024)`** — the inner answer per URL for `ttl`
    seconds, at most `maxsize` URLs (least recently used dropped first); no opinion is
    not cached; thread-safe; `.clear()`, `len()`. `ttl <= 0` or `maxsize < 1` raises
    `ValueError`.
  - **`RoundRobin(inner)`** — rotates the answer one place per lookup, so successive
    requests lead with a different entry and keep the rest as fallbacks; one rotation
    per distinct answer (the 1024 most recent), shared by every URL with that answer;
    thread-safe. A one-entry answer is unchanged.
  - **`Probed(inner, *, timeout=5.0)`** — `(first reachable entry,)`: the first whose
    port accepts a TCP connection within `timeout` (DIRECT counts as reachable; a
    failed proxy is skipped for 30 s). None reachable → **`NoReachableProxyError`** (a
    `LookupError`, not `KeyError`).
  - **`configure(inner, *, bypass=None, cache_ttl=None, round_robin=False, probe=False,
    probe_timeout=5.0) -> ProxyMap`** — the asked-for wrappers in one fixed order,
    outermost first: `Bypass`; then `Probed(RoundRobin(Cached(inner)))` when rotating
    (each lookup probes the rotated answer), else `Cached(Probed(inner))` (the probed
    answer is cached). With nothing asked for, returns `inner`.

## Bypass rules (`proxylib.bypass`, re-exported at top level)

- **`BypassRules.parse(text, *, dialect="no_proxy", reversed=False) -> BypassRules`** —
  `text` is the list as one string or as entries. Dialects: `"no_proxy"` (curl,
  `,`/space separated), `"wininet"` (Windows `ProxyOverride`, `;` separated),
  `"macos"` (`ExceptionsList`), `"gsettings"` (GNOME/MATE `ignore-hosts`), `"kde"`
  (`NoProxyFor`; `reversed=True` for `ReversedException`, which makes the list name
  the hosts that *use* the proxy). Unknown dialect → `ValueError`. Unparsable
  entries are skipped with one `UserWarning` naming them.
- Entry kinds: host (exact; in `no_proxy`/`kde`, and for a leading `.` or `*.` in
  every dialect, the host and its subdomains); glob with `*`/`?` (`[` literal,
  case-insensitive); CIDR including abbreviated IPv4 (`169.254/16`) and IPv6
  (matched against IP-literal hosts only — no DNS); optional `:port` (a URL without
  a port has its scheme's default); `<local>` = a host name with no dot;
  `<subnet>` = resolves to loopback, link-local or an address on a local interface's
  network (does DNS); `<-loopback>` turns off the implicit loopback bypass; `*` as
  the whole list = every host (among other entries it is ignored in `no_proxy`,
  with a warning, as curl and requests do; elsewhere it is a glob).
- **Implicit loopback**: `localhost`, `*.localhost`, `127.0.0.0/8` and `::1` always
  bypass unless `<-loopback>` is listed (Chromium, Go).
- **`.matches(url) -> bool`**; `a | b` combines; `bool(rules)` is false when empty;
  `BypassRules.NONE`; immutable, hashable.
- Differences from `requests.utils.should_bypass_proxies` (tested): a default port
  matches `host:443`; entries are case-insensitive; loopback bypasses implicitly;
  IPv6 CIDR matches bracketed hosts; `*` alone bypasses everything (requests leaves
  that to urllib).

## Env var config (`proxylib.env`, re-exported at top level)

- **`EnvProxyConfig(env=None, *, proxies=None, no_proxy=None)`** — a proxy map read
  from an environment mapping: `env=None` reads `os.environ`, any other mapping is
  read instead (`{}` reads nothing). It takes every `<scheme>_proxy`, `all_proxy`
  and `no_proxy`; a lowercase name wins over its uppercase form. Inside a CGI
  request (`REQUEST_METHOD` set) an uppercase `HTTP_PROXY` is ignored (httpoxy);
  with `os.environ` on Windows, whose names are case-insensitive, `http_proxy` is
  ignored then too. There is no PAC environment variable: put a PAC URL in
  `HTTP_PROXY` and the others.
  - `proxies` (scheme or `"all"` → `Proxy`, proxy URL with scheme-less = `http`, or
    PAC location loaded on first use) is applied over the environment's;
    `no_proxy` (`BypassRules` or `NO_PROXY` text) replaces the environment's.
    Pass `env={}` to build one from explicit values only.
  - Lookup: bypassed → `(None,)`; else the scheme's proxy (`ws` falls back to
    `http`, `wss` to `https`); else `"all"`; else **`KeyError`** (no opinion — the
    environment cannot say DIRECT). A key that is not a URL raises
    `ProxyParseError`. `repr()` hides passwords.

## System settings (`proxylib.system`; `auto_proxy`, `system_config`, `ProxyConfig` at top level)

- **`auto_proxy(*, system=True, no_proxy=None, wpad=False, timeout=10.0,
  on_missing_engine="raise", environ=None) -> ProxyMap`** — the proxy map for this
  machine; it answers every URL (never `KeyError`). Precedence, the same on every OS:
  1. If any proxy variable (`HTTP_PROXY`, `HTTPS_PROXY`, `ALL_PROXY`, ... — any
     `*_proxy` but `no_proxy`, non-empty) is set in `environ` (default `os.environ`),
     the variables alone decide (`EnvProxyConfig(environ)`, as
     `urllib.request.getproxies()` does): a scheme with no variable is DIRECT and the
     OS is never consulted, no OS resolver is built. A variable may hold a PAC
     location (`file:` URL or an `http(s)` URL with a path), loaded on first lookup.
  2. Otherwise, with `system=True`, the OS's own resolver answers — `WinHTTPProxyMap`
     on Windows, `CFNetworkProxyMap` on macOS, `LibProxyMap` elsewhere when libproxy
     is installed — and a URL it cannot answer (`KeyError`) goes to
     `system_config().to_proxymap(wpad=, timeout=, on_missing_engine=)`. With no OS
     resolver, or `system=False`, only that map is used. `system=False` never calls
     an OS resolver (libproxy included).
  3. `no_proxy` (`BypassRules`, `NO_PROXY` text, or its entries) wraps the result:
     matching URLs are DIRECT.
  There is no `provider=` argument and no `PROXY_PAC` variable.
- **`system_config() -> ProxyConfig`** — this machine's OS/desktop settings;
  environment variables are not read. Windows: the user's Internet Options (WinHTTP
  `WinHttpGetIEProxyConfigForCurrentUser`). macOS: `scutil --proxy`. Elsewhere: GNOME
  (`org.gnome.system.proxy`), MATE, KDE (`kioslaverc`; `ProxyType=4` defers to the
  environment and reads as no settings), NetworkManager (`nmcli`, else `dbus-send`) —
  the first with a proxy configured, else the first with settings. Nothing readable →
  `ProxyConfig()`. Programs run with a 5 s limit, no stdin and `LC_ALL=C`; any
  failure reads as "no settings". Decisions are logged at DEBUG on the
  `proxylib.system` logger.
- **`ProxyConfig(source="none", state="unset", auto_detect=False, pac_url=None,
  pac_script=None, proxies={}, bypass=BypassRules.NONE)`** — frozen dataclass.
  - `source`: `"windows"`, `"macos"`, `"gnome"`, `"mate"`, `"kde"`,
    `"networkmanager"` or `"none"`.
  - `state`: `"direct"` (the settings say no proxy — Windows and macOS with nothing
    switched on, GNOME `mode='none'`, KDE `ProxyType=0`), `"configured"`, or
    `"unset"` (no settings to read). Anything else raises `ValueError`.
  - `proxies`: read-only mapping from a request scheme (`http`, `https`, `ftp`) to a
    `Proxy`, plus `"socks"` — the proxy for every scheme without its own entry. String
    values are parsed. No cross-filling: an `https`-only setting leaves `http` DIRECT.
    SOCKS keeps the version the OS means: Windows `socks=` is `socks4`; macOS, GNOME,
    MATE and KDE SOCKS are `socks5`. An `https`/`ftp` entry is an HTTP proxy.
  - `bypass`: the OS's list parsed in its dialect (`wininet`, `macos`, `gsettings`,
    `kde`); it applies to `proxies` only (as on every OS), and loopback is always
    bypassed.
  - **`.to_proxymap(*, wpad=False, timeout=10.0, on_missing_engine="raise") ->
    ProxyMap`** — `state="direct"` → DIRECT for every URL. Otherwise asks, in order:
    WPAD (`discover_pac`), only when `auto_detect` is set or `wpad=True` with
    `state="unset"`; the PAC at `pac_url`; `pac_script`; then `proxies` (bypass
    first; a scheme with no entry is DIRECT). A source that fails (no WPAD server, a
    PAC that does not download or raises `PACError`) passes to the next and is retried
    after 30 s. Nothing is fetched until the first lookup. A missing JS engine is not
    swallowed: `MissingExtraError` unless `on_missing_engine="direct"`. `timeout`
    bounds each WPAD probe and PAC download.
- **OS resolvers** (`proxylib.system`) — each answers `tuple[Proxy | None, ...]` and
  raises `KeyError` when it cannot answer, never DIRECT for a failure:
  - **`WinHTTPProxyMap()`** — `WinHttpGetProxyForUrl`: WinHTTP does WPAD (DHCP and
    DNS), fetches the PAC with NTLM/Kerberos when challenged and runs it (no JS engine
    needed); when the settings name neither, or WinHTTP fails, the manual proxies
    answer. One session per map (10 s timeouts); `close()` releases it, after which a
    lookup raises `KeyError`. Construction raises `OSError` off Windows. Several
    proxies in WinHTTP's answer are kept, in order.
  - **`CFNetworkProxyMap(deadline=5.0)`** — `CFNetworkCopyProxiesForURL`, running a
    configured PAC natively; a PAC run longer than `deadline` seconds → `KeyError`.
    Off macOS every lookup raises `KeyError`.
  - **`LibProxyMap(lib=None)`** — libproxy's C API via `ctypes`; `lib` defaults to
    the library found on the linker path. Not installed, or no answer → `KeyError`.
    One `pxProxyFactory` per map, made on first lookup, freed by `close()` (or garbage
    collection).
## PAC support (`proxylib.pac`)

- **`load(location, *, timeout=10.0, cache_ttl=300.0, script_timeout=5.0, engine=None,
  on_missing_engine="raise") -> PacProxyMap`** (top-level `proxylib.load_pac`) — the
  PAC at a URL (`http`, `https`, `file`) or a path (`str`/`os.PathLike`; `file:path`
  without `//` is a path). Never script text. `timeout` bounds the download; the
  fetch **never goes through a proxy**; a body over 1 MiB raises `PACError`; UTF-8
  with a Latin-1 fallback; downloads (not `file:`) are cached per URL for
  `cache_ttl` seconds.
- **`loads(text, *, script_timeout=5.0, engine=None, on_missing_engine="raise") ->
  PacProxyMap`** (top-level `proxylib.loads_pac`) — the PAC from script text.
- **`PacScript(source, *, engine=None, functions=None, timeout=5.0,
  on_missing_engine="raise")`** — one script, run in a **helper Python process**
  (`sys.executable`) so it can be stopped: neither engine can be interrupted
  in-process. `.find_proxy_for_url(url, host) -> str` (a non-string result is
  `"DIRECT"`). `timeout` bounds each call and loading (each DNS lookup a builtin
  makes is bounded at 2 s): an overrun ends the helper and raises `PACError`; for the
  next 30 s every call raises `PACError` at once, then the script is started afresh.
  A script that overruns while loading is not loaded. A script
  error, or a script with no `FindProxyForURL` function, raises `PACError`.
  `functions` adds to or overrides the builtins and must be picklable module-level
  functions the helper can import. No engine installed: `"raise"` →
  `MissingExtraError` (extra `pac`), `"direct"` → `UserWarning` and every answer is
  `"DIRECT"`. Thread-safe (calls are serialised); `.close()` ends the helper
  (garbage collection does too). `PacScript.from_file(path, *, encoding="utf-8-sig",
  **options)`, `PacScript.from_url(url, *, timeout=10.0, max_bytes=MAX_PAC_BYTES,
  cache_ttl=300.0, **options)` (the script budget is `script_timeout=` there).
- **`PacProxyMap(script, *, browser_compatibility=False)`** — the proxy map; `script`
  is a `PacScript` or any `callable(url, host) -> str` (a Python `FindProxyForURL`).
  `host` is the URL's host, lower-cased; the full URL is passed, except that
  `browser_compatibility=True` reduces an `https` URL to `https://host/` (Chrome and
  Firefox privacy rule). Answers through `Proxy.parse_pac_result`; never `KeyError`.
- **`functions`** — read-only mapping of the PAC builtins by their PAC names (the
  Netscape set — `dnsResolve`, `myIpAddress`, `isInNet`, `shExpMatch`,
  `dnsDomainIs`, `weekdayRange`, `dateRange`, `timeRange`, ... — plus Microsoft's
  `*Ex` functions, `sortIpAddressList`, `getClientVersion`). `shExpMatch` treats only
  `*` and `?` as wildcards and is case-sensitive, as in browsers. `dnsResolve` caches
  answers and failures for 30 s (`clear_caches()` drops them).
- **`proxylib.pac.engines`** — `names()` (installed engines), `get_engine(name=None)`,
  `JSEngine` protocol. Selection: `engine=`, else `PROXYLIB_JS_ENGINE` (comma-separated
  priority list), else quickjs then dukpy; an unknown name raises `ValueError`.
  Neither engine is imported until a script needs it. `proxylib[pac]` installs
  `quickjs-ng` (Python 3.10+) / `quickjs` (3.9); `proxylib[dukpy]` installs `dukpy`
  (the one with a Windows ARM64 wheel).
- **`discover(fqdn=None, *, timeout=3.0, cache_ttl=300.0, on_missing_engine="raise")
  -> PacProxyMap | None`** (`proxylib.pac.wpad`, top-level `proxylib.discover_pac`) —
  DNS+HTTP WPAD: tries `http://wpad.<domain>/wpad.dat` for each parent domain of
  `fqdn` (default: this host's FQDN), most specific first, stopping before a public
  suffix (a bare TLD or a ccTLD registry level such as `co.uk`); a domain whose PAC
  fails to download or run is skipped. Results, failures included, are cached per
  fqdn. **DHCP option 252 is not implemented.**

## Patching clients (`proxylib.patching`; `patch`, `unpatch`, `Patch`, `register_patcher` at top level)

- **How it works.** Each client — built in: `"requests"` (new `requests.Session`s mount a
  `ProxyMapAdapter` for `http://` and `https://`) and `"urllib"` (a global opener with a
  `ProxyMapHandler`, installed only when the program has not installed its own) — gets
  proxylib's integration **once**, and it always asks the **active map**: the newest
  `patch()` covering that client, else the **default**.
- **When.** At `import proxylib` for clients already imported, and through an import
  hook for the rest (so `import proxylib` never imports `requests`). With the **`patch`
  extra** (`importpatch>=0.2,<0.3`), proxylib's `importpatch` entry points
  (`requests`, `urllib.request` = `proxylib.integrations.autopatch`) install it whenever
  the client is imported, in any program of the environment, even one that never
  imports proxylib.
- **The default map** depends on `PROXYLIB_AUTO_PATCH` (read when the integration is
  installed): unset or empty → **no opinion**, so the client chooses its proxy exactly as
  it would without proxylib (requests from its `proxies` and the environment, urllib from
  `urllib.request.getproxies()`); `1`/`true`/`yes`/`on` → **`auto_proxy()`** (built on the
  first lookup); `0`/`false`/`no`/`off` → nothing is installed until `patch()` is called.
  Any other value warns and is ignored.
- **`patch(proxymap, *, targets=None) -> Patch`** — makes `proxymap` the active map of
  every client in `targets` (default: all registered) until undone. Patches nest; the
  newest covering a client wins. A named target whose client is not installed raises
  `MissingExtraError` (with the default, it is skipped); an unknown name raises
  `ValueError`. Naming a target imports its client.
- **`Patch`** — `.undo()` (newest first: undoing one a later patch still covers raises
  `RuntimeError`; undoing an ended patch does nothing), a context manager (`with
  patch(m):` undoes on exit), `.active`, `.proxymap`, `.targets` (`None` = all).
- **`unpatch()`** — ends every patch; every client is back on the default map. The
  integrations stay installed (they behave as without proxylib under the default).
- **`active(target) -> ProxyMap`** — the map `target`'s client uses now.
- **`register_patcher(name, install, uninstall, *, module, replace=False)`** — a client
  integration. `install(proxymap)` is called once, when module `module` has been
  imported, with a map that always answers as the active map does; `uninstall()`
  removes it. An existing `name` raises `ValueError` unless `replace=True`.
  **`targets()`** lists the names.

## Client integrations (`proxylib.integrations`)

- **Failover and health** (requests and httpx): an answer is a list tried in order,
  healthy entries first. An entry that fails **before the request is sent** (the proxy,
  or for DIRECT the server, refuses or times out connecting) is marked bad for
  `bad_proxy_ttl` seconds (default 300) and the next is tried; the last error is raised.
  A read or write error never fails over (the server may have the request). Marks are
  process-wide, shared with `Probed`, and dropped by `clear_caches()`.
- **`ProxyMapAdapter(proxymap, *args, failover=True, bad_proxy_ttl=300.0, **kwargs)`**
  (`.requests`; looking the name up imports `requests`, and constructing it without
  `requests` raises `MissingExtraError`) — a `requests.adapters.HTTPAdapter` subclass;
  hooks `send()` so it sees the real request URL (scheme, host, and path). An explicit
  `proxies=` entry at the same `scheme://hostname` key still wins (matches
  `requests.utils.select_proxy` precedence); a less-specific key (bare `"http"`, or
  env-injected) does not. When the map has no opinion, requests decides from its
  `proxies` as usual — but a proxylib value found there (a PAC result such as `"PROXY
  a:1; DIRECT"`, a list of proxies, a `Proxy`, or a `ProxyDict` as the whole `proxies`)
  is resolved and failed over; a plain proxy URL stays requests' own. Errors from
  `failover=False` are requests' (`ProxyError`, `ConnectionError`, ...).
- **`ProxyMapHandler(proxymap)`** (`.urllib`) — a `urllib.request.ProxyHandler`
  subclass; resolves per-request from `proxymap` instead of a static dict.
  `http_open`/`https_open`/`ftp_open` all bind the same resolver. It uses the healthiest
  entry and does not fail over (urllib cannot re-send a request through another proxy).
  Returning DIRECT falls through to the default (non-proxying) handler; no opinion
  (`KeyError`) uses the proxy `urllib.request.getproxies()` names for the scheme, as the
  standard handler would.
- **`ProxyTransport(proxymap, *, failover=True, bad_proxy_ttl=300.0,
  **transport_kwargs)`** and **`AsyncProxyTransport(...)`** (`.httpx`, the `httpx` extra;
  constructing one without httpx raises `MissingExtraError(extra="httpx")`) — httpx
  transports: `httpx.Client(transport=ProxyTransport(m))`,
  `httpx.AsyncClient(transport=AsyncProxyTransport(m))` (which reads the map with
  `alookup`). One inner `httpx.HTTPTransport` / `AsyncHTTPTransport` per proxy URL,
  made on first use with `transport_kwargs`, closed by `close()` / `aclose()` (the
  client does this). Fails over on `httpx.ProxyError`, `ConnectError`, `ConnectTimeout`.
  A map with no opinion means DIRECT (httpx skips its environment proxies when given a
  transport): chain `EnvProxyConfig()` in front to honour them. SOCKS needs
  `httpx[socks]`. httpx has no global hook, so there is no httpx patch target.
- **`ProxyDict(proxymap)`** (`.dict`) — duck-types the plain `{scheme_or_url:
  "proxy://uri"}` dict `requests`-like libraries accept. **Composes**, doesn't subclass,
  `ProxyMap` (`__getitem__` returns `str`, an LSP violation if it were a `ProxyMap`
  subclass). Lookups are by scheme/host only, not the full URL — path-dependent
  PAC/`NO_PROXY` rules won't apply; use `ProxyMapAdapter`/`ProxyMapHandler` when that
  fidelity matters. DIRECT raises `KeyError` (dict convention: missing key = no proxy),
  and so does a key the map cannot parse as a URL (`"http"`, `"all"`).
  `.setdefault(url, value)` is a no-op (requests calls it to merge env proxies; the
  `ProxyMap` wins).

## Exceptions (`proxylib.exceptions`, all re-exported at top level)

- **`ProxylibError`** — base of every error proxylib raises.
- **`ProxyParseError(ProxylibError, ValueError)`** — text that should name a proxy or a
  PAC result could not be parsed.
- **`PACError(ProxylibError)`** — a PAC script raised, ran out of time, or could not be
  loaded as a script.
- **`NoReachableProxyError(ProxylibError, LookupError)`** — no offered proxy accepted a
  connection (`Probed`).
- **`MissingExtraError(ProxylibError, ImportError)`** — an optional dependency is not
  installed; `.extra` is the proxylib extra (or `None`), `.name` the missing module, and
  the message gives the `pip install` line.
- None of them subclasses `KeyError`: `KeyError` from a map always means "no opinion".

## Caches

- **`clear_caches()`** (top level) — drops every cache proxylib keeps: downloaded PAC
  scripts, PAC `dnsResolve` answers, WPAD results, GNOME/MATE settings, local
  interfaces and the unreachable-proxy blacklist. (A `Cached` map keeps its own:
  `.clear()`.)

## Package metadata

- **`proxylib.__version__`** — resolved lazily (PEP 562 `__getattr__`) from installed
  package metadata (`importlib.metadata.version("proxylib")`); costs nothing at import
  time and never drifts from `pyproject.toml`.
- **Dependencies** — one required: `netimps>=0.4.0,<0.5` (network helpers, no
  dependencies of its own). `import proxylib` imports neither it nor any optional
  client library; each is imported when first used. Extras: `pac` (quickjs), `dukpy`,
  `httpx` (the httpx transports), `patch` (importpatch: patch clients in every program,
  see Patching clients).
