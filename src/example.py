import requests

from proxylib import (
    JSProxyAutoConfig,
    Proxy,
    RequestsProxies,
    SimpleProxyMap,
    UriSplit,
    netutils,
)

proxymap = SimpleProxyMap("proxy 10.7.19.1:9095")
pac = JSProxyAutoConfig("")
test = pac.dnsResolve("google.com")

addrs = netutils.get_local_interfaces()

proxies = RequestsProxies(proxymap)

test = requests.get("https://google.com", proxies=proxies)

pass
