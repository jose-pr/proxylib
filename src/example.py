from proxylib import JSProxyAutoConfig, Proxy, UriSplit

proxy = Proxy.from_str("direct", UriSplit.PAC)
pac = JSProxyAutoConfig("")
test = pac.dnsResolve("google.com")

pass
