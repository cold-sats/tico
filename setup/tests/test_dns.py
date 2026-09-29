

from setup import dns
from setup.tests.fakes import NETLIFY_NS, FakeResolver


def test_zone_walks_up_to_the_first_name_with_ns():
    r = FakeResolver(ns={"example.com": NETLIFY_NS})
    z = dns.detect_zone("tico.corp.example.com", r)
    assert z.name == "example.com" and z.provider.key == "netlify"


def test_resolves_to_requires_every_planned_address():
    rec = [dns.Record("A", "t.example.com", "1.2.3.4")]
    assert dns.resolves_to("t.example.com", rec, FakeResolver({("t.example.com", dns.A): ["1.2.3.4"]}))
    assert not dns.resolves_to("t.example.com", rec, FakeResolver({("t.example.com", dns.A): ["9.9.9.9"]}))
    assert not dns.resolves_to("t.example.com", rec, FakeResolver())

