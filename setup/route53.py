"""Create the records in Route 53, but only in a hosted zone the internet actually asks."""
from __future__ import annotations

from .dns import Record, Zone


def find_zone(client, zone: Zone) -> tuple[str, str]:
    """Returns (zone id, status). A hosted zone can exist without being the delegated one: two pilot installs hit
    that (Route 53 held a zone while Netlify/NS1 served the domain), so a match on name alone is not enough."""
    r = client.list_hosted_zones_by_name(DNSName=zone.name, MaxItems="5")["HostedZones"]
    cands = [z for z in r if z["Name"].rstrip(".") == zone.name and not z.get("Config", {}).get("PrivateZone")]
    if not cands:
        return "", "missing"
    for z in cands:
        zid = z["Id"].split("/")[-1]
        ns = {n.rstrip(".").lower() for n in client.get_hosted_zone(Id=zid)["DelegationSet"]["NameServers"]}
        if ns & set(zone.nameservers):
            return zid, "authoritative"
    return cands[0]["Id"].split("/")[-1], "not-authoritative"


def upsert(client, zone_id: str, records: list[Record]) -> None:
    changes = [{"Action": "UPSERT", "ResourceRecordSet": {"Name": r.name, "Type": r.type, "TTL": r.ttl,
                                                          "ResourceRecords": [{"Value": r.value}]}} for r in records]
    client.change_resource_record_sets(HostedZoneId=zone_id, ChangeBatch={"Comment": "tico setup", "Changes": changes})
