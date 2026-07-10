import urllib.request

import requests

from proxylib import (
    ProxyMap,
    ProxyMapAdapter,
    ProxyMapHandler,
    SimpleProxyMap,
    auto_proxy,
    netutils,
)

# Auto-detect the system/env proxy (or fall back to WPAD discovery).
proxymap = auto_proxy()

addrs = netutils.get_local_interfaces()

# Recommended requests integration: mount a ProxyMapAdapter so every request's
# real URL (not just its scheme/host) is matched against the ProxyMap.
session = requests.Session()
adapter = ProxyMapAdapter(proxymap)
session.mount("http://", adapter)
session.mount("https://", adapter)
response = session.get("https://google.com")

# A PAC file can also be loaded and used directly.
pac_proxymap = ProxyMap("file:examples/example.pac")
session.mount("http://", ProxyMapAdapter(pac_proxymap))
session.mount("https://", ProxyMapAdapter(pac_proxymap))

# Same idea for plain urllib.request instead of requests:
opener = urllib.request.build_opener(ProxyMapHandler(proxymap))
opener.open("https://google.com")
# or, to affect every urllib.request.urlopen() call process-wide:
urllib.request.install_opener(opener)

# For always-DIRECT (no proxy) use:
direct = SimpleProxyMap("DIRECT")
