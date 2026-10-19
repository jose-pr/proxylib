# proxylib

[![PyPI version](https://img.shields.io/pypi/v/proxylib.svg)](https://pypi.org/project/proxylib/)
[![Python versions](https://img.shields.io/pypi/pyversions/proxylib.svg)](https://pypi.org/project/proxylib/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Docs](https://img.shields.io/badge/docs-latest-blue.svg)](https://jose-pr.github.io/proxylib/)

Platform-agnostic proxy configuration for Python: detect the system/environment proxy
settings, evaluate PAC (Proxy Auto-Config) files — including WPAD auto-discovery — and
wire the result straight into [`requests`](https://requests.readthedocs.io/) or
[`urllib`](https://docs.python.org/3/library/urllib.request.html).

One required runtime dependency, [`netimps`](https://pypi.org/project/netimps/) (network helpers, itself dependency-free); optional extras add a PAC JavaScript engine (see below).

## Features

- **Proxy string parsing** — `PROXY host:port; DIRECT`-style PAC strings, `scheme://host:port`
  URLs, and env-var-style values, all normalized into a common `Proxy` type.
- **One precedence on every OS** — `auto_proxy()` uses the proxy environment variables
  when any is set (as `urllib.request.getproxies()` does), else the OS: its own
  resolver (WinHTTP on Windows, CFNetwork on macOS,
  [libproxy](https://libproxy.github.io/libproxy/) on Linux when installed), backed by
  the OS settings read directly.
- **OS settings as data** — `system_config()` returns a `ProxyConfig`: the Windows
  Internet Options (WinHTTP API), macOS System Configuration (`scutil --proxy`), or
  GNOME, MATE, KDE and NetworkManager settings on Linux. It keeps what each OS stores:
  per-scheme proxies, SOCKS (as the fallback for every other scheme), the PAC URL,
  auto-detection, and the bypass list in that OS's own syntax; and it tells "the OS says
  no proxy" apart from "there are no settings".
- **WPAD only when asked** — auto-detection runs when the OS has it switched on
  ("Automatically detect settings" on Windows, "Auto Proxy Discovery" on macOS, mode
  `auto` with a blank URL on GNOME/MATE, `ProxyType=3` on KDE, NetworkManager
  `proxy.method=auto` with no PAC) or when you pass `wpad=True` on a machine with no
  settings — never because nothing else was found.
- **Env var proxy config** — every `<scheme>_proxy` plus `ALL_PROXY` and `NO_PROXY`
  (lowercase wins), read from any mapping; a PAC URL may be given as a proxy value.
- **Bypass rules in each OS's syntax** — `BypassRules` reads `NO_PROXY` (curl), the
  Windows `ProxyOverride` list, macOS `ExceptionsList`, GNOME `ignore-hosts` and KDE
  `NoProxyFor`: host suffixes, globs, CIDR (IPv4 and IPv6), ports, `<local>`.
- **PAC support** — the full Netscape PAC utility-function set (including
  `dateRange`/`timeRange`) plus the common Microsoft `*Ex` extensions. Scripts run as
  real JavaScript (`quickjs` or `dukpy`) in a helper process with a time limit, so a
  hostile or broken PAC cannot hang your program; a Python function can stand in for
  `FindProxyForURL` too.
- **WPAD discovery** — DNS + HTTP `wpad.<domain>/wpad.dat` lookup, stopping before a
  public suffix such as `co.uk`. Results (including "no WPAD server here") are cached for 5 minutes so repeated
  lookups don't re-probe the network, and DNS resolution fails fast on a hanging lookup.
- **Clients with failover** — `requests` (`ProxyMapAdapter`), `httpx`
  (`ProxyTransport`, `AsyncProxyTransport`) and `urllib` (`ProxyMapHandler`) resolve the
  proxy from the real request URL. A `PROXY a; PROXY b; DIRECT` answer is a failover
  list: a proxy that refuses or times out connecting is skipped for 5 minutes and the
  next entry is tried (urllib uses the healthiest entry).
- **asyncio** — `await alookup(proxymap, url)` reads any map without blocking the event
  loop.
- **Patched clients that behave as before** — importing proxylib gives `requests` and
  `urllib` its adapter and handler, which choose exactly the proxy they always did until
  you call `proxylib.patch(proxymap)` (nestable: `with proxylib.patch(m): ...`). Set
  `PROXYLIB_AUTO_PATCH=1` to use `auto_proxy()` everywhere; install `proxylib[patch]` to
  patch clients in programs that never import proxylib.
- **Composable wrappers** — `ChainProxyMap` for fallback across maps; `Bypass`,
  `Cached`, `RoundRobin` and `Probed` (reachability probing with a circuit breaker),
  composed in the order you write them or with `configure()`.

## Installation

```bash
pip install proxylib
```

Optional extras:

| Extra | Adds | Needed for |
| --- | --- | --- |
| `proxylib[pac]` | `quickjs-ng` (Python ≥3.10) / `quickjs` (Python 3.9) | Executing PAC files as JavaScript (preferred engine) |
| `proxylib[dukpy]` | `dukpy` | The `dukpy` JS engine, for platforms without a quickjs wheel (Windows ARM64) |
| `proxylib[httpx]` | `httpx` | `ProxyTransport` / `AsyncProxyTransport` |
| `proxylib[patch]` | `importpatch` | Patching `requests`/`urllib` in programs that never import proxylib |

Without a JS engine installed, loading a PAC raises `MissingExtraError` naming the
extra to install; pass `on_missing_engine="direct"` to get a warning and DIRECT
instead. With both installed, `quickjs` is preferred; set `PROXYLIB_JS_ENGINE=dukpy`
(or a comma-separated priority list) to change that.

## Quick start

### Auto-detect the system proxy and use it with `requests`

```python
import requests
from proxylib import auto_proxy, ProxyMapAdapter

proxymap = auto_proxy()  # proxy env vars if set, else the OS resolver and settings

session = requests.Session()
adapter = ProxyMapAdapter(proxymap)
session.mount("http://", adapter)
session.mount("https://", adapter)

response = session.get("https://example.com")
```

`ProxyMapAdapter` is the recommended integration: it hooks `HTTPAdapter.send()`, so it
sees the real request URL (scheme, host *and* path) — exactly what a PAC file's
`FindProxyForURL` is meant to receive.

When you don't need that fidelity (no PAC path rules), `ProxyDict` is the simpler
option — a drop-in for any plain proxies dict:

```python
from proxylib import auto_proxy, ProxyDict

requests.get("https://example.com", proxies=ProxyDict(auto_proxy()))
```

### ...or with plain `urllib.request`

```python
import urllib.request
from proxylib import auto_proxy, ProxyMapHandler

proxymap = auto_proxy()
opener = urllib.request.build_opener(ProxyMapHandler(proxymap))
opener.open("https://example.com")

# or, to affect every urllib.request.urlopen() call process-wide:
urllib.request.install_opener(opener)
```

`ProxyMapHandler` subclasses `urllib.request.ProxyHandler` but resolves per-request
from the `ProxyMap` instead of a static `{scheme: proxy_url}` dict, for the same reason
`ProxyMapAdapter` exists for `requests`.

### With `httpx`

```python
import httpx
from proxylib import auto_proxy
from proxylib.integrations.httpx import ProxyTransport

with httpx.Client(transport=ProxyTransport(auto_proxy())) as client:
    client.get("https://example.com")
```

`AsyncProxyTransport` does the same for `httpx.AsyncClient`.

### ...or patch `requests` and `urllib` everywhere

Importing proxylib already gives new `requests.Session`s and urllib's default opener
proxylib's adapter and handler; until you patch, they pick the proxy exactly as
without proxylib.

```python
import proxylib

with proxylib.patch(proxylib.auto_proxy()):
    requests.get("https://example.com")  # resolved by auto_proxy()
# back to requests' own choice here; proxylib.unpatch() ends every patch
```

Patches nest (the newest wins), and `targets=["requests"]` or `["urllib"]` limits one
to a client. `PROXYLIB_AUTO_PATCH=1` makes `auto_proxy()` the default without any
code, and `PROXYLIB_AUTO_PATCH=0` turns the default integration off. With
`pip install "proxylib[patch]"`, the integration is installed whenever `requests` or
`urllib.request` is imported, even in programs that never import proxylib (through
[importpatch](https://pypi.org/project/importpatch/)).

### From environment variables

```python
import proxylib
from proxylib import EnvProxyConfig

proxymap = EnvProxyConfig()  # os.environ: http_proxy / https_proxy / all_proxy / no_proxy
proxylib.lookup(proxymap, "https://example.com")  # -> (Proxy(...),) or (None,) for DIRECT
```

### A fixed proxy, or DIRECT

```python
from proxylib import SimpleProxyMap

proxymap = SimpleProxyMap("http://user:pass@proxy.example.com:8080")
direct = SimpleProxyMap("DIRECT")
```

### Loading a PAC file directly

```python
import proxylib
from proxylib import load_pac, loads_pac

proxymap = load_pac("https://example.com/proxy.pac")  # a URL
proxymap = load_pac("./proxy.pac")                      # or a path
proxymap = loads_pac(script_text)                       # or the script itself
proxylib.lookup(proxymap, "https://example.com/")
```

A script runs with a 5-second budget per call (`script_timeout=`); a call that
overruns raises `PACError`, and the script answers `PACError` at once for 30 seconds
before it is restarted. A script error is `PACError` too.

`ProxyMap(value)` picks the right map for a configured value without doing any
I/O: a proxy URL or PAC result string builds a `SimpleProxyMap`, a PAC location (a
`file:` URL or an `http(s)` URL with a path) is loaded on the first lookup, and
anything else indexable by URL is used as it is.

### Any mapping is a proxy map

A proxy map is anything indexable by request URL — a plain `dict` included, keyed
the way `requests` keys its `proxies` (`"https"`, `"all"`, `"http://host"`). Read
any map's answer with `lookup()`, which always returns a tuple of `Proxy` (or
`None` for DIRECT):

```python
from proxylib import ChainProxyMap, auto_proxy, lookup

proxymap = ChainProxyMap({"https": "http://corp-proxy:3128"}, auto_proxy())
lookup(proxymap, "https://example.com/")  # -> (Proxy(scheme='http', host='corp-proxy', port=3128),)
```

## API overview

| Module | Purpose |
| --- | --- |
| `proxylib.proxy` | Core types: `Proxy`, `ProxyMap` (protocol + factory), `SimpleProxyMap`, `ChainProxyMap`, `lookup()` |
| `proxylib.patching` | `patch()` / `Patch` / `unpatch()` / `register_patcher()` — client integrations and the active map |
| `proxylib.env` | `EnvProxyConfig` — `HTTP_PROXY`/`HTTPS_PROXY`/`NO_PROXY` |
| `proxylib.system` | `auto_proxy()`, `system_config()`, `ProxyConfig`, and the OS resolvers `WinHTTPProxyMap`, `CFNetworkProxyMap`, `LibProxyMap` |
| `proxylib.wrappers` | `Bypass`, `Cached`, `RoundRobin`, `Probed`, `configure()` — maps that wrap another map |
| `proxylib.pac` | `PacScript`, `PacProxyMap`, `load()`, `loads()`, `functions` — PAC scripts and builtins |
| `proxylib.pac.wpad` | `discover()` — DNS+HTTP WPAD auto-discovery |
| `proxylib.pac.engines` | `JSEngine` interface, `names()`, engine selection |
| `proxylib.integrations.requests` | `ProxyMapAdapter` — the recommended `requests` integration |
| `proxylib.integrations.urllib` | `ProxyMapHandler` — a per-request-aware `urllib.request.ProxyHandler` |
| `proxylib.integrations.httpx` | `ProxyTransport`, `AsyncProxyTransport` — httpx transports with failover |
| `proxylib.integrations.dict` | `ProxyDict` — the plain proxies-dict integration |
| `proxylib.exceptions` | `ProxylibError` and its subclasses (re-exported at top level) |

Every `ProxyMap` implementation (`SimpleProxyMap`, `EnvProxyConfig`, `PacProxyMap`, ...) answers
the same question: `proxymap[url]` returns the sequence of `Proxy` (or `None` for
DIRECT) to try, in order.

## Supported Python versions

Python 3.9–3.14. The codebase uses `from __future__ import annotations` so modern
`X | Y` type syntax can be used everywhere while staying importable on 3.9.

## Development

```bash
python -m venv .venv/<your-python-version>
.venv/<your-python-version>/Scripts/pip install -e ".[dev,dukpy,pac]"
.venv/<your-python-version>/Scripts/pytest -q
```

Tests that need `dukpy`/`quickjs` skip automatically if those extras aren't
installed (`requests` and `httpx` come from `dev`: they are test dependencies, while
proxylib itself imports them only when their integration is used).

### Releasing

This project follows [Semantic Versioning](https://semver.org/) and keeps a
[`CHANGELOG.md`](CHANGELOG.md). Pushing a tag matching `v*` (e.g. `v1.0.0`) triggers
[`.github/workflows/release.yaml`](.github/workflows/release.yaml), which runs the test
suite across platforms/Python versions as a gate, then in parallel: builds the
sdist/wheel, creates a GitHub Release (with auto-generated release notes and a diff link
against the previous tag) and publishes it to PyPI via [Trusted
Publishing](https://docs.pypi.org/trusted-publishers/) (no stored token), and
builds+publishes the [documentation site](#documentation-site) to GitHub Pages.

### Documentation site

API reference docs are built with [MkDocs](https://www.mkdocs.org/) +
[mkdocstrings](https://mkdocstrings.github.io/) from `mkdocs.yml`/`docs/`, and
published to GitHub Pages on every release (see above). To preview locally:

```bash
.venv/<your-python-version>/Scripts/pip install -e ".[docs]"
.venv/<your-python-version>/Scripts/mkdocs serve
```

## Known limitations

- **DHCP-based WPAD discovery is not implemented** — only DNS+HTTP (`wpad.<domain>/wpad.dat`).
  Reading DHCP option 252 needs raw OS lease access with no portable stdlib path.
- **Linux desktop settings** are read from GNOME/MATE (`gsettings`), KDE
  (`kioslaverc`) and NetworkManager (`nmcli`, or `dbus-send` if `nmcli` isn't
  installed) with no session detection: the first with a proxy configured wins, even
  if it isn't the active desktop. Xfce, Cinnamon and other desktops are covered only
  through libproxy, if installed — otherwise set `HTTP_PROXY`/`HTTPS_PROXY`/`NO_PROXY`
  (a proxy variable may name a PAC file).
- The NetworkManager `dbus-send` fallback path scrapes `dbus-send`'s
  debug-oriented text output for the specific fields it needs; it hasn't been verified
  against a live NetworkManager D-Bus session, only a best-effort reconstruction of the
  expected format. `nmcli`, when available, is preferred and doesn't have this caveat.
- `dateRange`/`timeRange` implement the documented PAC overload shapes but haven't been
  exhaustively verified against every real-world PAC file's edge cases.
- **urllib does not fail over** — `ProxyMapHandler` uses the healthiest entry of an
  answer but cannot re-send a request through the next one; use `Probed(proxymap)` to
  pre-select a reachable entry, or requests/httpx for request-time failover. Failover
  happens only for errors before the request is sent; a read or write error is raised.

## License

MIT — see [LICENSE](LICENSE).
