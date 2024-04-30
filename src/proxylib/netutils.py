import ipaddress as _ip
import socket as _socket

try:

    import ifaddr as _ifaddr

    def get_local_interfaces():
        ips: list[_ip.IPv4Interface | _ip.IPv6Interface] = []

        for adapter in _ifaddr.get_adapters():
            print("IPs of network adapter " + adapter.nice_name)
            for ip in adapter.ips:
                if_ = f"{ip.ip}/{ip.network_prefix}"
                if ip.is_IPv4:
                    ip = _ip.IPv4Interface(if_)
                else:
                    ip = _ip.IPv6Interface(if_)
                ips.append(ip)
        return ips

except ImportError:

    def get_local_interfaces():
        return []


def get_ip(address: str):
    try:
        ip = _ip.ip_address(address)
    except:
        ip = _ip.ip_address(_socket.gethostbyname(address))
    return ip
