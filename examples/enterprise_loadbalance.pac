// Adapted from documented patterns at
// https://developer.mozilla.org/en-US/docs/Web/HTTP/Guides/Proxy_servers_and_tunneling/Proxy_Auto-Configuration_PAC_file
// (shExpMatch-based routing, multiple-proxy fallback chains) and the classic
// Forcepoint/Websense "load distribution by client subnet" sample PAC
// (isInNet(myIpAddress(), ...) with primary/backup proxy pairs whose order
// flips per subnet so load is spread across both proxies).
function FindProxyForURL(url, host) {
    host = host.toLowerCase();

    // Never proxy internal hosts or the corporate intranet.
    if (isPlainHostName(host) || dnsDomainIs(host, ".corp.example.com")) {
        return "DIRECT";
    }

    // Route by destination pattern, each with its own fallback chain.
    if (shExpMatch(host, "*.example.com")) {
        return "PROXY proxy1.example.com:8080; PROXY proxy4.example.com:8080";
    }
    if (shExpMatch(host, "*.edu")) {
        return "PROXY proxy2.example.com:8080; PROXY proxy4.example.com:8080";
    }

    // Everything else: route by client subnet, alternating which proxy is
    // primary so load is spread across both.
    var me = myIpAddress();
    if (isInNet(me, "10.1.0.0", "255.255.0.0") || isInNet(me, "10.2.0.0", "255.255.0.0")) {
        return "PROXY wcg1.example.com:8080; PROXY wcg2.example.com:8080";
    }
    if (isInNet(me, "10.3.0.0", "255.255.0.0") || isInNet(me, "10.4.0.0", "255.255.0.0")) {
        return "PROXY wcg2.example.com:8080; PROXY wcg1.example.com:8080";
    }

    return "PROXY proxy3.example.com:8080; PROXY proxy4.example.com:8080";
}
