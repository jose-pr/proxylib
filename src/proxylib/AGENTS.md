# `proxylib` — public API header

Header-file-style reference for the `proxylib` package: every public export with
its signature, arguments, contract and gotchas, so the package can be used
without reading its source. It ships inside the package and is
self-contained. Development documentation lives with the source at
<https://github.com/jose-pr/proxylib>.

Import from `proxylib` (the names in `proxylib.__all__`). A few names live in their
module only: the OS resolvers in `proxylib.system`, the PAC builtins and engines in
`proxylib.pac`, the client integrations in `proxylib.integrations.{requests, urllib,
httpx, aiohttp, dict}`, and `active`/`targets` in `proxylib.patching`. Modules whose
name starts with `_` are private.

`pip install proxylib` (Python 3.9+). Two dependencies, neither with dependencies of
its own: `netimps` (network helpers) and `importpatch` (post-import hooks). Extras:
`pac` installs the quickjs JavaScript engine for PAC scripts (`quickjs-ng` on Python
3.10+, `quickjs` on 3.9) and `dukpy` the dukpy engine (the one with Windows ARM64 and
Intel macOS wheels). The client integrations need no extra: each works when its client
(`requests`, `httpx`, `aiohttp`) is installed. `import proxylib` imports importpatch,
but not netimps, a JS engine or any client.

`proxylib.__version__` is the installed version, read from the package metadata
when first asked for.

## Proxy maps (`proxylib.proxy`)

A **proxy map** is anything indexable by request URL — a plain `dict` included; no
proxylib base class is needed. `proxymap[url]` answers with:

- `None` — DIRECT;
- one proxy — a `Proxy`, a proxy URL (`"http://user:pass@host:3128"`; scheme-less
  means `http`), a PAC result string (`"PROXY a:1; SOCKS5 b:2; DIRECT"`), or any
  object with a `url` attribute (credentials from the URL, else from its
  `username`/`password` attributes);
- an iterable of those, tried in order, where a `None` entry is DIRECT and an empty
  iterable is DIRECT;
- or it **raises `KeyError`**: no opinion (a chain asks the next map).

Read an answer with `lookup()`, never by indexing yourself. Every built-in map
returns `tuple[Proxy | None, ...]`, is safe to share between threads and asyncio
tasks (through `alookup`), and has an idempotent `close()` that frees what it owns
(a PAC helper process, an OS session) and closes the maps it wraps or chains.

```python
lookup(proxymap: ProxyMap, url: str) -> tuple[Proxy | None, ...]
```

Never empty. A `Mapping` with no entry for the full URL is also asked with the keys
`requests` uses, most specific first: `scheme://host`, `scheme`, `all://host`, `all`.
Raises `KeyError` for no opinion, `TypeError` for an answer that names no proxy,
`ProxyParseError` for malformed proxy text.

```python
async alookup(proxymap: ProxyMap, url: str) -> tuple[Proxy | None, ...]
```

`lookup` run in a worker thread (`asyncio.to_thread`): a PAC script, a download or
an OS resolver may block. Same answer and errors.

```python
Proxy(scheme, host, port=None, username=None, password=None, *, path=None, headers=None)
Proxy.parse(text) -> Proxy
Proxy.parse_pac_result(text) -> tuple[Proxy | None, ...]
proxy.headers -> dict[str, str]          # a new dict each read
proxy.is_gateway -> bool
proxy.gateway_url(target) -> str
```

One proxy: immutable, hashable, picklable. `scheme` is lower-cased (`"proxy"` →
`"http"`, `"socks"` → `"socks4"`); an empty scheme or host, or a port outside
1–65535, raises `ProxyParseError`. Absent port and credentials are `None`. `.url` is
`scheme://host[:port]` without credentials (IPv6 bracketed; `str()` is the same);
`.uri()` adds the credentials, percent-encoded; `repr()` shows `password='***'`.
`parse` reads a proxy URL (scheme-less = `http`, `[::1]:8080` for IPv6; a path other
than `/` raises `ProxyParseError` — that is a PAC location, except on a gateway).
`parse_pac_result` reads a `FindProxyForURL` result: keywords case-insensitive
(`DIRECT`, `PROXY`, `HTTP`, `HTTPS`, `SOCKS` = `socks4`, `SOCKS4`, `SOCKS5`, and
proxylib's own `PREFIX <http(s) URL>` for a gateway); an entry with an unknown keyword
or no host is dropped with a `UserWarning`; nothing usable is `(None,)`.

**Proxy headers.** `headers` (a mapping or pairs) are sent to that proxy only: in the
`CONNECT` of a tunnel, and on a plain-http request to it — never through the tunnel to
the server. Use them for a credential that is not user/password (`{"Proxy-Authorization":
"Bearer …"}`) or one under another header name (`{"X-Proxy-Token": "…"}`). Names must be
HTTP tokens and values free of CR/LF, else `ProxyParseError`; a SOCKS proxy takes none.
They count in equality and hashing (names case-insensitive); `repr()` shows the names
with `'***'`; `.url` and `.uri()` never include them. No text form carries them: build
the `Proxy` in code.

**URL-prefix gateways.** Schemes `prefix+http` and `prefix+https`, with a `path`
(default `/`; an absolute path, no query), name a gateway that fetches a URL appended to
its own: the request for `T` is sent directly to `gateway_url(T)` =
`<http|https>://host[:port]<path>T`, the target as given. Write one as
`prefix+https://gw.example/fetch/`, or `PREFIX https://gw.example/fetch/` in a PAC
result; `.url` keeps the `prefix+` scheme and the path. A gateway's credentials go as a
Basic `Proxy-Authorization` header of that request, with its `headers`. Health marks
and probes use its host and port (`443` for `prefix+https`).

```python
ProxyMap                     # runtime_checkable Protocol: __getitem__(url) only
ProxyMap(src=None) -> ProxyMap
```

`isinstance(x, ProxyMap)` checks the shape only (true for a `dict`, and for a `str`).
Calling the protocol builds a map from a configured value, with no I/O: `None`, a
proxy URL, a PAC result string, a `Proxy` or a list/tuple of them → `SimpleProxyMap`;
a PAC location (`file:` URL, inline script, or `http(s)` URL with a path beyond `/`)
→ a map that loads it on the first lookup; anything else with `__getitem__` is
returned unchanged. `ProxyLike` and `ProxyAnswer` are the type aliases for one proxy
and for an answer.

```python
SimpleProxyMap(proxy=None)          # the same answer for every URL; .proxies
ChainProxyMap(*maps)                # the first map with an opinion answers
```

`SimpleProxyMap` takes anything `lookup` reads. `ChainProxyMap` asks each map in
order; any answer, DIRECT included, ends the chain; if every link has no opinion,
neither does the chain. Links can be `dict`s.

## Wrappers (`proxylib.wrappers`)

Maps over any inner map, read through `lookup`; the inner map's `KeyError` passes
through. Compose in the order you mean: `RoundRobin(Cached(m, ttl=60))` rotates the
cached answer.

```python
Bypass(inner, rules)
Cached(inner, *, ttl: float, maxsize: int = 1024)
RoundRobin(inner)
Probed(inner, *, timeout: float = 5.0)
configure(inner, *, bypass=None, cache_ttl=None, round_robin=False, probe=False,
          probe_timeout=5.0) -> ProxyMap
```

- `Bypass` — `(None,)` for a URL `rules` match (`BypassRules`, `NO_PROXY` text or its
  entries; loopback included unless `<-loopback>`), else the inner answer.
- `Cached` — the inner answer per URL for `ttl` seconds, at most `maxsize` URLs (least
  recently used dropped first); no opinion is not cached; `.clear()`, `len()`.
  `ttl <= 0` or `maxsize < 1` raises `ValueError`.
- `RoundRobin` — rotates the answer one place per lookup, so successive requests lead
  with a different entry and keep the rest as fallbacks; one rotation per distinct
  answer (the 1024 most recent), shared by every URL with that answer.
- `Probed` — `(first reachable entry,)`: the first whose port accepts a TCP connection
  within `timeout` (DIRECT counts as reachable; a failed proxy is skipped for 30 s).
  None reachable raises `NoReachableProxyError` (a `LookupError`, not `KeyError`).
- `configure` — the asked-for wrappers, outermost first: `Bypass`; then
  `Probed(RoundRobin(Cached(inner)))` when rotating (each lookup probes the rotated
  answer), else `Cached(Probed(inner))` (the probed answer is cached). Nothing asked
  for returns `inner`.

## Bypass rules (`proxylib.bypass`)

```python
BypassRules.parse(text, *, dialect="no_proxy", reversed=False) -> BypassRules
rules.matches(url) -> bool
```

`text` is the list as one string or as entries. Dialects: `"no_proxy"` (curl; `,` or
space separated), `"wininet"` (Windows `ProxyOverride`; `;`), `"macos"`
(`ExceptionsList`), `"gsettings"` (GNOME/MATE `ignore-hosts`), `"kde"` (`NoProxyFor`;
`reversed=True` for `ReversedException`, which makes the list name the hosts that
*use* the proxy). An unknown dialect raises `ValueError`; unparsable entries are
skipped with one `UserWarning` naming them.

Entries: a host (exact; in `no_proxy`/`kde`, and for a leading `.` or `*.` in every
dialect, the host and its subdomains); a glob with `*`/`?` (`[` literal,
case-insensitive); CIDR, including abbreviated IPv4 (`169.254/16`) and IPv6, matched
against IP-literal hosts only (no DNS); an optional `:port` (a URL without a port has
its scheme's default); `<local>` = a host name with no dot; `<subnet>` = a host that
resolves to loopback, link-local or an address on a local interface's network (does
DNS); `<-loopback>` turns off the implicit loopback bypass; `*` as the whole list =
every host. **Loopback** (`localhost`, `*.localhost`, `127.0.0.0/8`, `::1`) always
bypasses unless `<-loopback>` is listed. `a | b` combines lists; `bool(rules)` is
false when empty; `BypassRules.NONE`; immutable and hashable.

## Environment configuration (`proxylib.env`)

```python
EnvProxyConfig(env=None, *, proxies=None, no_proxy=None)
```

A proxy map read from an environment mapping: `env=None` reads `os.environ`, any
other mapping is read instead (`{}` reads nothing). It takes every `<scheme>_proxy`,
`all_proxy` and `no_proxy` (see Environment variables). `proxies` (scheme or `"all"`
→ `Proxy`, proxy URL, or PAC location loaded on first use) is applied over the
environment's; `no_proxy` (`BypassRules` or `NO_PROXY` text) replaces it. A value may
also be a whole PAC result — `HTTP_PROXY="PROXY a:3128; SOCKS5 b:1080; DIRECT"` answers
those three entries, in order, for failover — or a gateway
(`HTTPS_PROXY=prefix+https://gw.example/fetch/`). Lookup:
bypassed → `(None,)`; else the scheme's proxy (`ws` falls back to `http`, `wss` to
`https`); else `"all"`; else `KeyError` (no opinion — the environment cannot say
DIRECT). A key that is not a URL raises `ProxyParseError`; `repr()` hides passwords.

## System settings (`proxylib.system`)

```python
auto_proxy(*, system=True, no_proxy=None, wpad=False, timeout=10.0,
           on_missing_engine="raise", environ=None) -> ProxyMap
```

The proxy map for this machine; it answers every URL (never `KeyError`), in the
order of **Configuration precedence** below. `system=False` uses only the OS settings
read by proxylib (never an OS resolver, libproxy included). `no_proxy`
(`BypassRules`, `NO_PROXY` text or its entries) wraps the result. `environ` (default
`os.environ`) is the environment read for proxy variables: **`environ={}` is the
"OS settings only" form.** `wpad`, `timeout` and `on_missing_engine` go to
`ProxyConfig.to_proxymap`.

```python
system_config() -> ProxyConfig
```

This machine's OS or desktop settings; environment variables are not read. Windows:
the user's Internet Options (`WinHttpGetIEProxyConfigForCurrentUser`). macOS:
`scutil --proxy`. Elsewhere: GNOME (`org.gnome.system.proxy`), MATE, KDE
(`kioslaverc`; `ProxyType=4` defers to the environment and reads as no settings),
NetworkManager (`nmcli`, else `dbus-send`) — the first with a proxy configured, else
the first with settings. Nothing readable → `ProxyConfig()`. Programs run with a 5 s
limit, no stdin and `LC_ALL=C`; any failure reads as "no settings". Decisions are
logged at DEBUG on the `proxylib.system` logger.

```python
ProxyConfig(source="none", state="unset", auto_detect=False, pac_url=None,
            pac_script=None, proxies={}, bypass=BypassRules.NONE)
config.to_proxymap(*, wpad=False, timeout=10.0, on_missing_engine="raise") -> ProxyMap
```

A frozen dataclass. `source`: `"windows"`, `"macos"`, `"gnome"`, `"mate"`, `"kde"`,
`"networkmanager"` or `"none"`. `state`: `"direct"` (the settings say no proxy:
Windows and macOS with nothing switched on, GNOME `mode='none'`, KDE `ProxyType=0`),
`"configured"`, or `"unset"` (nothing to read); anything else raises `ValueError`.
`proxies`: read-only mapping from a request scheme (`http`, `https`, `ftp`) to a
`Proxy`, plus `"socks"` — the proxy for every scheme without its own entry; string
values are parsed; no cross-filling (an `https`-only setting leaves `http` DIRECT);
SOCKS keeps the version the OS means (Windows `socks=` is `socks4`; macOS, GNOME,
MATE and KDE SOCKS are `socks5`); an `https`/`ftp` entry is an HTTP proxy. `bypass`:
the OS's list in its dialect, applied to `proxies` only (as every OS does).
`to_proxymap`: `state="direct"` → DIRECT for every URL; otherwise WPAD (only when
`auto_detect`, or `wpad=True` with `state="unset"`), then the PAC at `pac_url`, then
`pac_script`, then `proxies` (bypass first; a scheme with no entry is DIRECT). A
source that fails (no WPAD server, a PAC that does not download or raises
`PACError`) passes to the next and is retried after 30 s. Nothing is fetched until
the first lookup. A missing JS engine raises `MissingExtraError` unless
`on_missing_engine="direct"`. `timeout` bounds each WPAD probe and PAC download.

OS resolvers — each raises `KeyError` when it cannot answer, never DIRECT for a
failure; each is safe to share between threads:

```python
WinHTTPProxyMap()                 # Windows: WinHttpGetProxyForUrl
CFNetworkProxyMap(deadline=5.0)   # macOS: CFNetworkCopyProxiesForURL
LibProxyMap(lib=None)             # libproxy's C API, when installed
```

`WinHTTPProxyMap`: WinHTTP does WPAD (DHCP and DNS), fetches the PAC with
NTLM/Kerberos when challenged and runs it (no JS engine needed); when the settings
name neither, or WinHTTP fails, the manual proxies answer. One session (10 s
timeouts) serves every lookup and thread; `close()` releases it, after which a lookup
raises `KeyError`. Construction raises `OSError` off Windows. `CFNetworkProxyMap`
runs a configured PAC natively; a run longer than `deadline` seconds → `KeyError`;
off macOS every lookup raises `KeyError`. `LibProxyMap`: `lib` defaults to the
library on the linker path; not installed, or no answer → `KeyError`; one
`pxProxyFactory` per map, made on the first lookup, freed by `close()`.

## Configuration precedence

`auto_proxy()` decides the same way on every OS:

1. **Environment.** If any proxy variable (`HTTP_PROXY`, `HTTPS_PROXY`, `ALL_PROXY`,
   … — any non-empty `*_proxy` except `no_proxy`) is set, the variables alone decide
   (`EnvProxyConfig`, as `urllib.request.getproxies()` does): a scheme with no
   variable is DIRECT and the OS is not consulted. A variable may name a PAC file.
2. **OS resolver** (with `system=True`): WinHTTP, CFNetwork, or libproxy when
   installed. A URL it cannot answer goes on to:
3. **OS settings** (`system_config().to_proxymap()`): auto-detection (WPAD) only when
   the OS has it switched on or `wpad=True` is passed on a machine with no settings,
   then the PAC URL, then the manual proxies.
4. **DIRECT.**

## PAC support (`proxylib.pac`)

```python
load(location, *, timeout=10.0, cache_ttl=300.0, script_timeout=5.0, engine=None,
     on_missing_engine="raise") -> PacProxyMap        # top level: load_pac
loads(text, *, script_timeout=5.0, engine=None,
      on_missing_engine="raise") -> PacProxyMap       # top level: loads_pac
```

`load` reads the PAC at a URL (`http`, `https`, `file`) or a path (`str` or
`os.PathLike`; `file:path` without `//` is a path), never script text. `timeout`
bounds the download, which **never goes through a proxy**; a body over 1 MiB raises
`PACError`; UTF-8 with a Latin-1 fallback; downloads (not `file:`) are cached per URL
for `cache_ttl` seconds. `loads` takes the script text.

```python
PacScript(source, *, engine=None, functions=None, timeout=5.0, on_missing_engine="raise")
PacScript.from_file(path, *, encoding="utf-8-sig", **options)
PacScript.from_url(url, *, timeout=10.0, max_bytes=MAX_PAC_BYTES, cache_ttl=300.0, **options)
script.find_proxy_for_url(url, host) -> str
```

One script, run in a **helper Python process** (`sys.executable`) so it can be stopped:
neither engine can be interrupted in-process. `timeout` bounds loading and each call
(each DNS lookup a builtin makes is bounded at 2 s): an overrun ends the helper and
raises `PACError`; for the next 30 s every call raises `PACError` at once, then the
script is started afresh. A script error, a script without a `FindProxyForURL`
function, or one that overruns while loading raises `PACError`. A non-string result
is `"DIRECT"`. `functions` adds to or overrides the builtins and must be picklable
module-level functions the helper can import. With no engine installed:
`on_missing_engine="raise"` → `MissingExtraError` (extra `pac`); `"direct"` → one
`UserWarning`, every answer `"DIRECT"`. Calls are serialised; `close()` ends the
helper and its pipes (garbage collection does too). In `from_url` the script budget
is `script_timeout=`.

```python
PacProxyMap(script, *, browser_compatibility=False)
```

The proxy map; `script` is a `PacScript` or any `callable(url, host) -> str` (a Python
`FindProxyForURL`). `host` is the URL's host, lower-cased; `browser_compatibility=True`
reduces an `https` URL to `https://host/` (the Chrome and Firefox privacy rule). Answers
through `Proxy.parse_pac_result`; never `KeyError` — whatever a Python function raises
becomes `PACError`, as a script error does. `close()` ends the script's helper.

- `functions` — read-only mapping of the PAC builtins by their PAC names: the Netscape
  set (`dnsResolve`, `myIpAddress`, `isInNet`, `shExpMatch`, `dnsDomainIs`,
  `weekdayRange`, `dateRange`, `timeRange`, …) plus Microsoft's `*Ex` functions,
  `sortIpAddressList` and `getClientVersion`. `dnsResolve` caches answers and failures
  for 30 s. `weekdayRange`, `dateRange` and `timeRange` answer as Chromium's PAC library
  (shared with Firefox) does, so a PAC behaves as in a browser: `timeRange(9, 17)` runs
  to 17:59:59 and the hour form does not wrap (`timeRange(22, 6)` is never true; write
  `timeRange(22, 0, 6, 0)`); `dateRange(24, "DEC")` — a day with one other value — keeps
  both ends in the current month, so it is true from the 24th to the month's end; an
  unknown day or month name is false.
- `proxylib.pac.engines` — `names()` (installed engines), `get_engine(name=None)`, the
  `JSEngine` protocol. Selection: `engine=`, else `PROXYLIB_JS_ENGINE`, else quickjs
  then dukpy; an unknown name raises `ValueError`. Neither engine is imported until a
  script needs it.

```python
discover(fqdn=None, *, timeout=3.0, cache_ttl=300.0,
         on_missing_engine="raise") -> PacProxyMap | None    # top level: discover_pac
```

DNS+HTTP WPAD (`proxylib.pac.wpad`): tries `http://wpad.<domain>/wpad.dat` for each
parent domain of `fqdn` (default: this host's FQDN), most specific first, stopping
before a public suffix (a bare TLD or a ccTLD registry level such as `co.uk`); a
domain whose PAC fails to download or run is skipped. Results, failures included, are
cached per fqdn. DHCP option 252 is not implemented.

## Patching clients (`proxylib.patching`)

```python
patch(proxymap, *, targets=None) -> Patch
unpatch() -> None
register_patcher(name, install, *, uninstall, module, unnamed=False, replace=False)
patching.active(target) -> ProxyMap
patching.targets() -> tuple[str, ...]
```

Each client gets proxylib's integration **once**, and it always asks the client's
**active map**: the newest `patch()` covering it, else its default. Built-in targets:

- `"requests"` — new `requests.Session`s mount a `ProxyMapAdapter` for `http://` and
  `https://`;
- `"urllib"` — a global opener with a `ProxyMapHandler`, installed only when the
  program has not installed its own;
- `"httpx"` — `httpx.Client`/`AsyncClient` made without `transport`, `proxy`,
  `proxies` or `mounts` get a `ProxyTransport`/`AsyncProxyTransport`;
- `"aiohttp"` — `ClientSession` requests without a `proxy=` (or with a proxylib value
  as `proxy=`) take it from the active map, with failover.

**When.** As each client is imported, in any program of the environment:
proxylib's importpatch entry points (`requests`, `urllib.request`, `httpx`, `aiohttp`
= `proxylib.integrations.autopatch`) run at interpreter start, and `import proxylib`
registers the same hooks, patching clients already imported at once. Importing
proxylib never imports a client. **Which, and with what default**, is
`PROXYLIB_IMPORTPATCH` (read as each client is imported; see Environment variables):
named targets use `auto_proxy()`; unnamed `requests` and `urllib` are installed with a
default that has **no opinion**, so they choose their proxy exactly as without proxylib;
unnamed `httpx` and `aiohttp` are not installed (their integration would change that).

- `patch(proxymap, *, targets=None)` — makes `proxymap` the active map of every client
  in `targets` (default: all registered) until undone, installing the integration of
  each one covered. Patches nest; the newest covering a client wins. A named target
  whose client is not installed raises `MissingExtraError` (with the default it is
  skipped); an unknown name raises `ValueError`; naming a target imports its client.
- `Patch` — `undo()` (newest first: undoing one a later patch still covers raises
  `RuntimeError`; an ended patch does nothing), a context manager (`with patch(m):`
  undoes on exit), `.active`, `.proxymap`, `.targets` (`None` = all).
- `unpatch()` — ends every patch; every client is back on its default. Installed
  integrations stay.
- `register_patcher` — a client integration: `install(proxymap)` is called once, when
  module `module` has been imported and the target is wanted (named, patched from
  code, or `unnamed=True` for an integration that keeps the client's behaviour while
  its map has no opinion), with a map that always answers as the active map does;
  `uninstall()` removes it. An existing `name` raises `ValueError` unless
  `replace=True`.

## Client integrations (`proxylib.integrations`)

**What each client can use.** Every integration takes an answer's entries in order and
skips the ones its client cannot use, logging each at DEBUG on `proxylib.integrations`;
an answer with nothing usable left (DIRECT always is) raises `UnsupportedProxyError`
instead of sending the request somewhere else.

| | requests | httpx | aiohttp | urllib | `ProxyDict` |
| --- | --- | --- | --- | --- | --- |
| HTTP proxy | yes | yes | yes | yes | yes |
| SOCKS proxy | with `requests[socks]` | with `httpx[socks]` | no | no | yes |
| Proxy `headers` | yes | yes | yes | `Proxy-Authorization` only, for https URLs | no |
| URL-prefix gateway | yes | yes | no | yes | no |

Through a gateway (requests, httpx, urllib) the response keeps the original request and URL, so
cookies and relative redirects belong to the target, and each redirect goes through the
gateway again.

**Failover and health** (requests, httpx, aiohttp): an answer is a list tried in order,
healthy entries first. An entry that fails **before the request is sent** (the proxy,
or for DIRECT the server, refuses or times out connecting) is marked bad for
`bad_proxy_ttl` seconds (default 300) and the next is tried; the last error is
raised. A read or write error never fails over (the server may have the request).
Marks are process-wide, shared with `Probed`, and dropped by `clear_caches()`.

```python
ProxyMapAdapter(proxymap, *args, failover=True, bad_proxy_ttl=300.0, **kwargs)  # .requests
```

A `requests.adapters.HTTPAdapter` subclass hooking `send()`, so it sees the real
request URL. Looking the name up imports requests; constructing it without requests
raises `MissingExtraError`. A `ProxyDict` given as the whole `proxies`, and a caller's
`proxies` entry at the `scheme://hostname` key requests reads first, win over the map
(the caller's entry is sent as is, without failover); a less specific key (bare
`"http"`, or one requests adds from the environment) does not. When the map has no
opinion, requests decides from its `proxies` as usual — but a proxylib value there (a
PAC result such as `"PROXY a:1; DIRECT"`, a list of proxies, or a `Proxy`) is resolved
and failed over; a plain proxy URL stays requests' own.

```python
ProxyMapHandler(proxymap)                                                         # .urllib
```

A `urllib.request.ProxyHandler` subclass resolving per request. It uses the healthiest
usable entry and does not fail over (urllib cannot re-send a request through another
proxy). A proxy's headers are added unredirected; for an https URL only
`Proxy-Authorization` is usable, since urllib moves only that one into the `CONNECT`.
A gateway request goes through the opener's own HTTP(S) handler, and the response
carries the target URL, so `HTTPCookieProcessor` and the redirect handler see the target.
DIRECT falls through to the non-proxying handler; no opinion uses the proxy
`urllib.request.getproxies()` names for the scheme, as the standard handler would.

```python
ProxyTransport(proxymap, *, failover=True, bad_proxy_ttl=300.0, **transport_kwargs)  # .httpx
AsyncProxyTransport(proxymap, *, failover=True, bad_proxy_ttl=300.0, **transport_kwargs)
```

httpx transports: `httpx.Client(transport=ProxyTransport(m))`,
`httpx.AsyncClient(transport=AsyncProxyTransport(m))` (which reads the map with
`alookup`). One inner `HTTPTransport`/`AsyncHTTPTransport` per proxy URL, made on
first use with `transport_kwargs`, closed by `close()`/`aclose()`. Fails over on
`httpx.ProxyError`, `ConnectError`, `ConnectTimeout`. A map with no opinion means
DIRECT (httpx skips its environment proxies when given a transport): chain
`EnvProxyConfig()` in front to honour them. SOCKS needs `httpx[socks]`. Constructing
one without httpx raises `MissingExtraError`.

```python
ProxySession(proxymap, session=None, *, failover=True, bad_proxy_ttl=300.0,
             **session_kwargs)                                                    # .aiohttp
```

Wraps an `aiohttp.ClientSession` (made on first use with `session_kwargs`, or the
`session` given, which is then not closed). `request(method, url, **kwargs)` and
`get`/`post`/`put`/`patch`/`delete`/`head`/`options` resolve the proxy with `alookup`
and send with `proxy=`; the result is awaitable, or an `async with` context that
releases the response. Fails over on `aiohttp.ClientConnectorError` (which includes
`ClientProxyConnectionError`) and connect timeouts. No opinion → the request goes as
aiohttp would send it; a proxylib value as `proxy=` is resolved instead of the map.
A proxy's headers go as `proxy_headers` for an https URL (aiohttp sends those in the
`CONNECT` only) and join the request's headers for a plain-http one, which goes to the
proxy. `close()`, or `async with`. Constructing one without aiohttp raises
`MissingExtraError`.

```python
ProxyDict(proxymap)                                                               # .dict
```

Duck-types the `{scheme_or_url: "proxy://uri"}` dict requests-like libraries accept,
by scheme and host only (path-dependent PAC rules do not apply). The value is the first
entry a URL string can name (no gateway, no headers). DIRECT, and a key
that is not a URL (`"http"`, `"all"`), raise `KeyError`; `setdefault` is a no-op
(requests calls it to merge the environment's proxies; the map wins). Composes a map;
it is not one (`__getitem__` returns `str`).

## Differences from curl, requests and Chromium

- **`NO_PROXY` vs `requests.utils.should_bypass_proxies`** (pinned by tests): a
  default port matches `host:443`; entries are case-insensitive; loopback bypasses
  without being listed; IPv6 CIDR matches bracketed hosts; `*` alone bypasses every
  host (requests leaves that to urllib). As in curl and requests, `*` among other
  entries is ignored, with a warning.
- **Proxy variables**: a lowercase name wins over its uppercase form (curl, the
  standard library); requests reads both. A variable may name a PAC file; curl and
  requests would treat it as a proxy.
- **`shExpMatch`** treats only `*` and `?` as wildcards (`[` is literal) and is
  case-sensitive, as browsers do; Python's `fnmatch` would differ by platform.
- **A PAC result with nothing usable** (empty, or every entry unknown) is DIRECT, as in
  Chromium; unusable entries are dropped with a warning.
- **WPAD** never runs because nothing else was found (Chromium and Windows do the
  same: only when auto-detection is on).

## Caches

```python
clear_caches() -> None
```

Drops every cache proxylib keeps: downloaded PAC scripts, PAC `dnsResolve` answers,
WPAD results, GNOME/MATE settings, local interfaces and the bad-proxy marks. A `Cached`
map keeps its own (`.clear()`).

## Exceptions

- `ProxylibError` — base of every error proxylib raises.
- `ProxyParseError(ProxylibError, ValueError)` — text that should name a proxy or a PAC
  result could not be parsed.
- `PACError(ProxylibError)` — a PAC script raised, ran out of time, or could not be
  loaded as a script.
- `NoReachableProxyError(ProxylibError, LookupError)` — no offered proxy accepted a
  connection (`Probed`).
- `UnsupportedProxyError(ProxylibError)` — a client integration was offered only
  entries its client cannot use (see Client integrations); `.client`, `.proxies` and
  `.reasons` say which and why.
- `MissingExtraError(ProxylibError, ImportError)` — an optional dependency is not
  installed; `.extra` is the proxylib extra (or `None` for a client library), `.name`
  the missing module; the message gives the `pip install` line.

None of them subclasses `KeyError`: `KeyError` from a map always means "no opinion".

## Environment variables

- `HTTP_PROXY`, `HTTPS_PROXY`, `FTP_PROXY`, any `<scheme>_PROXY`, `ALL_PROXY` — read by
  `EnvProxyConfig` and first in `auto_proxy()`'s precedence. A lowercase name wins over
  its uppercase form. Inside a CGI request (`REQUEST_METHOD` set) an uppercase
  `HTTP_PROXY` is ignored (httpoxy); with `os.environ` on Windows, whose names are
  case-insensitive, `http_proxy` is then ignored too. A value may be a PAC location (a
  `file:` URL, or an `http(s)` URL with a path beyond `/`), loaded on first use; a
  whole PAC result (`PROXY a:3128; SOCKS5 b:1080; DIRECT`), tried in order; or a
  gateway (`prefix+https://gw.example/fetch/`).
- `NO_PROXY` / `no_proxy` — bypass rules in the `no_proxy` dialect.
- `PROXYLIB_IMPORTPATCH` — which clients use `auto_proxy()` when imported (Patching
  clients): `1`/`true`/`yes`/`on` for every target, or target names separated by `:`
  (`requests:httpx`; a module name such as `urllib.request` works too); an
  unknown name warns. Unset or empty: none named. `0`/`false`/`no`/`off`: nothing is
  installed until `patch()`.
- `PROXYLIB_JS_ENGINE` — PAC engine priority, comma-separated (`dukpy,quickjs`); an
  unknown name raises `ValueError`.
- `IMPORTPATCH_DISABLE`, `IMPORTPATCH_CONFIG`, `IMPORTPATCH_SYSTEM_CONFIG` — importpatch's
  own: turn its start-up hooks off, or name its configuration files (where
  `proxylib.integrations.autopatch = false` disables a client).
- `XDG_CONFIG_HOME` — where KDE's `kioslaverc` is read.

## Gotchas

- `import proxylib` installs the requests and urllib integrations (behaviour-preserving
  unless `PROXYLIB_IMPORTPATCH` names them) and an import hook; with proxylib installed,
  importpatch's start-up hook does the same in programs that never import proxylib.
  `PROXYLIB_IMPORTPATCH=0` turns it off.
- A map is not a context manager: `with m:` raises `TypeError`. Use
  `contextlib.closing(m)` to close one at the end of a block, or `with patch(m):` to
  make it the clients' map for the block.
- A PAC script runs in a helper process: loading costs a Python start-up (about 0.1 s),
  `functions=` must be importable, and the helper lives until `close()` or garbage
  collection.
- `httpx` and `aiohttp` take no environment proxies once proxylib decides: chain
  `EnvProxyConfig()` into the map, and keep aiohttp's `trust_env` off (with it on, a
  DIRECT answer uses the environment's proxy).
- `ProxyMap` is structural: `isinstance("text", ProxyMap)` is true. Use `ProxyMap(src)`
  to build a map from a configured value.
