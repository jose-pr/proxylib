# `proxylib` — public API header

Header-file-style reference for the `proxylib` package: every top-level export with its
signature, arguments, contract, and gotchas, so this module can be consumed without
reading its source. Kept current with the public API. For the project overview and
install instructions, see <https://github.com/jose-pr/proxylib#readme>.

Every `ProxyMap` implementation answers the same question — `proxymap[url]` (or
`.get(url, default)`) returns the sequence of `Proxy` (or `None` for DIRECT) to try, in
order. **Result contract**, followed by every built-in map: `__getitem__` **raises**
`KeyError` for "no opinion" (a chain falls through to the next map), **yields** `None`
for an explicit DIRECT decision, and **yields** a `Proxy` to mean "use this proxy".
`SimpleProxyMap` and `pac.PAC` are always definitive and never raise `KeyError`;
`EnvProxyConfig` raises `KeyError` for a scheme with no configured env proxy (env vars
can't express "explicitly DIRECT", only set/absent).

## Core types (`proxylib.proxy`)

- **`Proxy`** — `NamedTuple`-like URI type for one proxy authority
  (`scheme://[user[:pass]@]host[:port]`). `Proxy(scheme, username, password, host,
  port)` — **`Proxy("direct", ...)` returns `None`, not an instance** (the DIRECT
  sentinel). `scheme="proxy"` normalizes to `"http"`, `"socks"` to `"socks4"`, empty to
  `"http"`. `.url` — `"{scheme}://{netloc}"`.
- **`ProxyMap`** — `runtime_checkable Protocol`, and a factory: `ProxyMap(src)` builds a
  `SimpleProxyMap` for a bare authority string, or loads `src` as a PAC source (via
  `pac.load()`) if it looks like a PAC file/URL (has a path beyond the authority, or is
  a `file:` reference). Methods every implementation gets: `__getitem__(uri) ->
  Iterable[Optional[Proxy]]` (must implement; see result contract above),
  `get(uri, default=None)`, `__contains__(key)`, and `__enter__`/`__exit__` (context
  manager = `patch(self)` on enter, `unpatch()` on exit).
- **`SimpleProxyMap(proxy=None)`** — always returns the same fixed proxy/list.
  `proxy` may be `None` (DIRECT), a `Proxy`, a `Sequence[Optional[Proxy]]`, or a `str`:
  a URL-style string (`"://"` present, e.g. `"http://host:port"`) or a PAC-style string
  (`"PROXY host:port; DIRECT"`) — auto-detected.
- **`ChainProxyMap(*maps)`** — tries each `ProxyMap` in order; the first one with an
  opinion (not `KeyError`) wins. If every constituent raises `KeyError`, so does the
  chain — composes inside a larger chain.
- **`ConfigurableProxyMap(proxymap, *, cache_ttl=None, probe=False, probe_timeout=5.0,
  round_robin=False, browser_compatibility=False, bypass_local=False, no_proxy=None)`**
  — decorates any `ProxyMap` with independent opt-in features:
  - `cache_ttl` (seconds, `None`/falsy disables) — per-effective-URL cache; `clear_cache()`.
  - `probe=True` — resolves to the first reachable entry via
    `netutils.first_working_proxy`; a `LookupError` (nothing reachable) becomes
    `KeyError` here, not a silent DIRECT.
  - `round_robin=True` — rotates the result tuple each call so a different entry leads
    while preserving the rest as fallback (thread-safe).
  - `browser_compatibility=True` — strips path/query/fragment from HTTPS URLs before
    delegating and before computing the cache key (matches Chrome/Firefox PAC privacy
    behavior).
  - `bypass_local=True` — bypasses loopback/link-local/same-subnet addresses (shorthand
    for `no_proxy=["<local>"]`).
  - `no_proxy` — extra bypass rules (same syntax as `NO_PROXY`), checked before
    delegating to `proxymap`.
- **`UriSplit`** — enum selecting URL-style vs. PAC-string parsing for `Proxy.find_all`/
  `SimpleProxyMap`.

## Env var config (`proxylib.env`, re-exported at top level)

- **`EnvProxyConfig(http_proxy, https_proxy, no_proxy)`** — a `ProxyMap` from
  `HTTP_PROXY`/`HTTPS_PROXY`/`NO_PROXY`-style values. `http_proxy`/`https_proxy` are
  `str | Proxy | None` (`None` = "not configured", raises `KeyError` for that scheme —
  distinct from DIRECT). `no_proxy` is an iterable of entries: hostnames (exact or
  `.`-suffix match, curl convention), CIDR (`10.0.0.0/8`, IPv6 supported; matches
  IP-literal request hosts only, never resolved hostnames), `"<local>"`
  (loopback/link-local/same-subnet, needs the `ifaddr` extra for full accuracy), or
  `"*"` (bypass **everything**, matching curl/`requests`/stdlib — checked ahead of every
  other rule, so it never pays for a `<local>` DNS lookup, and it yields `[None]`
  (explicit DIRECT) even when no proxy is configured for the scheme). Merged
  with (not overridden by) the process-wide default rules from `set_default_no_proxy()`.
  - **`EnvProxyConfig.from_env() -> EnvProxyConfig`** — reads `HTTP_PROXY`/`http_proxy`,
    `HTTPS_PROXY`/`https_proxy`, `NO_PROXY`/`no_proxy` (uppercase wins if both set).
- **`set_default_no_proxy(rules)`** / **`get_default_no_proxy() -> list[str]`** —
  process-wide default `NO_PROXY` rules consulted by every `EnvProxyConfig` (and
  `ConfigurableProxyMap(no_proxy=...)`) in addition to whatever's passed explicitly.
  `set_default_no_proxy(None)` clears it.

## System / auto detection (`proxylib.os`, re-exported at top level)

- **`system_proxy(provider="python") -> ProxyMap | str`** — this machine's configured
  proxy. `provider="python"` (default): proxylib's own per-OS detection (`.nt` on
  Windows via the WinHTTP API, `.darwin` via `scutil --proxy`, `.posix` — libproxy,
  GNOME/MATE, KDE, NetworkManager, then env vars, tried in that order). Each backend
  respects its own OS/desktop auto-detect (WPAD) signal itself and tries it first. A
  `str` return is a PAC URL the caller still needs to load. `provider="system"`:
  outsources to the OS's native engine (`WinHttpProxyMap`/`CFNetworkProxyMap`/
  `LibProxyMap`) instead — falls back to `"python"` on POSIX if libproxy's shared
  library isn't loadable.
- **`auto_proxy(provider="python", **urlopen_kwargs) -> ProxyMap`** — resolves the full
  effective config: `system_proxy(provider)` → if it's a PAC URL string, load it → if it
  signals "nothing configured" (the `"python"` provider only), fall back to WPAD
  discovery (`pac.wpad.discover`) → otherwise DIRECT. `**urlopen_kwargs` forward to the
  PAC/WPAD HTTP fetch (e.g. `timeout=`).
- **`LibProxyMap(lib=None)`** (`proxylib.os.posix.libproxy`, re-exported at top level) —
  a standalone `ProxyMap` using libproxy's C API directly via `ctypes` (no subprocess).
  Construct with no arguments to auto-detect the shared library. `__getitem__` raises
  `KeyError` (not a construction-time error) if libproxy isn't available. Creates a
  fresh `pxProxyFactory` per lookup (matches libproxy's own contract); usable directly
  on any platform regardless of the OS dispatch above.

## PAC support (`proxylib.pac`)

- **`PAC`** — base utility-function namespace (`dnsResolve`, `dnsResolveEx`,
  `myIpAddress`, `myIpAddressEx`, `dnsDomainLevels`, `isInNet`/`isInNetEx`,
  `isResolvable`/`isResolvableEx`, `dateRange`, `timeRange`, `shExpMatch`,
  `sortIpAddressList`, `getClientVersion`, ...) implementing the full Netscape PAC set
  plus Microsoft's `*Ex` extensions. `FindProxyForURL` here always returns `"DIRECT"` —
  subclass and override it, or use `JSProxyAutoConfig`, to actually select proxies.
  `dnsResolve(host, cache_ttl=30.0)` — per-host cached; `cache_ttl=0`/`None` forces a
  fresh lookup.
- **`JSProxyAutoConfig`** (only defined if a JS engine is installed, else `None`) — a
  `PAC` subclass whose `FindProxyForURL` (and the utility functions) run as real
  JavaScript against whichever engine `pac.engines.get_engine_class()` picks. Which
  engine: the `PROXYLIB_JS_ENGINE` env var, a **comma-separated** priority list (e.g.
  `"dukpy,quickjs"`); unset defaults to `("quickjs", "dukpy")`. `proxylib[jspac]`
  installs plain `dukpy`; `proxylib[quickjs]` installs `quickjs`/`quickjs-ng` depending
  on the Python version.
- **`load(url, cache_ttl=300.0, **urllib_kwds) -> PAC`** (top-level alias:
  `proxylib.load_pac`) — load a PAC script from a URL, a `file:` path, or inline JS
  source (detected via a `"FindProxyForURL("` substring check). Without a JS engine
  installed, warns and returns an always-DIRECT `PAC()`. Genuine network downloads
  (not `file:`/inline) are cached per URL for `cache_ttl` seconds; `cache_ttl=0`/`None`
  forces a fresh fetch. Raises `ValueError` if the fetched/read source has no
  `FindProxyForURL`. The fetch **bypasses any configured proxy** (chicken-and-egg
  avoidance, matches browser PAC-fetch behavior).
- **`clear_download_cache()`** / **`clear_dns_cache()`** — test/cache-busting seams.
- **`discover(fqdn=None, timeout=3.0, cache_ttl=300.0, **urllib_kwds) -> PAC | None`**
  (`proxylib.pac.wpad`, top-level alias: `proxylib.discover_pac`) — DNS+HTTP WPAD
  discovery: tries `http://wpad.<domain>/wpad.dat` for each parent domain of `fqdn`
  (default: this host's FQDN), most-specific first, skipping the bare TLD. Returns the
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
- Built-in targets: `"requests"` wraps `requests.Session.__init__` so newly constructed
  sessions mount a `ProxyMapAdapter` (sessions created *before* `patch()` are
  untouched); `"urllib"` installs a global opener via
  `urllib.request.install_opener(...)`.

## `requests`/`urllib` integrations (`proxylib.integrations`)

- **`ProxyMapAdapter(proxymap, *args, **kwargs)`** (`.requests`; `None` if `requests`
  isn't installed) — a `requests.adapters.HTTPAdapter` subclass; hooks `send()` so it
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
  fidelity matters. DIRECT raises `KeyError` (dict convention: missing key = no proxy).
  `.setdefault(url, value)` is a no-op (requests calls it to merge env proxies; the
  `ProxyMap` wins).

## Network helpers (`proxylib.netutils`)

- **`first_working_proxy(proxies, timeout=5.0, circuit_breaker_ttl=30.0,
  clock=time.monotonic) -> Proxy | None`** (top-level) — failover helper: returns the
  first entry (in order) that accepts a TCP connection to its port; `None` (DIRECT) is
  returned immediately without probing. Raises `LookupError` if nothing is reachable
  (can't return `None` for that — `None` means DIRECT). A proxy that fails its probe is
  blacklisted (skipped without re-probing) for `circuit_breaker_ttl` seconds;
  `clear_circuit_breaker()` resets it. `0`/`None` disables the breaker.
- **`get_ip(address) -> IPv4Address | IPv6Address | None`** — resolve a hostname or IP
  literal.
- **`get_local_interfaces(cache_ttl=10.0) -> list[IPv4Interface | IPv6Interface]`** —
  this host's interfaces; accurate with the `ifaddr` extra, else a host-route-only
  (`/32`/`/128`) stdlib fallback. `clear_interfaces_cache()` resets the cache.
- **`get_default_port(scheme) -> int | None`** — conventional port for a scheme
  (`http`/`https`/`ftp`/`socks*` plus `getservbyname` fallback).
- **`is_loopback_or_link_local(ip) -> bool`** — loopback (`127/8`, `::1`) or link-local
  (`169.254/16`, `fe80::/10`).

## Package metadata

- **`proxylib.__version__`** — resolved lazily (PEP 562 `__getattr__`) from installed
  package metadata (`importlib.metadata.version("proxylib")`); costs nothing at import
  time and never drifts from `pyproject.toml`.
