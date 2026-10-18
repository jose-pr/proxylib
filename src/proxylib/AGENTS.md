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
built-in map returns `tuple[Proxy | None, ...]`. `SimpleProxyMap` and `PAC` always
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
- **`SimpleProxyMap(proxy=None)`** — the same answer for every URL; takes anything
  `lookup` reads. `.proxies` is the parsed tuple.
- **`ChainProxyMap(*maps)`** — asks each map in order through `lookup`; the first
  with an opinion answers (DIRECT included). If every map has no opinion, neither
  does the chain. Links can be `dict`s.
- **`ConfigurableProxyMap(proxymap, *, cache_ttl=None, probe=False, probe_timeout=5.0,
  round_robin=False, browser_compatibility=False, bypass_local=False, no_proxy=None,
  cache_maxsize=1024)`**
  — decorates any `ProxyMap` with independent opt-in features:
  - `cache_ttl` (seconds, `None`/falsy disables) — per-effective-URL cache of the
    decorated map's answer, at most `cache_maxsize` URLs (least recently used dropped
    first); `clear_cache()`.
  - `probe=True` — resolves to the first entry whose port accepts a TCP connection
    (unreachable proxies are skipped for 30 s); nothing reachable becomes `KeyError`
    here, not a silent DIRECT.
  - `round_robin=True` — rotates the result tuple each call, cached or not, so a
    different entry leads while preserving the rest as fallback (thread-safe).
  - `browser_compatibility=True` — strips path/query/fragment from HTTPS URLs before
    delegating and before computing the cache key (matches Chrome/Firefox PAC privacy
    behavior).
  - `bypass_local=True` — bypasses loopback/link-local/same-subnet addresses (shorthand
    for `no_proxy=["<local>"]`).
  - `no_proxy` — extra bypass rules (same syntax as `NO_PROXY`), checked before
    delegating to `proxymap`.

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

- **`EnvProxyConfig(*, proxies={}, no_proxy=None)`** — a proxy map. `proxies` maps a
  URL scheme or `"all"` to a `Proxy`, a proxy URL (scheme-less = `http`) or a PAC
  location (`file:` URL, or `http(s)` URL with a path), which is loaded on the
  first lookup that needs it. `no_proxy` is `BypassRules` or `NO_PROXY` text.
  Lookup: bypassed → `(None,)`; else the scheme's proxy (`ws` falls back to `http`,
  `wss` to `https`); else `"all"`; else **`KeyError`** (no opinion — the environment
  cannot say DIRECT). A key that is not a URL raises `ProxyParseError`.
  `repr()` hides passwords.
- **`EnvProxyConfig.from_environ(environ=None)`** — reads every `<scheme>_proxy`,
  `all_proxy` and `no_proxy` from `environ` (default `os.environ`); a lowercase name
  wins over its uppercase form. Inside a CGI request (`REQUEST_METHOD` set) an
  uppercase `HTTP_PROXY` is ignored (httpoxy); with `os.environ` on Windows, whose
  names are case-insensitive, `http_proxy` is ignored then too. There is no PAC
  environment variable: put a PAC URL in `HTTP_PROXY` and the others.

## System / auto detection (`proxylib.os`, re-exported at top level)

- **`system_proxy(provider="python") -> ProxyMap | str`** — this machine's configured
  proxy. `provider="python"` (default): proxylib's own per-OS detection (`.nt` on
  Windows via the WinHTTP API, `.darwin` via `scutil --proxy`, `.posix` — libproxy,
  GNOME/MATE, KDE, NetworkManager, then env vars, tried in that order). Each backend
  respects its own OS/desktop auto-detect (WPAD) signal itself and tries it first. A
  `str` return is a PAC URL the caller still needs to load. `provider="system"`:
  outsources to the OS's native engine (`WinHttpProxyMap`/`CFNetworkProxyMap`/
  `LibProxyMap`) instead — falls back to `"python"` on POSIX if libproxy's shared
  library isn't loadable. Any other `provider` raises `ValueError`. A WinHTTP answer
  with several proxies keeps all of them, in order.
- **`auto_proxy(provider="python", **urlopen_kwargs) -> ProxyMap`** — resolves the full
  effective config: `system_proxy(provider)` → if it's a PAC URL string, load it → if it
  signals "nothing configured" (the `"python"` provider only), fall back to WPAD
  discovery (`pac.wpad.discover`) → otherwise DIRECT. `**urlopen_kwargs` forward to the
  PAC/WPAD HTTP fetch (e.g. `timeout=`).
- **`LibProxyMap(lib=None)`** (`proxylib.os.posix.libproxy`, re-exported at top level) —
  a standalone `ProxyMap` using libproxy's C API directly via `ctypes` (no subprocess).
  Construct with no arguments to auto-detect the shared library. `__getitem__` raises
  `KeyError` (not a construction-time error) if libproxy isn't available, and when
  libproxy returns no answer. Keeps one `pxProxyFactory` per map, created on first
  lookup and freed by `close()` (or garbage collection); usable directly on any
  platform regardless of the OS dispatch above.

## PAC support (`proxylib.pac`)

- **`PAC`** — base utility-function namespace (`dnsResolve`, `dnsResolveEx`,
  `myIpAddress`, `myIpAddressEx`, `dnsDomainLevels`, `isInNet`/`isInNetEx`,
  `isResolvable`/`isResolvableEx`, `dateRange`, `timeRange`, `shExpMatch`,
  `sortIpAddressList`, `getClientVersion`, ...) implementing the full Netscape PAC set
  plus Microsoft's `*Ex` extensions. A proxy map. `shExpMatch` treats only `*` and
  `?` as wildcards and is case-sensitive on every platform, as in browsers. The
  script's result is read with `Proxy.parse_pac_result` (a non-string result is
  DIRECT).
  `FindProxyForURL` here always returns `"DIRECT"` —
  subclass and override it, or use `JSProxyAutoConfig`, to actually select proxies.
  `dnsResolve(host, cache_ttl=30.0)` — per-host cached; `cache_ttl=0`/`None` forces a
  fresh lookup.
- **`JSProxyAutoConfig`** (only defined if a JS engine is installed, else `None`) — a
  `PAC` subclass whose `FindProxyForURL` (and the utility functions) run as real
  JavaScript against whichever engine `pac.engines.get_engine_class()` picks; calls
  into the engine are serialised per instance, so one map is safe to share between
  threads. Which
  engine: the `PROXYLIB_JS_ENGINE` env var, a **comma-separated** priority list (e.g.
  `"dukpy,quickjs"`); unset defaults to `("quickjs", "dukpy")`. `proxylib[pac]`
  installs `quickjs`/`quickjs-ng` depending on the Python version; `proxylib[dukpy]`
  installs `dukpy` (the one with a Windows ARM64 wheel).
- **`load(url, cache_ttl=300.0, **urllib_kwds) -> PAC`** (top-level alias:
  `proxylib.load_pac`) — load a PAC script from a URL, a `file:` path, or inline JS
  source (detected via a `"FindProxyForURL("` substring check). Without a JS engine
  installed, warns and returns an always-DIRECT `PAC()`. Genuine network downloads
  (not `file:`/inline) are cached per URL for `cache_ttl` seconds; `cache_ttl=0`/`None`
  forces a fresh fetch. A download times out after 10 s unless `timeout=` is passed;
  a body over 1 MiB raises `ValueError`; a non-UTF-8 body is decoded as Latin-1.
  Raises `ValueError` if the fetched/read source has no
  `FindProxyForURL`. The fetch **bypasses any configured proxy** (chicken-and-egg
  avoidance, matches browser PAC-fetch behavior).
- **`clear_download_cache()`** / **`clear_dns_cache()`** — test/cache-busting seams.
- **`discover(fqdn=None, timeout=3.0, cache_ttl=300.0, **urllib_kwds) -> PAC | None`**
  (`proxylib.pac.wpad`, top-level alias: `proxylib.discover_pac`) — DNS+HTTP WPAD
  discovery: tries `http://wpad.<domain>/wpad.dat` for each parent domain of `fqdn`
  (default: this host's FQDN), most-specific first, stopping before a public suffix
  (a bare TLD or a ccTLD registry level such as `co.uk`). Returns the
  first successfully loaded `PAC`, or `None`. Results (including "not found") are
  cached per fqdn for `cache_ttl` seconds. **DHCP option 252 discovery is not
  implemented** (no portable stdlib path to OS DHCP lease data) — DNS+HTTP only.

## Global patching (`proxylib.patching`)

- **`patch(proxymap, targets=None)`** — globally wires `proxymap` into `targets`
  (default: every registered target — built-in `"requests"` and `"urllib"`, if
  `requests` is importable). Calling this while already patched **replaces** the
  previous patch (with a warning), not a stack — one active resolver at a time. A
  partial failure (unknown target, or a patch function that raises) rolls back
  whatever did apply before propagating.
- **`unpatch()`** — undoes whatever `patch()` last applied, in reverse order.
  Idempotent (no-op if nothing is patched).
- **`register_patcher(name, patch_func, unpatch_func)`** — register a custom
  integration. `patch_func(proxymap)` applies it; `unpatch_func()` (no args — capture
  state in a closure) undoes it. Re-registering an existing `name` replaces it.
- `patch(proxymap)` with no `targets` skips a built-in target whose client is not
  installed; naming it in `targets` raises `MissingExtraError`.
- Built-in targets: `"requests"` wraps `requests.Session.__init__` so newly constructed
  sessions mount a `ProxyMapAdapter` (sessions created *before* `patch()` are
  untouched); `"urllib"` installs a global opener via
  `urllib.request.install_opener(...)`.

## `requests`/`urllib` integrations (`proxylib.integrations`)

- **`ProxyMapAdapter(proxymap, *args, **kwargs)`** (`.requests`; looking the name up
  imports `requests`, and constructing it without `requests` raises
  `MissingExtraError`) — a `requests.adapters.HTTPAdapter` subclass; hooks `send()` so it
  sees the real request URL (scheme, host, and path). An explicit `proxies=` entry at
  the same `scheme://hostname` key still wins (matches `requests.utils.select_proxy`
  precedence); a less-specific key (bare `"http"`, or env-injected) does not.
- **`ProxyMapHandler(proxymap)`** (`.urllib`) — a `urllib.request.ProxyHandler`
  subclass; resolves per-request from `proxymap` instead of a static dict.
  `http_open`/`https_open`/`ftp_open` all bind the same resolver. Returning DIRECT
  falls through to the default (non-proxying) handler.
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
  connection (`ConfigurableProxyMap(probe=True)` turns it into `KeyError`).
- **`MissingExtraError(ProxylibError, ImportError)`** — an optional dependency is not
  installed; `.extra` is the proxylib extra (or `None`), `.name` the missing module, and
  the message gives the `pip install` line.
- None of them subclasses `KeyError`: `KeyError` from a map always means "no opinion".

## Caches

- **`clear_caches()`** (top level) — drops every cache proxylib keeps: downloaded PAC
  scripts, PAC `dnsResolve` answers, WPAD results, GNOME/MATE settings, local
  interfaces and the unreachable-proxy blacklist. (`ConfigurableProxyMap` instances
  keep their own cache: `clear_cache()`.)

## Package metadata

- **`proxylib.__version__`** — resolved lazily (PEP 562 `__getattr__`) from installed
  package metadata (`importlib.metadata.version("proxylib")`); costs nothing at import
  time and never drifts from `pyproject.toml`.
- **Dependencies** — one required: `netimps>=0.4.0,<0.5` (network helpers, no
  dependencies of its own). `import proxylib` imports neither it nor any optional
  client library; each is imported when first used. Extras: `pac` (quickjs), `dukpy`.
