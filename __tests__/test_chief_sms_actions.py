"""Chief's texting verbs — setup, and the guess it used to make.

The contract these tests defend:
  • "text Marcus" with two Marcuses ASKS. A text is class C: it leaves
    immediately, there is no outbox and no recall, so taking rows[0] of a
    two-row match put one client's words in front of another with no way
    back for anyone,
  • a failure says the thing the practitioner can act on — "opted out" is
    a fact, not a fault, and the unconfigured-provider message names env
    vars and a host and is not theirs to read,
  • the keyword is validated against sms_routing's OWN rules, and a word
    another business holds is refused rather than silently altered,
  • set_sms_alerts is the only writer of businesses.settings.sms_alerts —
    a key sms_alerts has always read and nothing has ever written,
  • the verbs are registered, classified, and named in Chief's prompt.
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import asyncio

import pytest

import chief_of_staff as cos
import chief_sms_actions as csa
import sb_clients

BIZ = {"id": "biz1", "name": "Test Co", "owner_id": "u1", "settings": {}}


def _run(coro):
    return asyncio.run(coro)


# ─── send_sms: the guess ──────────────────────────────────────────────

def _patch_contacts(monkeypatch, rows, sent=None):
    async def _sb(client, method, path, body=None):
        if method == "GET" and path.startswith("/contacts"):
            return rows
        return []

    async def _core(client, *, business_id, to, message, contact_id=None, sent_by=None):
        (sent if sent is not None else []).append((to, message))
        return {"id": "m1", "telnyx_id": "SM1"}

    monkeypatch.setattr(cos, "_sb", _sb)
    import sms_service
    monkeypatch.setattr(sms_service, "send_sms_core", _core)


def test_two_matching_contacts_asks_instead_of_texting_one(monkeypatch):
    sent = []
    _patch_contacts(monkeypatch, [
        {"id": "c1", "name": "Marcus Webb", "phone": "+15551110000"},
        {"id": "c2", "name": "Marcus Thompson", "phone": "+15552220000"},
    ], sent)
    res = _run(cos.handle_send_sms(None, BIZ, {
        "contact_name": "Marcus", "message": "See you at 2"}))
    assert res["failed"] is True
    assert "Marcus Webb" in res["result"] and "Marcus Thompson" in res["result"]
    assert not sent, "a class-C send must not happen on an ambiguous name"


def test_one_match_still_sends(monkeypatch):
    sent = []
    _patch_contacts(monkeypatch, [
        {"id": "c1", "name": "Marcus Webb", "phone": "+15551110000"}], sent)
    res = _run(cos.handle_send_sms(None, BIZ, {
        "contact_name": "Marcus", "message": "See you at 2"}))
    assert res.get("failed") is not True
    assert res["result"] == "sent"
    assert sent == [("+15551110000", "See you at 2")]


def test_no_such_contact_says_so(monkeypatch):
    """Not "no phone number on file" — that sends the practitioner
    looking for a number on a record that does not exist."""
    _patch_contacts(monkeypatch, [])
    res = _run(cos.handle_send_sms(None, BIZ, {
        "contact_name": "Nobody", "message": "hi"}))
    assert res["failed"] is True
    assert "don't have a contact" in res["result"]
    assert "phone number on file" not in res["result"]


def test_a_known_contact_without_a_phone_still_says_that(monkeypatch):
    _patch_contacts(monkeypatch, [{"id": "c1", "name": "Marcus", "phone": None}])
    res = _run(cos.handle_send_sms(None, BIZ, {
        "contact_name": "Marcus", "message": "hi"}))
    assert res["failed"] is True
    assert "no phone number on file" in res["result"]


def test_a_raw_number_skips_contact_resolution(monkeypatch):
    sent = []
    _patch_contacts(monkeypatch, [], sent)
    res = _run(cos.handle_send_sms(None, BIZ, {
        "to": "+15559998888", "message": "hi"}))
    assert res.get("failed") is not True
    assert sent == [("+15559998888", "hi")]


# ─── send_sms: what a failure says ────────────────────────────────────

def _patch_raising(monkeypatch, exc):
    async def _sb(client, method, path, body=None):
        if method == "GET" and path.startswith("/contacts"):
            return [{"id": "c1", "name": "Marcus", "phone": "+15551110000"}]
        return []

    async def _core(client, **kw):
        raise exc

    monkeypatch.setattr(cos, "_sb", _sb)
    import sms_service
    monkeypatch.setattr(sms_service, "send_sms_core", _core)


def test_an_opt_out_is_reported_as_the_fact_it_is(monkeypatch):
    import sms_service
    _patch_raising(monkeypatch, sms_service.SmsSendError(
        "+15551110000 has opted out of texts (STOP). "
        "They can text START to opt back in.", 422))
    res = _run(cos.handle_send_sms(None, BIZ, {
        "contact_name": "Marcus", "message": "hi"}))
    assert res["failed"] is True
    assert "opted out" in res["result"]
    assert "sms error" not in res["result"].lower(), (
        "dressing an actionable fact as a fault invites a retry that will "
        "fail identically forever")


def test_the_provider_config_message_never_reaches_a_practitioner(monkeypatch):
    import sms_service
    _patch_raising(monkeypatch, sms_service.SmsSendError(
        "SMS is not configured. Set the TWILIO_* vars in Railway.", 503))
    res = _run(cos.handle_send_sms(None, BIZ, {
        "contact_name": "Marcus", "message": "hi"}))
    assert res["failed"] is True
    for leak in ("TWILIO", "Railway", "vars"):
        assert leak not in res["result"], f"{leak} leaked to the practitioner"
    assert "nothing was sent" in res["result"]


def test_an_unexpected_failure_is_generic(monkeypatch):
    _patch_raising(monkeypatch, RuntimeError(
        "postgrest 500: relation sms_messages does not exist"))
    res = _run(cos.handle_send_sms(None, BIZ, {
        "contact_name": "Marcus", "message": "hi"}))
    assert res["failed"] is True
    assert "postgrest" not in res["result"] and "500" not in res["result"]


# ─── the keyword ──────────────────────────────────────────────────────

def _patch_kw(monkeypatch, *, current=None, owner_of=None):
    writes = {"posts": [], "patches": []}

    def _get(path):
        if path.startswith("/sms_keywords?business_id="):
            return [{"keyword": current}] if current else []
        if path.startswith("/sms_keywords?keyword="):
            word = path.split("keyword=eq.")[1].split("&")[0]
            biz = (owner_of or {}).get(word)
            return [{"business_id": biz}] if biz else []
        return []

    monkeypatch.setattr(sb_clients, "sb_get_as_service", _get)
    monkeypatch.setattr(sb_clients, "sb_post_as_service",
                        lambda p, b, prefer="return=representation":
                        writes["posts"].append((p, b)) or [b])
    monkeypatch.setattr(sb_clients, "sb_patch_as_service",
                        lambda p, b: writes["patches"].append((p, b)) or [b])
    return writes


def test_claiming_a_first_keyword_inserts_and_explains_why_it_matters(monkeypatch):
    w = _patch_kw(monkeypatch)
    res = _run(csa.handle_set_sms_keyword(None, BIZ, {"keyword": "bloom"}))
    assert res.get("failed") is not True
    assert w["posts"] and w["posts"][0][1]["keyword"] == "BLOOM"
    assert not w["patches"]
    assert "BLOOM" in res["result"]


def test_changing_a_keyword_names_the_old_one(monkeypatch):
    """Anything printed with the old word stops working for new clients,
    and that is not obvious from "done"."""
    w = _patch_kw(monkeypatch, current="OLDWORD")
    res = _run(csa.handle_set_sms_keyword(None, BIZ, {"keyword": "BLOOM"}))
    assert w["patches"] and not w["posts"]
    assert "OLDWORD" in res["result"] and "BLOOM" in res["result"]
    assert res["previous_keyword"] == "OLDWORD"


def test_a_keyword_another_business_holds_is_refused(monkeypatch):
    w = _patch_kw(monkeypatch, owner_of={"BLOOM": "someone-else"})
    res = _run(csa.handle_set_sms_keyword(None, BIZ, {"keyword": "BLOOM"}))
    assert res["failed"] is True
    assert "already taken" in res["result"]
    assert not w["posts"] and not w["patches"]


def test_re_claiming_your_own_keyword_is_a_no_op(monkeypatch):
    w = _patch_kw(monkeypatch, current="BLOOM", owner_of={"BLOOM": "biz1"})
    res = _run(csa.handle_set_sms_keyword(None, BIZ, {"keyword": "BLOOM"}))
    assert res.get("failed") is not True
    assert not w["posts"] and not w["patches"]


@pytest.mark.parametrize("bad", ["AB", "A B", "TOOLONGKEYWORDBEYONDLIMIT!", "hi!"])
def test_an_illegal_keyword_is_refused_by_the_routing_modules_own_rule(monkeypatch, bad):
    w = _patch_kw(monkeypatch)
    res = _run(csa.handle_set_sms_keyword(None, BIZ, {"keyword": bad}))
    assert res["failed"] is True
    assert not w["posts"] and not w["patches"]


def test_a_carrier_reserved_word_is_refused(monkeypatch):
    import sms_routing
    reserved = sorted(w for w in sms_routing.RESERVED_WORDS
                      if sms_routing.KEYWORD_RE.match(w))
    assert reserved, "no reserved word is even keyword-shaped — check the fixture"
    w = _patch_kw(monkeypatch)
    res = _run(csa.handle_set_sms_keyword(None, BIZ, {"keyword": reserved[0]}))
    assert res["failed"] is True
    assert "reserved" in res["result"]
    assert not w["posts"] and not w["patches"]


# ─── the alert switch ─────────────────────────────────────────────────

def _patch_settings(monkeypatch):
    writes = []
    monkeypatch.setattr(sb_clients, "sb_patch_as_service",
                        lambda p, b: writes.append((p, b)) or [b])
    return writes


def test_turning_reminders_off_writes_the_key_sms_alerts_reads(monkeypatch):
    """settings.sms_alerts has been read by sms_alerts._alert_setting
    since it shipped and written by NOTHING — so both alerts defaulted on
    for every business with no way to say otherwise."""
    writes = _patch_settings(monkeypatch)
    biz = dict(BIZ, settings={})
    res = _run(csa.handle_set_sms_alerts(None, biz, {"reminders": False}))
    assert res.get("failed") is not True
    _, body = writes[0]
    assert body["settings"]["sms_alerts"]["reminders"] is False
    assert "reminders off" in res["result"]
    assert biz["settings"]["sms_alerts"]["reminders"] is False, (
        "same-turn reads must see it")


def test_the_default_is_read_as_on_when_reporting_what_changed(monkeypatch):
    """Absent means ON — sms_alerts._alert_setting's own default. The
    'was' half of the message has to be true, not assumed."""
    _patch_settings(monkeypatch)
    res = _run(csa.handle_set_sms_alerts(None, dict(BIZ, settings={}),
                                         {"reminders": True}))
    assert "Already set that way" in res["result"]


def test_stop_texting_my_clients_switches_both(monkeypatch):
    writes = _patch_settings(monkeypatch)
    res = _run(csa.handle_set_sms_alerts(None, dict(BIZ, settings={}),
                                         {"on": False}))
    alerts = writes[0][1]["settings"]["sms_alerts"]
    assert alerts == {"confirmations": False, "reminders": False}
    assert "anything you send yourself is unaffected" in res["result"]


def test_switching_one_leg_leaves_the_other_alone(monkeypatch):
    writes = _patch_settings(monkeypatch)
    biz = dict(BIZ, settings={"sms_alerts": {"confirmations": False}})
    _run(csa.handle_set_sms_alerts(None, biz, {"reminders": False}))
    alerts = writes[0][1]["settings"]["sms_alerts"]
    assert alerts == {"confirmations": False, "reminders": False}


def test_an_unreadable_switch_asks_rather_than_guessing(monkeypatch):
    writes = _patch_settings(monkeypatch)
    res = _run(csa.handle_set_sms_alerts(None, dict(BIZ), {}))
    assert res["failed"] is True
    assert not writes


def test_an_unknown_alert_name_is_refused(monkeypatch):
    writes = _patch_settings(monkeypatch)
    res = _run(csa.handle_set_sms_alerts(
        None, dict(BIZ), {"on": False, "kinds": ["marketing"]}))
    assert res["failed"] is True
    assert not writes, "a typo must not write a key nothing reads"


# ─── status ───────────────────────────────────────────────────────────

def test_status_leads_with_the_missing_keyword(monkeypatch):
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda p: [])
    import sms_service
    monkeypatch.setattr(sms_service, "_twilio_configured", lambda: True)
    res = _run(csa.handle_sms_status(None, dict(BIZ), {}))
    assert "no keyword yet" in res["result"]
    assert res["signal"]["has_keyword"] == 0
    assert res["signal"]["ready"] == 0
    assert res["label"].endswith("needs setup")


def test_status_reports_ready_when_it_is(monkeypatch):
    def _get(path):
        if path.startswith("/sms_keywords"):
            return [{"keyword": "BLOOM"}]
        return []

    monkeypatch.setattr(sb_clients, "sb_get_as_service", _get)
    import sms_service
    monkeypatch.setattr(sms_service, "_twilio_configured", lambda: True)
    res = _run(csa.handle_sms_status(None, dict(BIZ), {}))
    assert "keyword BLOOM" in res["result"]
    assert res["signal"]["ready"] == 1
    assert res.get("failed") is not True


def test_status_writes_nothing(monkeypatch):
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda p: [])
    for writer in ("sb_post_as_service", "sb_patch_as_service",
                   "sb_delete_as_service"):
        monkeypatch.setattr(sb_clients, writer, lambda *a, **k: (_ for _ in ()).throw(
            AssertionError(f"sms_status called {writer}")))
    import sms_service
    monkeypatch.setattr(sms_service, "_twilio_configured", lambda: False)
    _run(csa.handle_sms_status(None, dict(BIZ), {}))


# ─── the shape every action card depends on ───────────────────────────

def test_every_return_path_carries_result_and_label(monkeypatch):
    _patch_kw(monkeypatch)
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", lambda p, b: [b])
    import sms_service
    monkeypatch.setattr(sms_service, "_twilio_configured", lambda: True)
    for coro in (
        csa.handle_set_sms_keyword(None, dict(BIZ), {"keyword": "BLOOM"}),
        csa.handle_set_sms_keyword(None, dict(BIZ), {}),            # fails
        csa.handle_set_sms_alerts(None, dict(BIZ), {"on": False}),
        csa.handle_set_sms_alerts(None, dict(BIZ), {}),             # fails
        csa.handle_sms_status(None, dict(BIZ), {}),
    ):
        res = _run(coro)
        assert isinstance(res.get("result"), str) and res["result"]
        assert isinstance(res.get("label"), str) and res["label"]
        assert "type" in res


# ─── registration: a handler is not a capability ──────────────────────

VERBS = ("set_sms_keyword", "set_sms_alerts", "sms_status",
         "provision_sms_number", "release_sms_number", "restore_sms_number")


@pytest.mark.parametrize("verb", VERBS)
def test_verb_is_registered_classified_and_in_the_prompt(verb):
    import action_registry as reg

    class _EmptyCtx(dict):
        def __missing__(self, key):
            return []

    assert verb in cos.ACTION_HANDLERS
    assert verb in reg.known_verbs()
    prompt = cos._build_system_prompt(
        _EmptyCtx(business={"id": "b1", "name": "T", "type": "coach",
                            "settings": {}, "voice_profile": {}}), False)
    assert verb in prompt, (
        f"{verb} exists but Chief is never told about it")


def test_no_broadcast_verb_exists():
    """Deliberate. /sms/broadcast gates on opt-out only and never calls
    has_sms_consent, while campaigns_router runs the same bulk traffic
    through the consent check and quiet hours. A verb is what the model
    reaches for, so wrapping the weaker path would make it the default."""
    assert "broadcast_sms" not in cos.ACTION_HANDLERS
    assert "send_broadcast" not in cos.ACTION_HANDLERS
