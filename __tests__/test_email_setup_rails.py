"""Email setup room, Phase 1 — the backend rails.

Covers:
  1. email_domain_dns: the DMARC row, host resolution, the pure
     comparison rules (TXT chunks/quotes/case, DMARC any-valid-policy,
     MX host+priority), provider detection, and check_records with a
     stubbed resolver.
  2. email_domains_router: dns-check shape, test-send pinned to the
     owner's own address and recording what it sent, test-status
     refusing a message id that isn't on record and mapping Resend's
     last_event, health counts, share-records validation + platform from.
  3. email_domain_monitor: drift flips to failed + notifies + drops the
     identity cache; a provider outage touches nothing; recovery
     restores verified; a healthy domain writes nothing.
"""
from __future__ import annotations

import asyncio
import pathlib
import sys

_here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))
sys.path.insert(0, str(_here))

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402

import email_domain_dns as edd  # noqa: E402
import email_domain_monitor as edm  # noqa: E402
import email_domains_router as edr  # noqa: E402
import email_sender  # noqa: E402
from test_i2_gl_sync import FakeSB  # noqa: E402


RESEND_RECORDS = [
    {"record": "SPF", "type": "TXT", "name": "send",
     "value": "v=spf1 include:amazonses.com ~all", "ttl": "Auto",
     "priority": None, "status": "pending"},
    {"record": "SPF", "type": "MX", "name": "send",
     "value": "feedback-smtp.us-east-1.amazonses.com", "ttl": "Auto",
     "priority": 10, "status": "pending"},
    {"record": "DKIM", "type": "TXT", "name": "resend._domainkey",
     "value": "p=MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQC7Xk", "ttl": "Auto",
     "priority": None, "status": "pending"},
]

PENDING_CFG = {
    "domain": "studiok.com", "from_local_part": "hello",
    "from_name": "Sarah from Studio K", "resend_domain_id": "dom_1",
    "status": "pending", "records": RESEND_RECORDS,
    "connected_at": "2026-09-01T00:00:00+00:00", "verified_at": None,
}
VERIFIED_CFG = {**PENDING_CFG, "status": "verified",
                "verified_at": "2026-09-01T01:00:00+00:00"}


def _u(uid, email=None):
    return type("U", (), {"id": uid, "email": email})()


# ─── 1. email_domain_dns ─────────────────────────────────────────────


def test_dmarc_row_is_added_once_and_flagged_optional():
    recs = edd.with_dmarc(RESEND_RECORDS, "studiok.com")
    assert len(recs) == 4
    dmarc = recs[-1]
    assert dmarc["record"] == "DMARC" and dmarc["optional"] is True
    assert dmarc["name"] == "_dmarc"
    assert dmarc["value"].startswith("v=DMARC1; p=none;")
    assert "rua=mailto:dmarc@studiok.com" in dmarc["value"]
    # idempotent
    assert len(edd.with_dmarc(recs, "studiok.com")) == 4


@pytest.mark.parametrize("name,expected", [
    ("send", "send.studiok.com"),
    ("resend._domainkey", "resend._domainkey.studiok.com"),
    ("@", "studiok.com"),
    ("", "studiok.com"),
    ("send.studiok.com", "send.studiok.com"),
    ("send.studiok.com.", "send.studiok.com"),
])
def test_fqdn_for(name, expected):
    assert edd.fqdn_for(name, "studiok.com") == expected


def test_compare_txt_tolerates_quotes_chunks_and_spf_case():
    exp = "v=spf1 include:amazonses.com ~all"
    assert edd.compare_txt(exp, ['"v=spf1 include:amazonses.com ~all"'], case_sensitive=False)["match"]
    assert edd.compare_txt(exp, ["V=SPF1 INCLUDE:amazonses.com ~ALL"], case_sensitive=False)["match"]
    assert edd.compare_txt(exp, ['"v=spf1 include:" "amazonses.com ~all"'], case_sensitive=False)["match"]
    out = edd.compare_txt(exp, ["v=spf1 include:_spf.google.com ~all"], case_sensitive=False)
    assert out == {"found": True, "match": False}
    assert edd.compare_txt(exp, [], case_sensitive=False) == {"found": False, "match": False}


def test_compare_txt_dkim_is_case_sensitive():
    key = "p=MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQC7Xk"
    assert edd.compare_txt(key, [key], case_sensitive=True)["match"]
    assert not edd.compare_txt(key, [key.lower()], case_sensitive=True)["match"]
    # a trimmed paste is the classic failure — found, not matching
    assert edd.compare_txt(key, [key[:-4]], case_sensitive=True) == {"found": True, "match": False}


def test_compare_dmarc_accepts_any_valid_policy():
    assert edd.compare_dmarc(["v=DMARC1; p=quarantine; rua=mailto:x@y.z"])["match"]
    assert edd.compare_dmarc(['"v=DMARC1; p=none;"'])["match"]
    assert edd.compare_dmarc(["v=spf1 -all"]) == {"found": True, "match": False}
    assert edd.compare_dmarc([]) == {"found": False, "match": False}


def test_compare_mx_needs_host_and_priority():
    host = "feedback-smtp.us-east-1.amazonses.com"
    assert edd.compare_mx(host, 10, [(10, host + ".")])["match"]
    assert edd.compare_mx(host, "10", [(10, host.upper())])["match"]
    assert not edd.compare_mx(host, 10, [(20, host)])["match"]
    assert edd.compare_mx(host, None, [(20, host)])["match"]  # no priority asked
    assert edd.compare_mx(host, 10, [(10, "mail.other.com")]) == {"found": True, "match": False}


def test_evaluate_record_reports_what_was_found():
    rec = RESEND_RECORDS[2]
    out = edd.evaluate_record(rec, ["p=MIGfMA0…tYpo"], [])
    assert out["found"] and not out["match"]
    assert out["found_values"] == ["p=MIGfMA0…tYpo"]
    mx = edd.evaluate_record(RESEND_RECORDS[1], [], [(10, "feedback-smtp.us-east-1.amazonses.com")])
    assert mx["match"] and mx["found_values"] == ["10 feedback-smtp.us-east-1.amazonses.com"]


@pytest.mark.parametrize("ns,key", [
    (["ada.ns.cloudflare.com", "bob.ns.cloudflare.com"], "cloudflare"),
    (["ns41.domaincontrol.com"], "godaddy"),
    (["dns1.registrar-servers.com"], "namecheap"),
    (["ns-cloud-a1.googledomains.com"], "squarespace"),
    (["ns-123.awsdns-45.org"], "route53"),
    (["ns1.some-unknown-host.example"], None),
    ([], None),
])
def test_detect_provider(ns, key):
    out = edd.detect_provider(ns)
    assert out["key"] == key
    assert out["guide_url"].startswith("https://")


def _stub_resolver(monkeypatch, txt, mx, ns):
    async def _txt(name):
        return txt.get(name, [])

    async def _mx(name):
        return mx.get(name, [])

    async def _ns(domain):
        return ns
    monkeypatch.setattr(edd, "lookup_txt", _txt)
    monkeypatch.setattr(edd, "lookup_mx", _mx)
    monkeypatch.setattr(edd, "lookup_ns", _ns)


def test_check_records_required_vs_optional(monkeypatch):
    _stub_resolver(
        monkeypatch,
        txt={"send.studiok.com": ["v=spf1 include:amazonses.com ~all"],
             "resend._domainkey.studiok.com": [RESEND_RECORDS[2]["value"]]},
        mx={"send.studiok.com": [(10, "feedback-smtp.us-east-1.amazonses.com")]},
        ns=["ada.ns.cloudflare.com"])
    recs = edd.with_dmarc(RESEND_RECORDS, "studiok.com")
    out = asyncio.run(edd.check_records("studiok.com", recs))
    assert out["required_ok"] is True      # SPF, MX, DKIM all present
    assert out["all_ok"] is False          # DMARC still missing
    assert out["provider"]["key"] == "cloudflare"
    by = {(r["record"], r["type"]): r for r in out["records"]}
    assert by[("DMARC", "TXT")]["dns"] == {"found": False, "match": False, "found_values": []}
    assert by[("DKIM", "TXT")]["fqdn"] == "resend._domainkey.studiok.com"
    assert by[("DKIM", "TXT")]["dns"]["match"]


def test_check_records_survives_a_lookup_exception(monkeypatch):
    async def _boom(name):
        raise RuntimeError("resolver down")
    monkeypatch.setattr(edd, "lookup_txt", _boom)
    monkeypatch.setattr(edd, "lookup_mx", _boom)

    async def _ns(domain):
        raise RuntimeError("resolver down")
    monkeypatch.setattr(edd, "lookup_ns", _ns)
    out = asyncio.run(edd.check_records("studiok.com", RESEND_RECORDS))
    assert out["required_ok"] is False
    assert all(r["dns"]["found"] is False for r in out["records"])
    assert out["provider"]["key"] is None


# ─── 2. Router ───────────────────────────────────────────────────────


@pytest.fixture
def fake(monkeypatch):
    fb = FakeSB()
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_get_as_service", fb.get)
    monkeypatch.setattr(sb_clients, "sb_post_as_service",
                        lambda p, b, prefer="rep": fb.post(p, b, prefer))
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", fb.patch)
    monkeypatch.setattr(sb_clients, "sb_delete_as_service", fb.delete)
    fb.rows("businesses").append(
        {"id": "b1", "owner_id": "owner1", "name": "Studio K",
         "settings": {"email_domain": dict(PENDING_CFG)}})
    monkeypatch.setenv("RESEND_API_KEY", "re_test")
    return fb


def _cfg(fb):
    return fb.rows("businesses")[0]["settings"]["email_domain"]


def _recorded_send(monkeypatch, message_id="msg_1"):
    calls = []

    async def _send(**kw):
        calls.append(kw)
        return {"id": message_id}
    monkeypatch.setattr(email_sender, "send_via_resend", _send)
    return calls


def test_dns_check_owner_only_and_shape(fake, monkeypatch):
    _stub_resolver(monkeypatch, txt={}, mx={}, ns=["ns41.domaincontrol.com"])
    with pytest.raises(HTTPException) as e:
        asyncio.run(edr.dns_check("b1", _u("stranger")))
    assert e.value.status_code == 403
    out = asyncio.run(edr.dns_check("b1", _u("owner1")))
    assert out["ok"] and out["domain"] == "studiok.com"
    assert out["provider"]["name"] == "GoDaddy"
    assert [r["record"] for r in out["records"]] == ["SPF", "SPF", "DKIM", "DMARC"]
    assert out["required_ok"] is False and "checked_at" in out


def test_dns_check_needs_a_connected_domain(fake):
    fake.rows("businesses")[0]["settings"] = {}
    with pytest.raises(HTTPException) as e:
        asyncio.run(edr.dns_check("b1", _u("owner1")))
    assert e.value.status_code == 409


def test_test_send_is_pinned_to_the_owner(fake, monkeypatch):
    calls = _recorded_send(monkeypatch)
    # someone else's address → refused, nothing sent
    with pytest.raises(HTTPException) as e:
        asyncio.run(edr.test_send("b1", edr.TestSendBody(to_email="victim@example.com"),
                                  _u("owner1", "sarah@studiok.com")))
    assert e.value.status_code == 400 and calls == []
    # no sign-in email known → refused
    with pytest.raises(HTTPException):
        asyncio.run(edr.test_send("b1", edr.TestSendBody(), _u("owner1", None)))
    assert calls == []


def test_test_send_platform_identity_while_pending(fake, monkeypatch):
    calls = _recorded_send(monkeypatch, "msg_p")
    out = asyncio.run(edr.test_send("b1", edr.TestSendBody(), _u("owner1", "Sarah@StudioK.com")))
    assert out["ok"] and out["id"] == "msg_p"
    assert out["identity"] == "platform"
    assert out["to"] == "sarah@studiok.com"
    sent = calls[0]
    assert sent["to_email"] == "sarah@studiok.com"
    assert sent["business_id"] == "b1"
    assert sent["from_email"] == email_sender.DEFAULT_FROM_EMAIL
    assert "isn't verified yet" in sent["body"]
    assert _cfg(fake)["last_test"]["id"] == "msg_p"


def test_test_send_custom_identity_when_verified(fake, monkeypatch):
    fake.rows("businesses")[0]["settings"]["email_domain"] = dict(VERIFIED_CFG)
    calls = _recorded_send(monkeypatch, "msg_v")
    out = asyncio.run(edr.test_send("b1", edr.TestSendBody(), _u("owner1", "sarah@studiok.com")))
    assert out["identity"] == "custom" and out["from_email"] == "hello@studiok.com"
    assert calls[0]["from_name"] == "Sarah from Studio K"
    assert "sending from hello@studiok.com" in calls[0]["body"]


def test_test_status_refuses_unknown_message_and_maps_events(fake, monkeypatch):
    fake.rows("businesses")[0]["settings"]["email_domain"] = {
        **PENDING_CFG, "last_test": {"id": "msg_1", "to": "sarah@studiok.com",
                                     "from_email": "hello@studiok.com",
                                     "identity": "custom", "sent_at": "2026-09-02T10:00:00+00:00"}}
    seen = {}

    async def _resend(method, path, json_body=None):
        seen["path"] = path
        return {"id": "msg_1", "last_event": seen.get("event")}
    monkeypatch.setattr(edr, "_resend", _resend)

    with pytest.raises(HTTPException) as e:
        asyncio.run(edr.test_status("b1", "msg_other", _u("owner1")))
    assert e.value.status_code == 404 and "path" not in seen  # never asked Resend

    seen["event"] = "delivered"
    out = asyncio.run(edr.test_status("b1", "msg_1", _u("owner1")))
    assert seen["path"].endswith("/emails/msg_1")
    assert out["accepted"] and out["delivered"] and not out["opened"] and not out["failed"]
    assert out["identity"] == "custom"

    seen["event"] = "opened"
    assert asyncio.run(edr.test_status("b1", "msg_1", _u("owner1")))["opened"]

    seen["event"] = "bounced"
    out = asyncio.run(edr.test_status("b1", "msg_1", _u("owner1")))
    assert out["failed"] and out["failure"] == "bounced" and not out["delivered"]

    seen["event"] = None  # older API shape: sent, no event yet
    out = asyncio.run(edr.test_status("b1", "msg_1", _u("owner1")))
    assert out["accepted"] and not out["delivered"]


def test_health_counts_last_30_days(fake, monkeypatch):
    fake.rows("businesses")[0]["settings"]["email_domain"] = dict(VERIFIED_CFG)
    ev = fake.rows("events")
    ev += [
        {"business_id": "b1", "event_type": "email_sent", "created_at": "2099-01-01T00:00:00+00:00"},
        {"business_id": "b1", "event_type": "agent_message_sent", "created_at": "2099-01-01T00:00:00+00:00"},
        {"business_id": "b1", "event_type": "email_sent", "created_at": "2000-01-01T00:00:00+00:00"},  # old
        {"business_id": "b2", "event_type": "email_sent", "created_at": "2099-01-01T00:00:00+00:00"},  # other biz
        {"business_id": "b1", "event_type": "invoice_viewed", "created_at": "2099-01-01T00:00:00+00:00"},
    ]
    fake.rows("contacts").extend([
        {"business_id": "b1", "email": "a@x.com"}, {"business_id": "b1", "email": "b@x.com"},
        {"business_id": "b2", "email": "c@x.com"}])
    fake.rows("email_suppressions").extend([{"email": "b@x.com"}, {"email": "c@x.com"}])

    async def _resend(method, path, json_body=None):
        return {"id": "dom_1", "status": "verified", "records": RESEND_RECORDS}
    monkeypatch.setattr(edr, "_resend", _resend)

    out = asyncio.run(edr.domain_health("b1", _u("owner1")))
    assert out["connected"] and out["live_status"] == "verified"
    assert out["stats"]["sent"] == 2
    assert out["stats"]["opened"] == 1
    assert out["stats"]["suppressed_contacts"] == 1
    assert out["stats"]["opened_is_floor"] is True
    assert [r["record"] for r in out["records"]][-1] == "DMARC"


def test_health_when_nothing_connected(fake):
    fake.rows("businesses")[0]["settings"] = {}
    out = asyncio.run(edr.domain_health("b1", _u("owner1")))
    assert out == {"ok": True, "connected": False,
                   "from_email": email_sender.DEFAULT_FROM_EMAIL,
                   "stats": {"window_days": 30, "sent": 0, "opened": 0,
                             "suppressed_contacts": 0, "opened_is_floor": True}}


def test_share_records_validates_and_sends_from_platform(fake, monkeypatch):
    calls = _recorded_send(monkeypatch, "msg_s")
    with pytest.raises(HTTPException) as e:
        asyncio.run(edr.share_records("b1", edr.ShareRecordsBody(to_email="not-an-email"),
                                      _u("owner1", "sarah@studiok.com")))
    assert e.value.status_code == 400 and calls == []

    out = asyncio.run(edr.share_records(
        "b1", edr.ShareRecordsBody(to_email="Dev@Agency.com", note="Cloudflare login is in 1Password"),
        _u("owner1", "sarah@studiok.com")))
    assert out == {"ok": True, "to": "dev@agency.com", "id": "msg_s"}
    sent = calls[0]
    assert sent["from_email"] == email_sender.DEFAULT_FROM_EMAIL   # never the unverified domain
    assert sent["reply_to"] == "sarah@studiok.com"
    assert "business_id" not in sent                                # no identity override
    body = sent["body"]
    assert "resend._domainkey.studiok.com" in body
    assert "_dmarc" in body and "(recommended, optional)" in body
    assert "Priority: 10" in body
    assert "Cloudflare login is in 1Password" in body


# ─── 3. Monitor ──────────────────────────────────────────────────────


@pytest.fixture
def watched(fake, monkeypatch):
    """A verified business under watch, with the network seams stubbed."""
    fake.rows("businesses")[0]["settings"]["email_domain"] = dict(VERIFIED_CFG)
    notes = []

    async def _notify(biz, **kw):
        notes.append(kw)
        return {"in_app": True, "push": False, "email": False}
    monkeypatch.setattr(edm, "_notify", _notify)
    monkeypatch.setattr(edm, "_watched_businesses", lambda: [dict(fake.rows("businesses")[0])])
    email_sender._IDENTITY_CACHE["id:b1"] = ("hello@studiok.com", "Sarah")
    return notes


def _live(monkeypatch, payload):
    async def _resend_domain(domain_id):
        return payload
    monkeypatch.setattr(edm, "_resend_domain", _resend_domain)


def test_monitor_flags_drift_and_tells_the_owner(fake, watched, monkeypatch):
    _live(monkeypatch, {"id": "dom_1", "status": "failed"})
    out = asyncio.run(edm.monitor_tick())
    assert out == {"checked": 1, "drift": 1, "recovered": 0, "errors": 0}
    cfg = _cfg(fake)
    assert cfg["status"] == "failed"
    assert cfg["drift_detected_at"] and cfg["drift_reason"] == "failed"
    assert "id:b1" not in email_sender._IDENTITY_CACHE       # next send is safe
    assert watched[0]["kind"] == "drift"
    assert "studiok.com" in watched[0]["title"]


def test_monitor_treats_missing_domain_as_drift(fake, watched, monkeypatch):
    _live(monkeypatch, {"__missing__": True})
    asyncio.run(edm.monitor_tick())
    assert _cfg(fake)["status"] == "failed" and _cfg(fake)["drift_reason"] == "missing"


def test_monitor_leaves_a_healthy_domain_alone(fake, watched, monkeypatch):
    _live(monkeypatch, {"id": "dom_1", "status": "verified"})
    before = dict(_cfg(fake))
    out = asyncio.run(edm.monitor_tick())
    assert out["drift"] == 0 and out["recovered"] == 0
    assert _cfg(fake) == before                              # no write at all
    assert watched == []
    assert "id:b1" in email_sender._IDENTITY_CACHE           # cache untouched


def test_monitor_provider_outage_is_not_drift(fake, watched, monkeypatch):
    _live(monkeypatch, None)
    before = dict(_cfg(fake))
    asyncio.run(edm.monitor_tick())
    assert _cfg(fake) == before and watched == []


def test_monitor_recovers_a_drifted_domain(fake, watched, monkeypatch):
    fake.rows("businesses")[0]["settings"]["email_domain"] = {
        **VERIFIED_CFG, "status": "failed",
        "drift_detected_at": "2026-09-02T09:00:00+00:00", "drift_reason": "failed"}
    _live(monkeypatch, {"id": "dom_1", "status": "verified"})
    out = asyncio.run(edm.monitor_tick())
    assert out["recovered"] == 1
    cfg = _cfg(fake)
    assert cfg["status"] == "verified"
    assert "drift_detected_at" not in cfg and "drift_reason" not in cfg
    assert cfg["verified_at"] == VERIFIED_CFG["verified_at"]   # original kept
    assert watched[0]["kind"] == "recovered"


def test_monitor_ignores_an_operator_marked_failure(fake, watched, monkeypatch):
    # failed by the operator's own verify call, never by us → not ours to poll
    fake.rows("businesses")[0]["settings"]["email_domain"] = {**VERIFIED_CFG, "status": "failed"}
    _live(monkeypatch, {"id": "dom_1", "status": "verified"})
    asyncio.run(edm.monitor_tick())
    assert _cfg(fake)["status"] == "failed" and watched == []


def test_monitor_one_bad_row_does_not_stop_the_rest(fake, watched, monkeypatch):
    other = {"id": "b2", "owner_id": "o2", "name": "Other",
             "settings": {"email_domain": {**VERIFIED_CFG, "resend_domain_id": "dom_2"}}}
    fake.rows("businesses").append(other)
    monkeypatch.setattr(edm, "_watched_businesses",
                        lambda: [dict(fake.rows("businesses")[0]), dict(other)])

    async def _resend_domain(domain_id):
        if domain_id == "dom_1":
            raise RuntimeError("boom")
        return {"id": "dom_2", "status": "failed"}
    monkeypatch.setattr(edm, "_resend_domain", _resend_domain)
    out = asyncio.run(edm.monitor_tick())
    assert out["errors"] == 1 and out["drift"] == 1
    assert fake.rows("businesses")[1]["settings"]["email_domain"]["status"] == "failed"
