# proxylib

Platform-agnostic proxy configuration for Python: detect the system/environment proxy
settings, evaluate PAC (Proxy Auto-Config) files — including WPAD auto-discovery — and
wire the result straight into `requests` or `urllib`.

Zero required runtime dependencies; a couple of optional extras unlock more.

For the full feature list, installation extras, quick-start examples for every
integration, and known limitations, see the
[project README](https://github.com/jose-pr/proxylib#readme). This site adds the
generated [API reference](api/core.md) and the [changelog](changelog.md).

## Installation

```bash
pip install proxylib
```

## Quick start

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
