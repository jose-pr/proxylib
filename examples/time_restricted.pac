// Adapted from the documented weekdayRange/dateRange/timeRange patterns at
// https://pactester.brdbnt.com/pacfunctions.html and
// https://developer.mozilla.org/en-US/docs/Web/HTTP/Guides/Proxy_servers_and_tunneling/Proxy_Auto-Configuration_PAC_file
//
// A time-of-day/weekday/date-based routing policy: proxy only during
// weekday business hours, direct otherwise (evenings, weekends, and an
// annual holiday blackout week).
function FindProxyForURL(url, host) {
    host = host.toLowerCase();

    // Always bypass the intranet, any time.
    if (dnsDomainIs(host, ".intranet.example.com")) {
        return "DIRECT";
    }

    // Annual holiday blackout: no proxy during the last week of December.
    if (dateRange(24, "DEC", 31, "DEC")) {
        return "DIRECT";
    }

    // Weekends: no proxy.
    if (weekdayRange("SAT", "SUN")) {
        return "DIRECT";
    }

    // Weekday business hours (8am-6pm, local time): use the daytime proxy.
    if (timeRange(8, 0, 0, 18, 0, 0)) {
        return "PROXY businesshours.example.com:8080; DIRECT";
    }

    // Weekday, outside business hours: use the after-hours proxy.
    return "PROXY afterhours.example.com:8080; DIRECT";
}
