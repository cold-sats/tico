import struct

import pytest

from setup import dns
from setup.tests.fakes import AWS_NS, NETLIFY_NS, FakeResolver


@pytest.mark.parametrize("ns,key", [
    (AWS_NS, "route53"), (["elliott.ns.cloudflare.com"], "cloudflare"), (NETLIFY_NS, "netlify"),
    (["ns1.vercel-dns.com"], "vercel"), (["ns-cloud-a1.googledomains.com"], "google"),
    (["ns53.domaincontrol.com"], "godaddy"), (["dns1.registrar-servers.com"], "namecheap"),
    (["ns1.example-dns.net"], "unknown"), ([], "unknown"),
])
def test_detect_provider(ns, key):
    assert dns.detect_provider(ns).key == key


def test_zone_walks_up_to_the_first_name_with_ns():
    r = FakeResolver(ns={"example.com": NETLIFY_NS})
    z = dns.detect_zone("tico.corp.example.com", r)
    assert z.name == "example.com" and z.provider.key == "netlify"


def test_delegated_subdomain_wins_over_parent():
    r = FakeResolver(ns={"example.com": NETLIFY_NS, "tico.example.com": AWS_NS})
    assert dns.detect_zone("tico.example.com", r).provider.key == "route53"


def test_zone_none_when_nothing_resolves():
    assert dns.detect_zone("tico.example.invalid", FakeResolver()) is None


def test_plan_records():
    assert dns.plan_records("t.example.com", "caddy", ipv4="1.2.3.4", ipv6="::1") == [
        dns.Record("A", "t.example.com", "1.2.3.4"), dns.Record("AAAA", "t.example.com", "::1")]
    (r,) = dns.plan_records("t.example.com", "cloudflared", tunnel_id="abc")
    assert (r.type, r.value, r.proxied) == ("CNAME", "abc.cfargotunnel.com", True)


def test_relative_names_and_manual_text_names_the_provider():
    assert dns.relative_name("example.com", "example.com") == "@"
    assert dns.relative_name("tico.example.com", "example.com") == "tico"
    z = dns.Zone("example.com", tuple(NETLIFY_NS), dns.detect_provider(NETLIFY_NS))
    text = "\n".join(dns.manual_instructions([dns.Record("A", "tico.example.com", "1.2.3.4")], z))
    assert "Netlify" in text and "tico" in text and "1.2.3.4" in text


def test_resolves_to_requires_every_planned_address():
    rec = [dns.Record("A", "t.example.com", "1.2.3.4")]
    assert dns.resolves_to("t.example.com", rec, FakeResolver({("t.example.com", dns.A): ["1.2.3.4"]}))
    assert not dns.resolves_to("t.example.com", rec, FakeResolver({("t.example.com", dns.A): ["9.9.9.9"]}))
    assert not dns.resolves_to("t.example.com", rec, FakeResolver())


def test_wait_polls_until_all_resolvers_agree_then_stops():
    rec = [dns.Record("A", "t.example.com", "1.2.3.4")]
    good = FakeResolver({("t.example.com", dns.A): ["1.2.3.4"]})
    late = FakeResolver()
    now, msgs = [0.0], []

    def sleep(s):
        now[0] += s
        if now[0] >= 30:
            late.records[("t.example.com", dns.A)] = ["1.2.3.4"]

    assert dns.wait_until_live("t.example.com", rec, [("G", good), ("C", late)], timeout=300, interval=10,
                               say=msgs.append, sleep=sleep, clock=lambda: now[0])
    assert now[0] == 30 and any("waiting" in m for m in msgs)


def test_wait_times_out_with_a_clear_message():
    now, msgs = [0.0], []

    def sleep(s):
        now[0] += s

    ok = dns.wait_until_live("t.example.com", [dns.Record("A", "t.example.com", "1.2.3.4")], [("G", FakeResolver())],
                             timeout=60, interval=20, say=msgs.append, sleep=sleep, clock=lambda: now[0])
    assert not ok and "Still not resolving on G" in msgs[-1] and "re-run" in msgs[-1]


def test_wire_parser_follows_name_compression():
    def name(s):
        return b"".join(bytes([len(p)]) + p.encode() for p in s.split(".")) + b"\0"
    q = name("example.com") + struct.pack(">HH", dns.NS, 1)
    ans = b"\xc0\x0c" + struct.pack(">HHIH", dns.NS, 1, 60, 6) + b"\x03ns1\xc0\x0c"
    data = struct.pack(">HHHHHH", 1, 0x8180, 1, 1, 0, 0) + q + ans
    assert dns._parse_answers(data, dns.NS) == ["ns1.example.com"]
