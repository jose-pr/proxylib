// Exercises the Microsoft PAC extension functions documented at
// https://pactester.brdbnt.com/pacfunctions.html and
// https://learn.microsoft.com/previous-versions//cc251110(v=msdn.10)
// (IPv6-aware corporate network detection for WPAD environments).
function FindProxyForURL(url, host) {
    host = host.toLowerCase();

    // Real WPAD files commonly gate the newer *Ex functions behind an
    // engine-capability check like this.
    if (getClientVersion() === "") {
        return "PROXY legacy-fallback.example.com:8080";
    }

    if (isPlainHostName(host)) {
        return "DIRECT";
    }

    if (!isResolvableEx(host)) {
        return "PROXY unreachable-fallback.example.com:8080";
    }

    // sortIpAddressList: prefer the numerically-first address for a
    // dual-stack (IPv4 + IPv6) host.
    var addresses = sortIpAddressList(dnsResolveEx(host));

    // isInNetEx/myIpAddressEx: IPv6-safe equivalents of isInNet/myIpAddress,
    // needed since isInNet only understands IPv4.
    if (isInNetEx(myIpAddressEx().split("; ")[0], "127.0.0.0/8")) {
        return "DIRECT";
    }

    return "PROXY proxy.example.com:8080; DIRECT";
}
