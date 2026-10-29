"""Prayer shared with the prayer team (church_prayer.py; the member page,
website and private-care saves; the Lead tab's Prayer list; the sweep).
Kevin, 2026-10-17: prayer is always connected to the pastoral roles, and the
pastor can name a leader to oversee prayer requests ("create and
Intercessor leader now"). Canvas BKNqVVNiyxfAGAa7UAVWUC, boards 2, 5, 7, 8.

What these hold: a request reaches a member who leads only when the person
chose to share it; words about danger, abuse or a death never do; a leader
sees a first name, the words, and how to reach them only when the person
asked for a call; emails never carry the request's words."""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import timedelta

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import church_follow_up as cfu  # noqa: E402
import church_prayer as cp  # noqa: E402
import church_roles as cr  # noqa: E402
from test_church_roles import CHURCH, db  # noqa: E402,F401  (the fake database fixture)
from test_church_follow_up import BIZ, OTHER_BIZ, PASTOR, DANA, MARCUS, KEISHA, ANDRE, _role  # noqa: E402

WORDS = "Please pray for my mother’s surgery on Tuesday."


@pytest.fixture
def prayer(db):
    """Love City with its library filled, Dana as Intercessor leader and
    Marcus as an intercessor under her."""
    cr.ensure_library(CHURCH)
    db.t["church_leader_roles"] += [_role(DANA, "intercessor_leader"), _role(MARCUS, "intercessors")]
    return db


def _request(db, *, share=True, text=WORDS, call=False, email="ann@example.org", name="Ann Lee", phone="555-0199"):
    sub = {"name": name, "email": email, "phone": phone, "prayer_request": text, "source": "Member page"}
    row = {"business_id": BIZ, "form_id": None, "status": "new", "submission": sub,
           **cp.consent_columns(sub, share=share, wants_call=call)}
    made = db.post("/ministry_care_requests", row)[0]
    return made


@pytest.mark.parametrize("text", ["I want to end my life", "My husband hits me", "My dad passed away last night",
                                  "Please pray, I was abused as a child", "I keep thinking about suicide"])
def test_words_about_danger_abuse_or_a_death_are_always_the_pastors(text):
    assert cp.needs_pastor(text)
    cols = cp.consent_columns({"prayer_request": text}, share=True)
    assert cols == {"prayer_team": False, "wants_call": False, "needs_pastor": True}


def test_an_ordinary_request_is_shared_only_when_the_person_chose_it():
    assert not cp.needs_pastor(WORDS)
    assert cp.consent_columns({"prayer_request": WORDS}, share=True)["prayer_team"] is True
    assert cp.consent_columns({"prayer_request": WORDS}, share=False)["prayer_team"] is False
    assert cp.consent_columns({"prayer_request": WORDS})["prayer_team"] is False, "no answer is not a yes"


def test_a_shared_request_goes_to_the_intercessor_leader_due_in_a_day(prayer):
    row = _request(prayer)
    out = cp.on_new(BIZ, row)
    assert out["leader_contact_id"] == DANA and out["leader_role"] == "intercessor_leader"
    due = cfu._parse(out["leader_due_at"]) - cfu._parse(out["leader_assigned_at"])
    assert due == timedelta(days=1)


@pytest.mark.parametrize("kw", [{"share": False}, {"text": "My dad passed away"}])
def test_a_request_kept_for_the_pastors_or_needing_one_is_handed_to_no_one(prayer, kw):
    row = _request(prayer, **kw)
    assert cp.on_new(BIZ, row) is None
    assert prayer.t["ministry_care_requests"][-1].get("leader_contact_id") is None


def test_with_no_one_leading_prayer_it_waits_with_the_pastor(db):
    cr.ensure_library(CHURCH)
    row = _request(db)
    assert cp.on_new(BIZ, row) is None


def test_two_prayer_leaders_share_the_requests(prayer):
    prayer.t["church_leader_roles"].append(_role(KEISHA, "intercessor_leader"))
    got = [cp.on_new(BIZ, _request(prayer))["leader_contact_id"] for _ in range(4)]
    assert sorted(got) == sorted([DANA, DANA, KEISHA, KEISHA])


def test_a_leader_sees_a_first_name_and_reaches_them_only_when_they_asked_for_a_call(prayer):
    cp.on_new(BIZ, _request(prayer, call=False))
    cp.on_new(BIZ, _request(prayer, call=True, name="Marcus Hill", phone="555-0123"))
    view = cp.leader_prayers(BIZ, DANA)
    by = {p["first"]: p for p in view["requests"]}
    assert set(by) == {"Ann", "Marcus"}
    assert by["Ann"]["text"] == WORDS and by["Ann"]["phone"] == "" and by["Ann"]["email"] == ""
    assert by["Marcus"]["phone"] == "555-0123"
    assert "Lee" not in str(view) and "Hill" not in str(view), "never the last name"
    assert cp.leader_prayers(BIZ, MARCUS)["requests"] == [], "only what's handed to you"


def test_a_role_that_may_not_see_how_to_reach_them_never_does(prayer):
    d = cr.by_key(cr.defs(BIZ))
    cr.update_role(BIZ, d["intercessor_leader"]["id"], {"sees": []})
    cp.on_new(BIZ, _request(prayer, call=True))
    assert cp.leader_prayers(BIZ, DANA)["requests"][0]["phone"] == ""


def test_i_prayed_marks_it_for_the_office_too_and_only_for_their_own(prayer):
    row = cp.on_new(BIZ, _request(prayer))
    cp.prayed(BIZ, {"id": DANA, "name": "Dana Rivers"}, row["id"])
    saved = prayer.t["ministry_care_requests"][-1]
    assert saved["leader_prayed_at"] and saved["prayed_at"]
    with pytest.raises(Exception) as e:
        cp.prayed(BIZ, {"id": MARCUS, "name": "Marcus Taylor"}, row["id"])
    assert e.value.status_code == 404


def test_a_note_says_we_prayed_never_their_words_and_goes_once(prayer, monkeypatch):
    row = cp.on_new(BIZ, _request(prayer))
    sent = []

    async def email(biz, to, name, subject, body, key):
        sent.append((to, subject, body))
        return True
    monkeypatch.setattr(cfu, "_email", email)
    leader = {"id": DANA, "name": "Dana Rivers"}
    assert asyncio.run(cp.send_note(CHURCH, leader, row["id"]))
    assert asyncio.run(cp.send_note(CHURCH, leader, row["id"]))
    assert len(sent) == 1
    to, subject, body = sent[0]
    assert to == "ann@example.org" and subject == "We prayed for you today"
    assert "surgery" not in body and "Love City Church is with you" in body and "Dana" in body
    nomail = cp.on_new(BIZ, _request(prayer, email=""))
    with pytest.raises(Exception) as e:
        asyncio.run(cp.send_note(CHURCH, leader, nomail["id"]))
    assert e.value.status_code == 400


def test_a_request_is_passed_only_to_someone_who_prays_under_you(prayer):
    row = cp.on_new(BIZ, _request(prayer))
    leader = {"id": DANA, "name": "Dana Rivers"}
    assert [t["contact_id"] for t in cp.pass_targets(BIZ, leader)] == [MARCUS]
    with pytest.raises(Exception) as e:
        cp.pass_on(BIZ, leader, row["id"], KEISHA)
    assert e.value.status_code == 400
    out = cp.pass_on(BIZ, leader, row["id"], MARCUS)
    assert out["leader_contact_id"] == MARCUS and out["leader_role"] == "intercessors" and out["leader_told_at"] is None
    assert [p["first"] for p in cp.leader_prayers(BIZ, MARCUS)["requests"]] == ["Ann"]


def test_the_sweep_tells_them_once_then_climbs_their_chain_without_the_words(prayer, monkeypatch):
    sent, alerts = [], []

    async def email(biz, to, name, subject, body, key):
        sent.append((to, subject, body))
        return True

    async def alert(biz_id, title, body, key, person):
        alerts.append((title, body))
        return True
    monkeypatch.setattr(cfu, "_email", email)
    monkeypatch.setattr(cfu, "_office_alert", alert)
    monkeypatch.setattr(cfu, "site_origin", lambda b: "https://lovecityc.com")
    row = cp.on_new(BIZ, _request(prayer))
    asyncio.run(cp.sweep())
    asyncio.run(cp.sweep())
    due = cfu._parse(row["leader_due_at"])
    asyncio.run(cp.sweep(due + timedelta(hours=1)))
    asyncio.run(cp.sweep(due + timedelta(days=1, hours=1)))
    asyncio.run(cp.sweep(due + timedelta(days=3, hours=1)))
    assert [(to, s) for to, s, _ in sent] == [
        ("dana@example.com", "A prayer request is waiting for you"),
        ("dana@example.com", "Ann’s prayer request is due today"),
        ("kevin@example.com", "A prayer request has waited a day"),
        ("kevin@example.com", "A prayer request has waited three days"),
    ]
    assert all("surgery" not in body for _, _, body in sent), "emails never carry the request"
    assert "https://lovecityc.com/my/lead/prayer" in sent[0][2]
    assert [t for t, _ in alerts] == ["A prayer request is waiting", "Hand a prayer request to someone else?"]
    assert prayer.t["ministry_care_requests"][-1]["leader_late_level"] == 3


def test_removing_a_prayer_leaders_last_role_returns_their_requests(prayer):
    row = cp.on_new(BIZ, _request(prayer))
    held = next(r for r in prayer.t["church_leader_roles"] if r["contact_id"] == DANA)
    assert cfu.remove_role(BIZ, held["id"])["prayer_returned"] == 1
    assert prayer.t["ministry_care_requests"][-1]["leader_contact_id"] is None


def test_the_office_sees_who_has_it_and_that_they_prayed(prayer):
    row = cp.on_new(BIZ, _request(prayer))
    cp.prayed(BIZ, {"id": DANA, "name": "Dana Rivers"}, row["id"])
    out = cp.office_fields(prayer.t["ministry_care_requests"], BIZ)[-1]
    assert out["prayer_team"] is True and out["leader"] == {"name": "Dana Rivers", "role_title": "Intercessor leader"}
    assert out["leader_prayed_at"]


# ─── Where requests come from ─────────────────────────────────────────

def test_the_member_page_shares_only_when_they_chose_and_never_for_youth(prayer):
    import member_portal_church as mpc
    me = {"id": KEISHA, "name": "Keisha Morgan", "email": "keisha@example.com", "phone": ""}
    assert mpc.save_prayer(BIZ, me, WORDS, confidential=False, wants_call=True)
    shared = prayer.t["ministry_care_requests"][-1]
    assert shared["prayer_team"] and shared["wants_call"] and shared["leader_contact_id"] == DANA
    assert mpc.save_prayer(BIZ, me, WORDS, confidential=True)
    assert prayer.t["ministry_care_requests"][-1].get("leader_contact_id") is None
    assert mpc.save_prayer(BIZ, me, WORDS, confidential=False, youth=True)
    youth = prayer.t["ministry_care_requests"][-1]
    assert youth["prayer_team"] is False and youth["submission"]["confidential"] == "yes"


def test_the_website_shares_only_on_the_prayer_team_answer(prayer):
    import website_forms
    base = {"name": "Ann Lee", "email": "ann@example.org", "phone": "", "message": WORDS}
    row = website_forms.save_prayer(BIZ, dict(base, fields={"request": WORDS, "follow_up": True,
                                                         "share": "Our prayer team may pray over this with me"}), "r-1")
    assert row["prayer_team"] and row["wants_call"] and prayer.t["ministry_care_requests"][-1]["leader_contact_id"] == DANA
    row = website_forms.save_prayer(BIZ, dict(base, fields={"request": WORDS, "share": "Keep this with the pastors only"}), "r-2")
    assert row["prayer_team"] is False and row["submission"]["confidential"] == "yes"


def test_the_website_form_validator_keeps_the_answer():
    import website_forms
    data = website_forms.validate({"name": "Ann Lee", "email": "ann@example.org", "phone": "", "form": "prayer_request",
                                   "message": WORDS, "fields": {"request": WORDS, "share": "Keep this with the pastors only"}})
    assert data["fields"]["share"] == "Keep this with the pastors only"


# ─── The Lead tab's Prayer list (board 7) and the invitation (board 8) ─

BUSINESS = {"id": BIZ, "name": "Love City Church", "type": "ministry", "settings": {"timezone": "America/Detroit"}}


@pytest.fixture
def shell(monkeypatch):
    import member_portal
    seen = {}

    def fake_shell(biz, site, title, body, **kw):
        seen.update(kw, title=title)
        return body
    monkeypatch.setattr(member_portal, "_shell", fake_shell)
    return seen


def _page(path, me):
    import member_portal_lead as mpl
    from types import SimpleNamespace
    return asyncio.run(mpl.serve(SimpleNamespace(query_params={}), BUSINESS, {}, me, path))


def test_a_prayer_leader_sees_the_requests_handed_to_them_and_nothing_else(prayer, shell):
    cp.on_new(BIZ, _request(prayer, call=True))
    html, status = _page("/my/lead/prayer", {"id": DANA, "name": "Dana Rivers"})
    assert status == 200 and shell["title"] == "Prayer"
    assert "1 request is waiting for prayer." in html and WORDS.replace("’", "&#x27;") not in html
    assert "Please pray for my mother" in html and ">Ann<" in html and "Lee" not in html
    assert 'action="/my/lead/prayer/prayed"' in html and "Call Ann" in html
    assert '<option value="%s">Marcus Taylor</option>' % MARCUS in html, "pass it to an intercessor under you"
    assert "Never their words" in html
    html, _ = _page("/my/lead", {"id": DANA, "name": "Dana Rivers"})
    assert "1 request is waiting" in html, "someone who only leads prayer lands on Prayer"


def test_the_invitation_carries_the_roles_definition_and_who_they_answer_to(prayer, shell):
    cr_defs = cr.by_key(cr.defs(BIZ))
    row = cfu.add_role(BIZ, KEISHA, cr_defs["intercessor_leader"]["id"], by_user="u")
    html, _ = _page("/my/lead", {"id": KEISHA, "name": "Keisha Morgan"})
    assert "Will you be Love City Church’s <em>Intercessor leader</em>?" in html
    assert "Leads Love City Church in prayer" in html and "The Lead Pastor. If something waits a day" in html
    assert "You’ll never see" in html and row["id"] in html


@pytest.fixture
def lead(prayer, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import member_portal_church as mpc
    import member_portal_lead as mpl
    import rate_limit
    who = {"me": {"id": DANA, "name": "Dana Rivers"}}

    async def signed_in(request):
        return {"business": BUSINESS, "site": {}}, who["me"], False
    monkeypatch.setattr(mpc, "_signed_in", signed_in)
    monkeypatch.setattr(rate_limit, "allow_strict", lambda *a: True)
    app = FastAPI()
    app.include_router(mpl.router)
    c = TestClient(app)
    c.who = who
    return c


def test_i_prayed_and_pass_it_on_from_the_lead_tab(lead, prayer):
    one = cp.on_new(BIZ, _request(prayer))
    two = cp.on_new(BIZ, _request(prayer, name="Bea Ray"))
    r = lead.post("/my/lead/prayer/prayed", data={"rid": one["id"]}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/my/lead/prayer?done=prayed"
    assert next(x for x in prayer.t["ministry_care_requests"] if x["id"] == one["id"])["leader_prayed_at"]
    r = lead.post("/my/lead/prayer/pass", data={"rid": two["id"], "to": MARCUS}, follow_redirects=False)
    assert r.headers["location"] == "/my/lead/prayer?done=passed"
    lead.who["me"] = {"id": KEISHA, "name": "Keisha Morgan"}
    r = lead.post("/my/lead/prayer/prayed", data={"rid": two["id"]}, follow_redirects=False)
    assert r.headers["location"] == "/my/lead", "someone who leads nothing can't act at all"



def test_a_prayer_rung_climbs_only_when_the_pastor_was_emailed(prayer, monkeypatch):
    """Review of #1477, item 2."""
    down = {"on": True}

    async def email(biz, to, name, subject, body, key):
        return not (down["on"] and to.startswith("kevin"))

    async def alert(biz_id, title, body, key, person):
        return True
    monkeypatch.setattr(cfu, "_email", email)
    monkeypatch.setattr(cfu, "_office_alert", alert)
    row = cp.on_new(BIZ, _request(prayer))
    due = cfu._parse(row["leader_due_at"])
    asyncio.run(cp.sweep())
    asyncio.run(cp.sweep(due + timedelta(hours=1)))
    asyncio.run(cp.sweep(due + timedelta(days=1, hours=1)))
    saved = prayer.t["ministry_care_requests"][-1]
    assert saved["leader_late_level"] == 1
    down["on"] = False
    asyncio.run(cp.sweep(due + timedelta(days=1, hours=2)))
    assert saved["leader_late_level"] == 2
