"""Email setup on Namecheap, and the operator's own mail.

Namecheap hides MX behind its Mail Settings switch, and switching to
Custom MX deletes the apex mail records Namecheap was managing. The
setup screen has to say so, list what to put back, and notice when it
wasn't put back. Found 2026-11-11 setting up Love City on lovecityc.com;
the records below are that domain's real Email Forwarding set.
"""
from __future__ import annotations

import asyncio
import pathlib
import sys

_here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))
sys.path.insert(0, str(_here))

import email_domain_dns as edd  # noqa: E402
import email_domains_router as edr  # noqa: E402
from test_email_setup_rails import (  # noqa: E402,F401  (fake is a fixture)
    RESEND_RECORDS, _cfg, _recorded_send, _stub_resolver, _u, fake)

EFORWARD = [(10, "eforward1.registrar-servers.com"), (10, "eforward2.registrar-servers.com"),
            (10, "eforward3.registrar-servers.com"), (15, "eforward4.registrar-servers.com"),
            (20, "eforward5.registrar-servers.com")]
EFWD_SPF = "v=spf1 include:spf.efwd.registrar-servers.com ~all"
NAMECHEAP_NS = ["dns1.registrar-servers.com", "dns2.registrar-servers.com"]


# ─── Pure rules ──────────────────────────────────────────────────────


def test_mail_service_names_the_provider():
    assert edd.mail_service_name(EFORWARD) == "Namecheap Email Forwarding"
    assert edd.mail_service_name([(10, "mx1.privateemail.com")]) == "Namecheap Private Email"
    assert edd.mail_service_name([(1, "aspmx.l.google.com")]) == "Google Workspace"
    assert edd.mail_service_name([(0, "studiok-com.mail.protection.outlook.com")]) == "Microsoft 365"
    assert edd.mail_service_name([(10, "mail.studiok.com")]) is None
    assert edd.mail_service_name([]) is None


def test_snapshot_is_never_an_empty_answer():
    assert edd.mail_snapshot([], [EFWD_SPF]) is None
    snap = edd.mail_snapshot(EFORWARD, ["google-site-verification=x", EFWD_SPF], "t0")
    assert snap["mx"][0] == [10, "eforward1.registrar-servers.com"] and len(snap["mx"]) == 5
    assert snap["spf"] == EFWD_SPF and snap["seen_at"] == "t0"


def test_snapshot_updates_only_on_first_sight_or_a_deliberate_move():
    before = edd.mail_snapshot(EFORWARD, [EFWD_SPF])
    assert edd.snapshot_needs_update(None, EFORWARD) is True
    assert edd.snapshot_needs_update(before, EFORWARD) is False          # unchanged
    assert edd.snapshot_needs_update(before, []) is False                # vanished: keep the old list
    assert edd.snapshot_needs_update(before, EFORWARD[:3]) is False      # shrank: keep the old list
    assert edd.snapshot_needs_update(before, [(1, "aspmx.l.google.com")]) is True  # moved on purpose


def test_mail_state_missing_lost_and_moved():
    before = edd.mail_snapshot(EFORWARD, [EFWD_SPF])
    ok = edd.mail_state("lovecityc.com", EFORWARD, [EFWD_SPF], before)
    assert ok["missing"] is False and ok["lost"] == [] and len(ok["keep"]) == 5
    assert ok["keep"][0] == {"type": "MX", "name": "@",
                             "value": "eforward1.registrar-servers.com", "priority": 10}

    gone = edd.mail_state("lovecityc.com", [], [], before)
    assert gone["missing"] is True
    assert [r["value"] for r in gone["keep"]] == [h for _p, h in EFORWARD]   # what to put back
    assert gone["keep_spf"] == EFWD_SPF and gone["service"] == "Namecheap Email Forwarding"

    partly = edd.mail_state("lovecityc.com", EFORWARD[:3], [EFWD_SPF], before)
    assert partly["missing"] is False
    assert [r["host"] for r in partly["lost"]] == ["eforward4.registrar-servers.com",
                                                    "eforward5.registrar-servers.com"]

    moved = edd.mail_state("lovecityc.com", [(1, "aspmx.l.google.com")], [], before)
    assert moved["missing"] is False and moved["lost"] == []


def test_namecheap_note_with_forwarding_lists_what_to_keep():
    mail = edd.mail_state("lovecityc.com", EFORWARD, [EFWD_SPF], None)
    recs = edd.with_dmarc(RESEND_RECORDS, "lovecityc.com")
    note = edd.namecheap_note("namecheap", mail, recs)
    assert note["kind"] == "namecheap_custom_mx" and len(note["keep"]) == 5
    text = " ".join(note["steps"])
    assert "Custom MX" in text and "Namecheap Email Forwarding" in text
    assert "@lovecityc.com" in text and EFWD_SPF in text
    assert "change Mail Settings back to Email Forwarding" in text
    assert note["keep_spf"] == EFWD_SPF
    body = edd.note_as_text(note)
    assert "MX  @  eforward5.registrar-servers.com  priority 20" in body
    assert f"TXT @  {EFWD_SPF}" in body


def test_namecheap_note_without_mail_and_off_namecheap():
    recs = edd.with_dmarc(RESEND_RECORDS, "studiok.com")
    empty = edd.mail_state("studiok.com", [], [], None)
    note = edd.namecheap_note("namecheap", empty, recs)
    text = " ".join(note["steps"])
    assert "doesn't receive email today" in text and note["keep"] == []
    assert "Email Forwarding" not in text and note["keep_spf"] is None
    assert edd.namecheap_note("cloudflare", empty, recs) is None
    no_mx = [r for r in recs if r["type"] != "MX"]
    assert edd.namecheap_note("namecheap", empty, no_mx) is None


# ─── The lookup ──────────────────────────────────────────────────────


def _seams(monkeypatch, zone, mx, txt=None):
    async def _zone(d):
        return zone

    async def _txt(z):
        return txt or []
    monkeypatch.setattr(edd, "lookup_zone", _zone)
    monkeypatch.setattr(edd, "lookup_apex_mx", mx)
    monkeypatch.setattr(edd, "lookup_txt", _txt)


def test_check_mail_treats_a_failed_lookup_as_unknown(monkeypatch):
    async def _boom(z):
        raise RuntimeError("SERVFAIL")
    _seams(monkeypatch, "lovecityc.com", _boom)
    out = asyncio.run(edd.check_mail("lovecityc.com", edd.mail_snapshot(EFORWARD, [EFWD_SPF])))
    assert out["checked"] is False and out["missing"] is False and out["snapshot"] is None
    assert len(out["keep"]) == 5 and out["keep_spf"] == EFWD_SPF


def test_check_mail_reads_the_zone_apex_for_a_sending_subdomain(monkeypatch):
    asked = []

    async def _mx(z):
        asked.append(z)
        return [(1, "aspmx.l.google.com")]
    _seams(monkeypatch, "studiok.com", _mx)
    out = asyncio.run(edd.check_mail("mail.studiok.com", None))
    assert asked == ["studiok.com"] and out["zone"] == "studiok.com"
    assert out["checked"] is True
    assert out["snapshot"]["mx"] == [[1, "aspmx.l.google.com"]]


# ─── The router ──────────────────────────────────────────────────────


def test_dns_check_remembers_mail_and_warns_when_a_switch_deletes_it(fake, monkeypatch):
    fake.rows("businesses")[0]["settings"]["email_domain"]["domain"] = "lovecityc.com"
    mx = {"lovecityc.com": list(EFORWARD)}
    txt = {"lovecityc.com": [EFWD_SPF]}
    _stub_resolver(monkeypatch, txt=txt, mx=mx, ns=NAMECHEAP_NS)
    writes = []
    import sb_clients
    real_patch = sb_clients.sb_patch_as_service

    def _patch(p, b):
        writes.append(b)
        return real_patch(p, b)
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", _patch)

    out = asyncio.run(edr.dns_check("b1", _u("owner1")))
    assert out["provider"]["key"] == "namecheap"
    assert out["mail_note"]["kind"] == "namecheap_custom_mx"
    assert len(out["mail_note"]["keep"]) == 5 and out["mail"]["missing"] is False
    assert "snapshot" not in out["mail"]
    assert len(_cfg(fake)["mail_before"]["mx"]) == 5 and len(writes) == 1
    assert _cfg(fake)["resend_domain_id"] == "dom_1"           # the rest of the blob kept

    asyncio.run(edr.dns_check("b1", _u("owner1")))
    assert len(writes) == 1                                       # polled again: no write

    # Mail Settings switched to Custom MX; only our record was added.
    mx["lovecityc.com"] = []
    txt["lovecityc.com"] = []
    mx["send.lovecityc.com"] = [(10, "feedback-smtp.us-east-1.amazonses.com")]
    out = asyncio.run(edr.dns_check("b1", _u("owner1")))
    assert out["mail"]["missing"] is True
    assert [r["value"] for r in out["mail_note"]["keep"]] == [h for _p, h in EFORWARD]
    assert out["mail_note"]["keep_spf"] == EFWD_SPF
    assert len(writes) == 1 and len(_cfg(fake)["mail_before"]["mx"]) == 5   # old list kept


def test_dns_check_survives_a_failed_snapshot_write(fake, monkeypatch):
    _stub_resolver(monkeypatch, txt={}, mx={"studiok.com": [(1, "aspmx.l.google.com")]},
                   ns=["ada.ns.cloudflare.com"])
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", lambda p, b: None)
    out = asyncio.run(edr.dns_check("b1", _u("owner1")))
    assert out["ok"] and out["mail_note"] is None
    assert out["mail"]["service"] == "Google Workspace"
    assert "mail_before" not in _cfg(fake)


def test_share_records_carries_the_namecheap_steps(fake, monkeypatch):
    fake.rows("businesses")[0]["settings"]["email_domain"]["domain"] = "lovecityc.com"
    _stub_resolver(monkeypatch, txt={"lovecityc.com": [EFWD_SPF]},
                   mx={"lovecityc.com": list(EFORWARD)}, ns=NAMECHEAP_NS)
    calls = _recorded_send(monkeypatch, "msg_n")
    asyncio.run(edr.share_records("b1", edr.ShareRecordsBody(to_email="web@agency.com"),
                                  _u("owner1", "pastor@lovecityc.com")))
    body = calls[0]["body"]
    assert "ON NAMECHEAP, MX RECORDS LIVE UNDER MAIL SETTINGS" in body
    assert "Custom MX" in body and "eforward1.registrar-servers.com" in body


def test_share_records_off_namecheap_has_no_mail_settings_steps(fake, monkeypatch):
    _stub_resolver(monkeypatch, txt={}, mx={}, ns=["ada.ns.cloudflare.com"])
    calls = _recorded_send(monkeypatch, "msg_c")
    asyncio.run(edr.share_records("b1", edr.ShareRecordsBody(to_email="web@agency.com"),
                                  _u("owner1", "sarah@studiok.com")))
    assert "Mail Settings" not in calls[0]["body"]
