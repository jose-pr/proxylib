import ipaddress as _ip
import socket as _socket

try:

    import ifaddr as _ifaddr

    def get_local_interfaces():
        ips: list[_ip.IPv4Interface | _ip.IPv6Interface] = []

        for adapter in _ifaddr.get_adapters():
            for ip in adapter.ips:
                if ip.is_IPv4:
                    ip = _ip.IPv4Interface((ip.ip, ip.network_prefix))
                else:
                    ip = _ip.IPv6Interface(
                        (ip.ip[0] + "%" + str(ip.ip[2]), ip.network_prefix)
                    )
                ips.append(ip)
        return ips

except ImportError:

    def get_local_interfaces():
        ip = _socket.gethostbyname(_socket.gethostname())
        ip = _ip.IPv4Interface(f"{ip}/32")
        return [ip]


def get_ip(address: str):
    try:
        try:
            ip = _ip.ip_address(address)
        except:
            ip = _ip.ip_address(_socket.gethostbyname(address))
        return ip
    except:
        return None
