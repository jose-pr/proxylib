import requests

from proxylib import (
    JSProxyAutoConfig,
    Proxy,
    ProxyMap,
    RequestsProxies,
    SimpleProxyMap,
    UriSplit,
    netutils,
)

proxymap = SimpleProxyMap("DIRECT")

addrs = netutils.get_local_interfaces()

proxies = RequestsProxies(proxymap)
test = requests.get("https://google.com", proxies=proxies)


proxies = ProxyMap("file:examples/example.pac")

pass
