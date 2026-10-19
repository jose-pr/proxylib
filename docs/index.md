# proxylib

**Which proxy should this request use?** proxylib answers it the same way on every OS
— from the proxy environment variables, the OS's own resolver and settings, or a PAC
file — and gets the answer into `requests`, `urllib`, `httpx` and `aiohttp`, with
failover along the list a PAC returns.

Moving from 1.x? Read the [migration guide](migration-2.0.md).

## Installation

```bash
pip install proxylib
```

| Extra | Adds | Needed for |
| --- | --- | --- |
| `proxylib[pac]` | `quickjs-ng` (Python 3.10+) / `quickjs` (3.9) | Running PAC files |
| `proxylib[dukpy]` | `dukpy` | The dukpy engine (Windows ARM64) |

The `requests`, `httpx` and `aiohttp` integrations need no extra.

## 30-second tour

```python
from proxylib import auto_proxy, lookup

proxymap = auto_proxy()
lookup(proxymap, "https://example.com/")  # (Proxy(...), ...) or (None,) for DIRECT
```

```python
import requests
from proxylib import ProxyMapAdapter, auto_proxy

session = requests.Session()
session.mount("https://", ProxyMapAdapter(auto_proxy()))
session.get("https://example.com/")
```

```python
import proxylib

with proxylib.patch(proxylib.auto_proxy()):
    ...  # every requests, urllib, httpx and aiohttp client uses auto_proxy()
```

## Learn more

- [Proxies and proxy maps](api/core.md), [wrappers](api/wrappers.md),
  [bypass rules](api/bypass.md), [environment variables](api/env.md)
- [System settings](api/system.md), [PAC support](api/pac.md)
- [Patching clients](api/patching.md), [client integrations](api/integrations.md)
- [Exceptions](api/exceptions.md), [changelog](changelog.md)
