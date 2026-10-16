"""Client addresses from explicitly trusted proxies; forwarded headers are otherwise ignored."""

from ipaddress import ip_address, ip_network


def trusted_proxies(values):
    parts = values.split(',') if isinstance(values, str) else values
    return tuple(str(ip_network(value.strip(), strict=False)) for value in parts if value.strip())


def client_ip(request, settings):
    peer = request.client.host if request.client else ''
    try:
        address = ip_address(peer)
    except ValueError:
        return 'unknown'
    networks = tuple(ip_network(value) for value in settings.trusted_proxies)
    trusted = lambda ip: any(ip.version == net.version and ip in net for net in networks)
    if not trusted(address):
        return str(address)
    raw = request.headers.get(settings.client_ip_header, '')
    if not raw or len(raw) > 2048:
        return str(address)
    try:
        if settings.client_ip_header == 'cf-connecting-ip':
            return str(ip_address(raw.strip()))
        chain = raw.split(',')
        if len(chain) > 32:
            return str(address)
        for part in reversed(chain):
            if not trusted(address):
                break
            address = ip_address(part.strip())
    except ValueError:
        return peer
    return str(address)


def ip_bucket(address):
    try:
        ip = ip_address(address)
    except ValueError:
        return 'unknown'
    return str(ip_network(f'{ip}/64', strict=False)) if ip.version == 6 else str(ip)
