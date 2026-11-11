"""Email setup: CNAME records are checked by where they point.

Resend's Forge gives new domains a CNAME return path. On lovecityc.com
(2026-11-11) it is `rsend` → send.forge.rmta.net. The checker used to
look every non-MX row up as TXT; the resolver followed the CNAME and
handed back Forge's own SPF ("v=spf1 ip4:52.3.252.119 …"), so a correct
record showed as "Different value, replace it". It also kept required_ok
false, so the screen never auto-verified.
"""
from __future__ import annotations

import asyncio
import pathlib
import sys

_here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))
sys.path.insert(0, str(_here))

import email_domain_dns as edd  # noqa: E402
from test_email_setup_rails import RESEND_RECORDS, _stub_resolver  # noqa: E402

FORGE = {"record": "SPF", "type": "CNAME", "name": "rsend",
         "value": "send.forge.rmta.net", "ttl": "Auto", "priority": None,
         "status": "pending"}
FORGE_SPF = "v=spf1 ip4:52.3.252.119 ip4:44.222.39.36 ip4:199.249.231.0/24 ~all"
ZONE = "lovecityc.com"


def test_compare_cname_ignores_case_and_trailing_dot():
    assert edd.compare_cname("send.forge.rmta.net", ["Send.Forge.RMTA.net."]) == {
        "found": True, "match": True}
    assert edd.compare_cname("send.forge.rmta.net", ["other.example.com"]) == {
        "found": True, "match": False}
    assert edd.compare_cname("send.forge.rmta.net", []) == {"found": False, "match": False}
    assert edd.compare_cname("", ["send.forge.rmta.net"])["match"] is False


def test_a_correct_forge_cname_is_found_not_different(monkeypatch):
    recs = edd.with_dmarc(RESEND_RECORDS + [FORGE], ZONE)
    _stub_resolver(
        monkeypatch,
        # What a TXT lookup of rsend returns in real life: the target's SPF.
        txt={f"send.{ZONE}": ["v=spf1 include:amazonses.com ~all"],
             f"resend._domainkey.{ZONE}": [RESEND_RECORDS[2]["value"]],
             f"rsend.{ZONE}": [FORGE_SPF]},
        mx={f"send.{ZONE}": [(10, "feedback-smtp.us-east-1.amazonses.com")]},
        ns=["dns1.registrar-servers.com"],
        cname={f"rsend.{ZONE}": ["send.forge.rmta.net"]})
    out = asyncio.run(edd.check_records(ZONE, recs))
    forge = next(r for r in out["records"] if r["type"] == "CNAME")
    assert forge["dns"] == {"found": True, "match": True,
                            "found_values": ["send.forge.rmta.net"]}
    assert out["required_ok"] is True        # the screen can auto-verify now


def test_a_cname_pointing_elsewhere_shows_where_it_points(monkeypatch):
    _stub_resolver(monkeypatch, txt={}, mx={}, ns=[],
                   cname={f"rsend.{ZONE}": ["old-provider.example.net"]})
    out = asyncio.run(edd.check_records(ZONE, [FORGE]))
    v = out["records"][0]["dns"]
    assert v["found"] is True and v["match"] is False
    assert v["found_values"] == ["old-provider.example.net"]
    assert out["required_ok"] is False


def test_a_missing_cname_is_not_found(monkeypatch):
    _stub_resolver(monkeypatch, txt={f"rsend.{ZONE}": []}, mx={}, ns=[])
    out = asyncio.run(edd.check_records(ZONE, [FORGE]))
    assert out["records"][0]["dns"] == {"found": False, "match": False, "found_values": []}


def test_namecheap_note_sends_the_other_records_to_host_records():
    mail = edd.mail_state(ZONE, [], [], None)
    note = edd.namecheap_note("namecheap", mail, edd.with_dmarc(RESEND_RECORDS + [FORGE], ZONE))
    assert any("The other records from the list go in Host Records" in s for s in note["steps"])
