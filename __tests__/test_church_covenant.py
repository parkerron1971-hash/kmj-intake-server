"""The admin covenant: who owes what, and the page they sign.

Kevin, 2026-11-06: "align the covenant so when they open the app it would pop
up. i want to use e-signature." What matters, in order:

  1. Nothing pops up until the owner sends it, and only the owner can.
  2. Each signer sees it only on their turn: Admin, then Executive Pastor, then
     the Senior Pastor. DocuSeal lists its submitters in no useful order.
  3. Sending twice asks nobody twice.
  4. A login sees its own covenant, never another admin's.
  5. A business, a switched-off church, or a failed read shows nothing, because
     this never stands between someone and their app.
  6. Nobody is emailed by DocuSeal, and a name can't break the page.
"""
from __future__ import annotations

import asyncio
import pathlib
import sys
from types import SimpleNamespace

_here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402

import church_covenant as cc  # noqa: E402
import church_covenant_text as text  # noqa: E402

BIZ = "11111111-1111-1111-1111-111111111111"
OWNER, EXEC, NAIYA, TIARA = "owner", "exec", "naiya", "tiara"
ADMINS = [
    {"user_id": NAIYA, "email": "naiya@x.org", "name": "Naiya Clark", "lane": "office_leadership", "lane_label": "Office & Leadership"},
    {"user_id": TIARA, "email": "tiara@x.org", "name": "Tiara Adams", "lane": "people_care", "lane_label": "People & Care"},
]
PASTOR = {"user_id": EXEC, "email": "jess@x.org", "name": "Jessica McCloud"}


def _user(uid):
    return SimpleNamespace(id=uid, email=f"{uid}@x.org")


def _row(uid, status="sent", doc="100"):
    return {"id": f"r{uid}", "document_id": doc, "title": f"Covenant: {uid}", "signer_name": uid, "signer_email": "x",
            "status": status, "source_ref": cc.source_ref(uid)}


def _sub(*done):
    """The order DocuSeal really returned them in the live test."""
    return {"submitters": [{"role": r, "slug": f"s-{r[:3]}", "status": "completed" if r in done else "awaiting"}
                           for r in (text.SENIOR, text.ADMIN, text.EXEC)]}


@pytest.fixture
def env(monkeypatch):
    state = {"type": "church", "rows": [], "on": True, "sub": _sub(), "posted": [], "created": [],
             "roles": {NAIYA: "manager", TIARA: "manager", EXEC: "manager"}}
    import business_users_router as bur
    monkeypatch.setattr(cc, "_business", lambda biz: {"id": BIZ, "name": "Love City", "type": state["type"],
                                                      "owner_id": OWNER, "settings": {"practitioner_name": "Kevin"}})
    monkeypatch.setattr(cc, "switched_on", lambda b: state["on"])
    monkeypatch.setattr(cc, "people", lambda b: {"admins": ADMINS, "exec": PASTOR})
    monkeypatch.setattr(cc, "_sent", lambda b: state["rows"])
    monkeypatch.setattr(bur, "role_of", lambda b, u: state["roles"].get(u))

    async def _submission(doc):
        return state["sub"]

    monkeypatch.setattr(cc, "_submission", _submission)

    async def _create(church, biz, admin, pastor, senior):
        state["created"].append(admin["name"])
        return {"name": admin["name"], "ok": True, "hash": "h"}

    monkeypatch.setattr(cc, "_create", _create)
    import docuseal_router as dr

    async def _owner_email(o):
        return "kevin@x.org"

    monkeypatch.setattr(dr, "_owner_email", _owner_email)
    import audit_log
    monkeypatch.setattr(audit_log, "record", lambda *a, **k: None)
    return state


def mine(uid):
    return asyncio.run(cc.mine(BIZ, _user(uid)))


def send(uid):
    return asyncio.run(cc.send(cc.SendBody(business_id=BIZ), _user(uid)))


# ─── 1. nothing until the owner sends it ────────────────────────────

def test_before_it_is_sent_an_admin_sees_nothing_and_the_owner_is_asked(env):
    assert mine(NAIYA)["sign"] == [] and mine(NAIYA)["send"] == []
    assert [a["name"] for a in mine(OWNER)["send"]] == ["Naiya Clark", "Tiara Adams"]


def test_only_the_owner_can_send(env):
    with pytest.raises(HTTPException) as e:
        send(NAIYA)
    assert e.value.status_code == 403 and env["created"] == []


# ─── 2. each on their turn ──────────────────────────────────────────

def test_the_admin_signs_first(env):
    env["rows"] = [_row(NAIYA)]
    item = mine(NAIYA)["sign"]
    assert len(item) == 1 and item[0]["url"].endswith("s-Adm") and item[0]["yours"] is True
    assert mine(EXEC)["sign"] == [] and mine(OWNER)["sign"] == []


def test_then_the_executive_pastor(env):
    env["rows"] = [_row(NAIYA)]
    env["sub"] = _sub(text.ADMIN)
    assert mine(NAIYA)["sign"] == []
    item = mine(EXEC)["sign"]
    assert item[0]["url"].endswith("s-Exe") and item[0]["name"] == NAIYA and item[0]["yours"] is False
    assert mine(OWNER)["sign"] == []


def test_then_the_senior_pastor(env):
    env["rows"] = [_row(NAIYA)]
    env["sub"] = _sub(text.ADMIN, text.EXEC)
    assert mine(EXEC)["sign"] == []
    assert mine(OWNER)["sign"][0]["url"].endswith("s-Sen")


def test_a_finished_covenant_shows_nobody_anything(env):
    env["rows"] = [_row(NAIYA, status="completed")]
    assert mine(NAIYA)["sign"] == [] and mine(EXEC)["sign"] == [] and mine(OWNER)["sign"] == []


def test_the_turn_ignores_the_order_docuseal_lists_them_in():
    assert cc.turn_of(_sub())["role"] == text.ADMIN
    assert cc.turn_of(_sub(text.ADMIN, text.EXEC, text.SENIOR)) is None


# ─── 3. sending twice ───────────────────────────────────────────────

def test_sending_asks_each_admin_once(env):
    out = send(OWNER)
    assert out["sent"] == ["Naiya Clark", "Tiara Adams"] and env["created"] == ["Naiya Clark", "Tiara Adams"]
    env["rows"] = [_row(NAIYA), _row(TIARA)]
    env["created"].clear()
    assert send(OWNER)["sent"] == [] and env["created"] == []
    assert mine(OWNER)["send"] == []


def test_an_admin_who_joins_later_is_the_only_one_asked(env):
    env["rows"] = [_row(NAIYA)]
    send(OWNER)
    assert env["created"] == ["Tiara Adams"]


# ─── 4. your own, never someone else's ──────────────────────────────

def test_an_admin_never_sees_another_admins_covenant(env):
    env["rows"] = [_row(NAIYA)]
    assert mine(TIARA)["sign"] == []


def test_someone_with_no_seat_sees_nothing(env):
    env["rows"] = [_row(NAIYA)]
    assert mine("stranger")["on"] is False


# ─── 5. it never gets in the way ────────────────────────────────────

def test_a_business_sees_nothing(env):
    env["type"] = "barber"
    assert mine(OWNER) == {"on": False, "sign": [], "send": []}


def test_a_church_with_the_switch_off_sees_nothing(env):
    env["on"] = False
    assert mine(OWNER)["on"] is False
    with pytest.raises(HTTPException) as e:
        send(OWNER)
    assert e.value.status_code == 404


def test_docuseal_down_shows_nothing_rather_than_breaking(env, monkeypatch):
    async def down(doc):
        return None

    monkeypatch.setattr(cc, "_submission", down)
    env["rows"] = [_row(NAIYA)]
    assert mine(NAIYA)["sign"] == []


def test_a_failed_read_shows_nothing(env, monkeypatch):
    monkeypatch.setattr(cc, "_sent", lambda b: None)
    assert mine(NAIYA)["on"] is False


@pytest.mark.parametrize("value,on", [("off", False), ("nonsense", False)])
def test_the_switch(monkeypatch, value, on):
    monkeypatch.setenv("CHURCH_COVENANT", value)
    assert cc.switched_on(BIZ) is on


# ─── 6. the page ────────────────────────────────────────────────────

def _body(**kw):
    a = {**ADMINS[0], "duties": [("The front desk", "Mondays")], **kw}
    return cc.payload_for("Love City", a, PASTOR, {"email": "kevin@x.org", "name": "Kevin"})


def test_docuseal_emails_nobody():
    body = _body()
    assert body["send_email"] is False and all(s["send_email"] is False for s in body["submitters"])
    assert body["order"] == "preserved"
    assert [s["role"] for s in body["submitters"]] == [text.ADMIN, text.EXEC, text.SENIOR]


def test_the_page_has_every_fill_in_and_every_signature():
    html = _body()["documents"][0]["html"]
    assert html.count("<signature-field") == 3 and html.count("<date-field") == 3
    assert html.count("<checkbox-field") == 3 and html.count("<text-field") == 5
    assert "Naiya Clark: covenant page" in html and "The front desk" in html and "Pastor Jessica" in html


def test_a_name_cannot_break_the_page():
    html = _body(name="<script>x</script> & Co")["documents"][0]["html"]
    assert "<script>" not in html and "&lt;script&gt;" in html


def test_no_executive_pastor_leaves_two_signers():
    body = cc.payload_for("Love City", {**ADMINS[0], "duties": []}, None, {"email": "k@x.org", "name": "Kevin"})
    assert [s["role"] for s in body["submitters"]] == [text.ADMIN, text.SENIOR]
    assert body["documents"][0]["html"].count("<signature-field") == 2


def test_every_lane_has_its_line_and_real_duties():
    for lane in cc.LANES:
        assert text.LANE_LINES[lane]
        assert cc.duties_of(lane)


@pytest.mark.parametrize("day,words", [("Tue, monthly", "Tuesdays and monthly"), ("Sat, Sun", "Saturdays and Sundays"),
                                       ("Mon", "Mondays"), ("as needed", "As needed")])
def test_the_days_read_as_words(day, words):
    assert cc.when_of(day) == words
