# Migrating from 1.x to 2.0

proxylib 2.0 keeps the question it answers — which proxy should this request use —
and the ways it gets the answer into clients, but cleans up the API around it. The
floor stays Python 3.9.

The three changes most programs notice:

- **Read answers with `lookup(proxymap, url)`.** It returns a tuple of `Proxy` (or
  `None` for DIRECT) for every kind of map, a plain `dict` included. Indexing a map
  yourself still works, but a map may answer with any shape `lookup` normalises.
- **`KeyError` means "no opinion"** everywhere, and nothing proxylib raises is a
  `KeyError` otherwise (`ProxylibError` and its subclasses).
- **`auto_proxy()` reads the proxy environment variables first on every OS**, then the
  OS's own resolver (WinHTTP, CFNetwork, libproxy), then the OS settings. WPAD runs only
  when the OS has auto-detection on (or `wpad=True` on a machine with no settings).

## Names

| 1.x | 2.0 |
| --- | --- |
| `proxymap[url]` returning a list | `lookup(proxymap, url)` → `tuple[Proxy | None, ...]` (`alookup` for asyncio) |
| `proxymap.get(url, default)`, `url in proxymap` | `lookup()`, catching `KeyError` |
| `with proxymap:` (patched every client) | `with proxylib.patch(proxymap):` (nestable); `contextlib.closing(m)` to close a map |
| `ProxyMap(src)` | unchanged — and now does no I/O (a PAC location loads on first lookup) |
| `Proxy(scheme, host, port, ...)` with `port=0`, `username=""` for "none" | `Proxy(scheme, host, port=None, username=None, password=None)`; absent values are `None` |
| `Proxy.from_str(text)`, `Proxy.find_all(text)` | `Proxy.parse(text)`, `Proxy.parse_pac_result(text)` |
| `Proxy.as_uri()` | `Proxy.uri()` (credentials percent-encoded); `.url` has none |
| `UriSplit` | removed (use `urllib.parse.urlsplit`) |
| `ConfigurableProxyMap(m, cache_ttl=, probe=, round_robin=, no_proxy=)` | `configure(m, cache_ttl=, probe=, round_robin=, bypass=)`, or `Cached`, `RoundRobin`, `Probed`, `Bypass` composed yourself |
| `ConfigurableProxyMap(browser_compatibility=True)` | `PacProxyMap(script, browser_compatibility=True)` |
| `ConfigurableProxyMap(bypass_local=True)`, `<local>` = loopback/link-local/subnet | the `<subnet>` bypass token; `<local>` now means a dotless host name (WinINet) |
| `ConfigurableProxyMap(probe=True)` raising `KeyError` when nothing is reachable | `Probed` raises `NoReachableProxyError` (a `LookupError`) |
| `set_default_no_proxy(...)`, `get_default_no_proxy()` | pass rules where a map is built: `auto_proxy(no_proxy=...)`, `EnvProxyConfig(no_proxy=...)`, `Bypass(m, rules)` |
| `EnvProxyConfig(http_proxy, https_proxy, no_proxy)` | `EnvProxyConfig({}, proxies={"http": ..., "https": ...}, no_proxy=...)` |
| `EnvProxyConfig.from_env()` | `EnvProxyConfig()` (reads `os.environ`; pass any mapping as `env`) |
| `PROXY_PAC=<url>` | put the PAC URL in `HTTP_PROXY`/`HTTPS_PROXY` (a `file:` URL, or an `http(s)` URL with a path) |
| `PAC` subclass overriding `find_proxy_for_url` | `PacProxyMap(callable)` — any `FindProxyForURL(url, host)` function |
| `JSProxyAutoConfig(script)` | `PacProxyMap(PacScript(script))`, or `loads_pac(script)` |
| `load_pac(script_text)` / `pac.load(script_text)` | `loads_pac(script_text)` / `pac.loads(script_text)`; `load_pac` takes a URL or a path only |
| `pac.load(url, cache_ttl, **urllib_kwds)` | `pac.load(url, *, timeout=, cache_ttl=, script_timeout=, engine=, on_missing_engine=)` |
| a PAC script error (engine-specific exception) | `PACError`; a script that runs too long raises `PACError` instead of hanging |
| no JS engine installed: warning, DIRECT | `MissingExtraError`; `on_missing_engine="direct"` for the old behaviour |
| `pac.clear_download_cache()`, `pac.clear_dns_cache()` | `proxylib.clear_caches()` |
| `pac.engines.get_engine_class(name)` | `pac.engines.get_engine(name)`; `names()` |
| `system_proxy(provider="python")` | `system_config().to_proxymap()` (or `auto_proxy(system=False)`) |
| `system_proxy(provider="system")`, `auto_proxy(provider="system")` | `auto_proxy()` (the OS resolver is the default) |
| `auto_proxy(provider="python")` | `auto_proxy(system=False)` |
| `auto_proxy(**urlopen_kwargs)` | `auto_proxy(timeout=..., on_missing_engine=...)` |
| `proxylib.os.*` | `proxylib.system` (`system_config`, `ProxyConfig`, `auto_proxy`, the resolvers) |
| `proxylib.os.nt.WinHttpProxyMap` | `proxylib.system.WinHTTPProxyMap` |
| `proxylib.LibProxyMap` | `proxylib.system.LibProxyMap` |
| `first_working_proxy`, `proxylib.netutils.*` | `Probed(m)`; host and network helpers come from [netimps](https://pypi.org/project/netimps/) |
| `register_patcher(name, patch_func, unpatch_func)` | `register_patcher(name, install, uninstall=..., module="client.module")` |
| `patch(m)` replacing the active patch with a warning | `patch(m)` returns a `Patch`; patches nest, newest wins |
| extras `jspac`, `quickjs`, `ifaddr` | `pac` (quickjs) and `dukpy`; no extra needed for local interfaces |

## Behaviour that changed

- **Patching.** Importing proxylib gives `requests`, `urllib`, `httpx`, `aiohttp` and
  pip an integration that chooses exactly the proxy they would without proxylib — and
  reads a PAC result or gateway in a proxy variable, which they cannot — until you
  `patch()` a map in. Through [importpatch](https://pypi.org/project/importpatch/) (a
  dependency) this also happens in programs that never import proxylib.
  `PROXYLIB_AUTOPROXY=1` (or client names: `requests:httpx:aiohttp`) makes those clients
  use `auto_proxy()`; `PROXYLIB_IMPORTPATCH` chooses which clients are integrated at all,
  and `PROXYLIB_IMPORTPATCH=0` turns the integration off.
- **Failover.** `ProxyMapAdapter`, the httpx transports and the aiohttp `ProxySession`
  try the next entry of a `PROXY a; PROXY b; DIRECT` answer when one refuses or times
  out connecting.
- **PAC scripts run in a helper process.** Loading a script starts one (about 0.1 s);
  `functions=` must be importable module-level functions; `close()` the map (or let it
  be collected) to end it.
- **Environment variables**: a lowercase name now wins over its uppercase form, every
  `<scheme>_proxy` is read (plus `all_proxy`), and `ws`/`wss` use the `http`/`https`
  proxies.
- **OS settings** keep SOCKS-only and per-protocol proxies; an `https`-only setting no
  longer serves `http` URLs.

## Example: a program routing egress through proxylib

1.x:

```text
from proxylib import EnvProxyConfig, auto_proxy, load_pac, system_proxy
from proxylib import pac

upstream = {
    "env": EnvProxyConfig.from_env(),
    "system": system_proxy(provider="system"),
    "auto": auto_proxy(),
    "pac": pac.load(generated_script_text),
}[setting]
for proxy in upstream[url]:
    ...
```

2.0:

```text
from proxylib import EnvProxyConfig, auto_proxy, lookup, loads_pac

upstream = {
    "env": EnvProxyConfig(),
    "system": auto_proxy(environ={}),     # the OS only, whatever the environment says
    "auto": auto_proxy(),
    "pac": loads_pac(generated_script_text),
}[setting]
for proxy in lookup(upstream, url):        # or: await alookup(upstream, url)
    ...
upstream.close()                           # ends a PAC helper process, if any
```
