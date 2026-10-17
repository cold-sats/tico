"""Every compose stack the release checks start beside each other needs its own edge network range.

compose.yaml gives the edge network a fixed subnet so the front doors keep fixed addresses, and Docker refuses a
second network on a range already in use ("Pool overlaps with other one on this address space"). The journey and
smoke run side by side in the release gate, and either may run on a computer with a real install on the default range.
"""
import ipaddress
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STACKS = ('scripts/journey-test.sh', 'docker/smoke.sh', 'docker/backup-test.sh')
NAMES = ('TICO_EDGE_SUBNET', 'TICO_EDGE_DYNAMIC_RANGE', 'TICO_CADDY_ADDRESS', 'TICO_CLOUDFLARED_ADDRESS')


def default_subnet():
    match = re.search(r'subnet: \$\{TICO_EDGE_SUBNET:-([0-9./]+)\}', (ROOT / 'compose.yaml').read_text())
    return ipaddress.ip_network(match.group(1))


def edge_settings(path):
    """The edge settings a stack script writes into its env file, with its prefix default filled in."""
    text = (ROOT / path).read_text()
    prefix = re.search(r'edge="\$\{TICO_SMOKE_EDGE:-([0-9.]+)\}"', text)
    if prefix:   # docker/smoke.sh writes the four lines from one prefix
        edge = prefix.group(1)
        return {'TICO_EDGE_SUBNET': f'{edge}.0/28', 'TICO_EDGE_DYNAMIC_RANGE': f'{edge}.8/29',
                'TICO_CADDY_ADDRESS': f'{edge}.2', 'TICO_CLOUDFLARED_ADDRESS': f'{edge}.3'}
    return dict(re.findall(rf'^({"|".join(NAMES)})=(\S+)$', text, re.M))


def test_each_gate_stack_has_its_own_edge_range_inside_its_subnet():
    subnets = {'compose.yaml default': default_subnet()}
    for path in STACKS:
        settings = edge_settings(path)
        assert sorted(settings) == sorted(NAMES), path
        subnet = ipaddress.ip_network(settings['TICO_EDGE_SUBNET'])
        assert ipaddress.ip_network(settings['TICO_EDGE_DYNAMIC_RANGE']).subnet_of(subnet), path
        for name in ('TICO_CADDY_ADDRESS', 'TICO_CLOUDFLARED_ADDRESS'):
            address = ipaddress.ip_address(settings[name])
            assert address in subnet and address not in ipaddress.ip_network(settings['TICO_EDGE_DYNAMIC_RANGE']), path
        for other, taken in subnets.items():
            assert not subnet.overlaps(taken), f'{path} edge range overlaps {other}'
        subnets[path] = subnet
