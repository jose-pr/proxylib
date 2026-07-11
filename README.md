# proxylib

[![PyPI version](https://img.shields.io/pypi/v/proxylib.svg)](https://pypi.org/project/proxylib/)
[![Python versions](https://img.shields.io/pypi/pyversions/proxylib.svg)](https://pypi.org/project/proxylib/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Docs](https://img.shields.io/badge/docs-latest-blue.svg)](https://jose-pr.github.io/proxylib/)

Platform-agnostic proxy configuration for Python: detect the system/environment proxy
settings, evaluate PAC (Proxy Auto-Config) files — including WPAD auto-discovery — and
wire the result straight into [`requests`](https://requests.readthedocs.io/) or
[`urllib`](https://docs.python.org/3/library/urllib.request.html).

Zero required runtime dependencies; a couple of optional extras unlock more (see below).

## Features

- **Proxy string parsing** — `PROXY host:port; DIRECT`-style PAC strings, `scheme://host:port`
  URLs, and env-var-style values, all normalized into a common `Proxy` type.
- **System proxy detection** — Windows (via the WinHTTP API), macOS (`scutil --proxy`),
  and Linux (env vars, plus best-effort [libproxy](https://libproxy.github.io/libproxy/),
  GNOME, MATE, KDE, and NetworkManager checks — tried in that order, first match wins).
  `system_proxy()` respects each OS/desktop's own auto-detect (WPAD) signal —
  "Automatically detect settings" on Windows, "Auto Proxy Discovery" on macOS, mode
  `auto` with a blank Configuration URL on GNOME/MATE, `ProxyType=3` in KDE's
  `kioslaverc`, or NetworkManager's `proxy.method=auto` with no PAC set — and tries
  WPAD itself first, in that platform's own precedence order (auto-detect → PAC script
  → manual proxy → DIRECT). NetworkManager is read via `nmcli` if installed, else
  `dbus-send` directly. `LibProxyMap` (libproxy's own resolution, called via `ctypes`
  bindings to its C API — no subprocess) is also available as a standalone `ProxyMap`
  you can use directly on any platform.
- **Env var proxy config** — `HTTP_PROXY`/`HTTPS_PROXY`/`NO_PROXY` (and lowercase
  variants), with correct exact/subdomain `NO_PROXY` matching.
- **PAC support** — the full Netscape PAC utility-function set (including
  `dateRange`/`timeRange`) plus the common Microsoft `*Ex` extensions, runnable either
  as real JavaScript through a pluggable engine (`dukpy` or `quickjs`, picked via
  `PROXYLIB_JS_ENGINE` or whichever is installed) or by subclassing in Python.
- **WPAD discovery** — DNS + HTTP `wpad.<domain>/wpad.dat` lookup. Used directly by
  `system_proxy()` on any platform/desktop whose own auto-detect setting is on, and as
  a generic last-resort fallback in `auto_proxy()` when nothing else is configured.
  Results (including "no WPAD server here") are cached for 5 minutes so repeated
  lookups don't re-probe the network, and DNS resolution fails fast on a hanging lookup.
- **`requests` integration** — a `ProxyMapAdapter` Transport Adapter that resolves the
  proxy from the real request URL (not just scheme+host).
- **`urllib.request` integration** — `ProxyMapHandler`, the same idea as
  `ProxyMapAdapter` but for the standard library's opener/handler system.
- **Global patching** — `proxylib.patch(proxymap)` wires an active `ProxyMap` into
  newly created `requests.Session`s and a global `urllib` opener, without mounting an
  adapter by hand; `proxylib.unpatch()` undoes it, and any `ProxyMap` also works
  directly as a context manager (`with proxymap:`).
- **Decorators & composition** — `ChainProxyMap` for sequential fallback across
  multiple `ProxyMap`s, and `ConfigurableProxyMap` for opt-in caching, active
  reachability probing (with a circuit breaker for dead proxies), round-robin
  selection, browser-style HTTPS privacy stripping, and local-address bypass.

## Installation

```bash
pip install proxylib
```

Optional extras:

| Extra | Adds | Needed for |
| --- | --- | --- |
| `proxylib[jspac]` | `dukpy` | Executing PAC files as JavaScript — "any working engine" meta-extra |
| `proxylib[dukpy]` | `dukpy` | The `dukpy` JS engine specifically |
| `proxylib[quickjs]` | `quickjs` | The `quickjs` JS engine specifically (no dependency on `dukpy`) |
| `proxylib[ifaddr]` | `ifaddr` | Accurate local network interface/prefix enumeration (used by `NO_PROXY <local>`) |

Without a JS engine installed, PAC files are still fetched and validated, but evaluate
to `DIRECT` (with a warning) since there's no engine to run them. With more than one
installed, `PROXYLIB_JS_ENGINE=dukpy` (or `quickjs`, or a comma-separated priority list)
picks which one runs.

## Quick start

### Auto-detect the system proxy and use it with `requests`

```python
import requests
from proxylib import auto_proxy, ProxyMapAdapter

proxymap = auto_proxy()  # OS settings -> env vars -> WPAD discovery -> DIRECT

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

### ...or patch every new `requests.Session`/`urllib` opener at once

```python
import proxylib

with proxylib.auto_proxy():  # patch() on __enter__, unpatch() on __exit__
    requests.get("https://example.com")  # any new Session picks up the active proxy
```

Outside a `with` block, call `proxylib.patch(proxymap)`/`proxylib.unpatch()` directly,
or pass `targets=["requests"]`/`["urllib"]` to patch just one. Sessions created *before*
`patch()` are untouched.

### From environment variables

```python
from proxylib import EnvProxyConfig

proxymap = EnvProxyConfig.from_env()  # HTTP_PROXY / HTTPS_PROXY / NO_PROXY
proxymap["https://example.com"]  # -> [Proxy(...)] or [None] for DIRECT
```

### A fixed proxy, or DIRECT

```python
from proxylib import SimpleProxyMap

proxymap = SimpleProxyMap("http://user:pass@proxy.example.com:8080")
direct = SimpleProxyMap("DIRECT")
```

### Loading a PAC file directly

```python
from proxylib import load_pac

proxymap = load_pac("https://example.com/proxy.pac")
proxymap = load_pac("file:./proxy.pac")
proxymap["https://example.com/"]
```

`ProxyMap(source)` is a small factory that picks the right implementation for you: a
bare `scheme://host:port` string builds a `SimpleProxyMap`, while anything that looks
like a PAC file/URL is loaded with `load_pac`.

## API overview

| Module | Purpose |
| --- | --- |
| `proxylib.proxy` | Core types: `Proxy`, `ProxyMap` (protocol + factory), `SimpleProxyMap`, `ChainProxyMap`, `ConfigurableProxyMap`, URI parsing |
| `proxylib.patching` | `patch()` / `unpatch()` / `register_patcher()` — global patching registry |
| `proxylib.env` | `EnvProxyConfig` — `HTTP_PROXY`/`HTTPS_PROXY`/`NO_PROXY` |
| `proxylib.os` | `system_proxy()` / `auto_proxy()` — platform dispatch + WPAD fallback |
| `proxylib.os.nt` / `.darwin` | Windows (WinHTTP API) / macOS (`scutil`) system proxy backends |
| `proxylib.os.posix` | Linux dispatch: `.libproxy`, `.gnome`, `.mate`, `.kde`, `.networkmanager` |
| `proxylib.pac` | `PAC`, `JSProxyAutoConfig`, `load()` — PAC utility functions + evaluation |
| `proxylib.pac.wpad` | `discover()` — DNS+HTTP WPAD auto-discovery |
| `proxylib.pac.javascript` | `JSContext` — runs a PAC script against a pluggable engine |
| `proxylib.pac.engines` | `JSEngine` interface, plus the `dukpy`/`quickjs` backends |
| `proxylib.integrations.requests` | `ProxyMapAdapter` — the recommended `requests` integration |
| `proxylib.integrations.urllib` | `ProxyMapHandler` — a per-request-aware `urllib.request.ProxyHandler` |
| `proxylib.integrations.dict` | `ProxyDict` — the plain proxies-dict integration |
| `proxylib.netutils` | `get_ip`, `get_default_port`, `get_local_interfaces`, `first_working_proxy` |

Every `ProxyMap` implementation (`SimpleProxyMap`, `EnvProxyConfig`, `PAC`, ...) answers
the same question: `proxymap[url]` returns the sequence of `Proxy` (or `None` for
DIRECT) to try, in order.

## Supported Python versions

Python 3.9–3.13. The codebase uses `from __future__ import annotations` so modern
`X | Y` type syntax can be used everywhere while staying importable on 3.9.

## Development

```bash
python -m venv .venv/<your-python-version>
.venv/<your-python-version>/Scripts/pip install -e ".[dev,jspac,ifaddr]"
.venv/<your-python-version>/Scripts/pytest -q
```

Tests that need `dukpy`/`quickjs`/`ifaddr` skip automatically if those extras aren't
installed (`requests` comes from `dev`, since it's a real test dependency regardless of
the `requests` integration's own optional-import guard).

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
- **Linux desktop proxy detection** covers libproxy, GNOME/MATE (`gsettings`), KDE
  (`kioslaverc`), and NetworkManager (`nmcli`, or `dbus-send` if `nmcli` isn't
  installed), tried in that fixed order with no session detection to disambiguate — if
  a machine has stale config from more than one of these, the first one with anything
  set wins, even if it isn't the active desktop. Xfce, Cinnamon, and other desktop
  environments aren't covered directly (though libproxy, if installed, may cover them)
  — set `HTTP_PROXY`/`HTTPS_PROXY`/`NO_PROXY` or `PROXY_PAC` explicitly otherwise.
- The NetworkManager `dbus-send` fallback path scrapes `dbus-send`'s
  debug-oriented text output for the specific fields it needs; it hasn't been verified
  against a live NetworkManager D-Bus session, only a best-effort reconstruction of the
  expected format. `nmcli`, when available, is preferred and doesn't have this caveat.
- `dateRange`/`timeRange` implement the documented PAC overload shapes but haven't been
  exhaustively verified against every real-world PAC file's edge cases.
- **No automatic proxy failover in the adapters themselves** — `ProxyMapAdapter`/
  `ProxyMapHandler` use the first proxy a `ProxyMap` returns; they don't retry the rest
  of a `PROXY a; PROXY b; DIRECT` chain on connection failure. Wrap your map with
  `ConfigurableProxyMap(proxymap, probe=True)` (active reachability probing, with a
  circuit breaker for proxies that keep failing), or call
  `first_working_proxy(proxymap[url])` directly, to pre-select a reachable entry.

## License

MIT — see [LICENSE](LICENSE).
