# proxylib

[![Version](https://img.shields.io/pypi/v/proxylib.svg)](https://pypi.org/project/proxylib/)
[![Python versions](https://img.shields.io/pypi/pyversions/proxylib.svg)](https://pypi.org/project/proxylib/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](https://github.com/jose-pr/proxylib/blob/main/LICENSE)
[![Docs](https://img.shields.io/badge/docs-latest-blue.svg)](https://jose-pr.github.io/proxylib/)
[![CI](https://img.shields.io/github/actions/workflow/status/jose-pr/proxylib/test.yaml)](https://github.com/jose-pr/proxylib/actions/workflows/test.yaml)

**Which proxy should this request use?** proxylib answers it the same way on every
OS — from the proxy environment variables, the OS's own resolver and settings, or a
PAC file — and gets the answer into `requests`, `urllib`, `httpx` and `aiohttp`, with
failover along the list a PAC returns. Documentation:
<https://jose-pr.github.io/proxylib/>.

## Features

- **One precedence on every OS** — `auto_proxy()` uses the proxy environment variables
  when any is set (as `urllib.request.getproxies()` does), else the OS's own resolver
  (WinHTTP on Windows, CFNetwork on macOS, [libproxy](https://libproxy.github.io/libproxy/)
  on Linux when installed), backed by the OS settings read directly.
- **OS settings as data** — `system_config()` returns a `ProxyConfig` from the Windows
  Internet Options, macOS System Configuration, or GNOME, MATE, KDE and NetworkManager:
  per-scheme proxies, SOCKS, the PAC URL, auto-detection and the bypass list in that
  OS's own syntax, with "the OS says no proxy" told apart from "no settings".
- **WPAD only when asked** — auto-detection runs when the OS has it switched on, or
  with `wpad=True` on a machine with no settings; never because nothing else was found.
- **PAC scripts that cannot hang you** — the full Netscape and Microsoft PAC builtins,
  run as real JavaScript (quickjs or dukpy) in a helper process with a time limit; a
  Python function can stand in for `FindProxyForURL`.
- **Clients with failover** — `requests`, `httpx`, `aiohttp` and `urllib` resolve the
  proxy from the real request URL; a `PROXY a; PROXY b; DIRECT` answer is a failover
  list, and a proxy that refuses or times out connecting is skipped for 5 minutes.
- **Proxy headers and URL-prefix gateways** — a `Proxy` can carry headers sent to that
  proxy only (a Bearer token, or a credential under another header name), and
  `prefix+https://gw/fetch/` (`PREFIX https://gw/fetch/` in a PAC result) names a
  gateway fetching `<gateway><URL>`. A client skips the entries it cannot use and raises
  `UnsupportedProxyError` when none is left, instead of leaking a header or going
  elsewhere.
- **Patched clients that behave as before** — `requests` and `urllib` get proxylib's
  integration as they are imported, choosing exactly the proxy they always did until
  you `patch()` a map in (nestable) or name them in `PROXYLIB_IMPORTPATCH`.
- **Bypass rules in each OS's syntax** — `NO_PROXY` (curl), Windows `ProxyOverride`,
  macOS `ExceptionsList`, GNOME `ignore-hosts`, KDE `NoProxyFor`: suffixes, globs, IPv4
  and IPv6 CIDR, ports, `<local>`, `<subnet>`.
- **Composable** — any mapping is a proxy map; `ChainProxyMap`, `Bypass`, `Cached`,
  `RoundRobin` and `Probed` compose in the order you write them; `alookup()` for
  asyncio.

## Installation

```bash
pip install proxylib
```

Python 3.9 to 3.14. Dependencies: [netimps](https://pypi.org/project/netimps/) and
[importpatch](https://pypi.org/project/importpatch/), neither with dependencies of
its own.

| Extra | Adds | Needed for |
| --- | --- | --- |
| `proxylib[pac]` | `quickjs-ng` (Python 3.10+) / `quickjs` (3.9) | Running PAC files (preferred engine) |
| `proxylib[dukpy]` | `dukpy` | The dukpy engine, for platforms without a quickjs wheel (Windows ARM64, Intel macOS) |

The `requests`, `httpx` and `aiohttp` integrations need no extra: each works when its
client is installed. Without a JS engine, loading a PAC raises `MissingExtraError`
naming the extra; `on_missing_engine="direct"` gives a warning and DIRECT instead.

## Quick start

### Ask the machine

```python
from proxylib import auto_proxy, lookup

proxymap = auto_proxy()  # proxy variables if set, else the OS resolver and settings
print(lookup(proxymap, "https://example.com/"))  # (Proxy(...), ...) or (None,) for DIRECT
proxymap.close()
```

### `requests`

```python
import requests
from proxylib import ProxyMapAdapter, auto_proxy

session = requests.Session()
adapter = ProxyMapAdapter(auto_proxy())
session.mount("http://", adapter)
session.mount("https://", adapter)
response = session.get("https://example.com/")
```

`ProxyMapAdapter` sees the real request URL — scheme, host *and* path, what a PAC's
`FindProxyForURL` expects — and fails over along the answer. A chain also works where
requests takes its proxies:

```python
import requests

requests.get("https://example.com/", proxies={"https": "PROXY proxy.invalid:3128; DIRECT"})
```

(proxylib's integration, installed whenever requests is imported, reads that value; a
plain proxy URL there stays requests' own).

### `httpx` and `aiohttp`

```python
import httpx
from proxylib import auto_proxy
from proxylib.integrations.httpx import ProxyTransport

with httpx.Client(transport=ProxyTransport(auto_proxy())) as client:
    client.get("https://example.com/")
```

`AsyncProxyTransport` does the same for `httpx.AsyncClient`. aiohttp has no transport
hook, so its session is wrapped:

```python
import asyncio

from proxylib import auto_proxy
from proxylib.integrations.aiohttp import ProxySession


async def main():
    async with ProxySession(auto_proxy()) as session:
        async with session.get("https://example.com/") as response:
            return await response.text()


asyncio.run(main())
```

### `urllib`

```python
import urllib.request

from proxylib import ProxyMapHandler, auto_proxy

opener = urllib.request.build_opener(ProxyMapHandler(auto_proxy()))
opener.open("https://example.com/").read()
```

### Patch every client at once

```python
import requests

import proxylib

with proxylib.patch(proxylib.auto_proxy()):
    requests.get("https://example.com/")  # resolved by auto_proxy()
# back to requests' own choice here; proxylib.unpatch() ends every patch
```

Patches nest (the newest wins); `targets=["requests"]` limits one to a client. Without
code, `PROXYLIB_IMPORTPATCH=1` (or client names: `requests:httpx`) makes those clients
use `auto_proxy()` in every program that imports them, through importpatch;
`PROXYLIB_IMPORTPATCH=0` turns the integration off.

### PAC files

```python
from proxylib import load_pac, loads_pac, lookup

script = 'function FindProxyForURL(url, host) { return "PROXY proxy.invalid:3128; DIRECT"; }'
from_text = loads_pac(script)
from_url = load_pac("https://example.com/proxy.pac")  # a URL, or a path
print(lookup(from_text, "https://example.com/"))
from_text.close()
from_url.close()
```

Each call gets 5 seconds (`script_timeout=`): an overrun raises `PACError` and the
script fails fast for 30 seconds before it is restarted.

### Any mapping is a proxy map

```python
from proxylib import Bypass, ChainProxyMap, EnvProxyConfig, SimpleProxyMap, lookup

proxymap = Bypass(
    ChainProxyMap({"https": "http://corp-proxy:3128"}, EnvProxyConfig(), SimpleProxyMap("DIRECT")),
    "*.internal, 10.0.0.0/8",
)
print(lookup(proxymap, "https://example.com/"))  # (Proxy(scheme='http', host='corp-proxy', port=3128),)
print(lookup(proxymap, "https://app.internal/"))  # (None,)
```

## API overview

| Module | Purpose |
| --- | --- |
| `proxylib.proxy` | `Proxy`, the `ProxyMap` protocol and factory, `SimpleProxyMap`, `ChainProxyMap`, `lookup()`, `alookup()` |
| `proxylib.wrappers` | `Bypass`, `Cached`, `RoundRobin`, `Probed`, `configure()` |
| `proxylib.bypass` | `BypassRules` and its dialects |
| `proxylib.env` | `EnvProxyConfig` — the proxy environment variables |
| `proxylib.system` | `auto_proxy()`, `system_config()`, `ProxyConfig`; the OS resolvers `WinHTTPProxyMap`, `CFNetworkProxyMap`, `LibProxyMap` |
| `proxylib.pac` | `load()`, `loads()`, `PacScript`, `PacProxyMap`, `functions`; `.wpad.discover()`; `.engines` |
| `proxylib.patching` | `patch()`, `Patch`, `unpatch()`, `register_patcher()`, `active()`, `targets()` |
| `proxylib.integrations` | `.requests.ProxyMapAdapter`, `.urllib.ProxyMapHandler`, `.httpx.ProxyTransport`/`AsyncProxyTransport`, `.aiohttp.ProxySession`, `.dict.ProxyDict` |
| `proxylib.exceptions` | `ProxylibError` and its subclasses |

The full contract, with every signature, is the API header shipped in the package
(`proxylib/AGENTS.md`) and the [documentation site](https://jose-pr.github.io/proxylib/).
Moving from 1.x: [migration guide](https://jose-pr.github.io/proxylib/migration-2.0/).

## Known limitations

- **DHCP-based WPAD is not implemented** — only DNS+HTTP (`wpad.<domain>/wpad.dat`).
- **Linux desktops** are read without session detection: GNOME/MATE (`gsettings`), KDE
  (`kioslaverc`) and NetworkManager (`nmcli`, or `dbus-send`); the first with a proxy
  configured wins. Other desktops are covered only through libproxy, if installed.
  The `dbus-send` path reads its debug output and has not been checked against a live
  NetworkManager.
- **urllib does not fail over** — `ProxyMapHandler` uses the healthiest entry but cannot
  re-send a request through the next one; use `Probed(proxymap)`, or requests, httpx or
  aiohttp. Failover happens only for errors before the request is sent.
- **SOCKS proxies need the client's SOCKS support**: `requests[socks]` for requests,
  `httpx[socks]` for httpx; aiohttp and urllib speak HTTP proxies only.
- **aiohttp skips gateways** (requests, httpx and urllib take them). urllib
  sends only a `Proxy-Authorization` proxy header for https URLs (it would send any
  other through the tunnel), so it skips a proxy with other headers there.

## Development

```bash
python -m venv .venv/3.14
.venv/3.14/Scripts/python -m pip install -e ".[dev,dukpy]"
.venv/3.14/Scripts/python -m pytest -q -W error::UserWarning
```

(`bin/` instead of `Scripts/` outside Windows.) The quickjs tests need `proxylib[pac]`,
which has no Windows ARM64 wheel; they skip, visibly, without it. The docs build with
`pip install -e ".[docs]"` and `mkdocs build --strict`.

### Releasing

This project follows [Semantic Versioning](https://semver.org/) and keeps a
[`CHANGELOG.md`](https://github.com/jose-pr/proxylib/blob/main/CHANGELOG.md). Pushing a
tag matching `v*` triggers the release workflow: test gate → build (checking the tag
names the version built) → a strict docs build as a gate → GitHub release → publish to
PyPI with trusted publishing. The release workflow never deploys the docs site itself:
for a final release its last job dispatches the docs workflow at the tag, which owns
every Pages deploy.

## License

MIT — see [LICENSE](https://github.com/jose-pr/proxylib/blob/main/LICENSE).
