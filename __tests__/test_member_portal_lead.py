"""The Lead tab (member_portal_lead.py): a leader's side of the member page.

Leaders are members: the tab appears only for someone holding (or asked to
hold) a church role, shows only the follow-ups handed to them, and every
action is checked against that. The tables are test_church_follow_up's
in-memory PostgREST; the signed-in member is set at member_portal_church's
_signed_in, which the session tests already cover."""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (ROOT, os.path.dirname(os.path.abspath(__file__))):
    if p not in sys.path:
        sys.path.insert(0, p)

import church_follow_up as cfu  # noqa: E402
import member_app_ui as ui  # noqa: E402
import member_portal_church as mpc  # noqa: E402
import member_portal_lead as mpl  # noqa: E402
from test_church_follow_up import (BIZ, DANA, MARCUS, ROBERT, SERVE, BAPTISM, TASHA, NAMES,  # noqa: E402,F401
                                   db, _open)

BUSINESS = {"id": BIZ, "name": "Love City Church", "type": "ministry", "settings": {"timezone": "America/Detroit"}}


def _me(cid):
    return {"id": cid, "name": NAMES[cid]}


def _req(**q):
    return SimpleNamespace(query_params=q)


@pytest.fixture
def shell(monkeypatch):
    """The page's shell is member_portal's; here it just keeps the body and
    the tab so the tests read what the Lead page itself writes."""
    import member_portal
    seen = {}

    def fake_shell(biz, site, title, body, **kw):
        seen.update(kw, title=title)
        return body
    monkeypatch.setattr(member_portal, "_shell", fake_shell)
    return seen


# ─── The tab ──────────────────────────────────────────────────────────

def test_only_a_leader_gets_the_lead_tab_and_it_comes_last():
    plain, leader = ui.nav("home"), ui.nav("lead", lead=True)
    assert "/my/lead" not in plain
    assert leader.count('class="mb-tab"') == plain.count('class="mb-tab"') + 1
    assert leader.rindex("/my/lead") > leader.rindex("/my/groups")
    assert 'href="/my/lead" aria-current="page"' in leader


def test_on_a_wide_screen_the_tab_bar_is_a_rail_down_the_left():
    css = ui.css(BUSINESS, {})
    assert "@media (min-width:1100px){.mb-nav{top:0;bottom:0;left:0" in css


# ─── The page ─────────────────────────────────────────────────────────

def test_someone_with_no_role_is_told_plainly(db, shell):
    html, status = asyncio.run(mpl.serve(_req(), BUSINESS, {}, _me(DANA), "/my/lead"))
    assert status == 200 and "You don’t lead anything at Love City Church yet" in html
    assert shell["tab"] == "lead"


def test_an_invitation_is_answered_on_the_page(db, shell):
    role = cfu.add_role(BIZ, DANA, "team_leader", "Hospitality Team", by_user="u")
    html, _ = asyncio.run(mpl.serve(_req(), BUSINESS, {}, _me(DANA), "/my/lead"))
    assert "Will you lead <em>the Hospitality Team</em>?" in html
    assert cfu.role_name({"role": "team_leader", "scope": "Youth Ministry (YWD)"}) == "the Youth Ministry (YWD) team"
    assert cfu.role_name({"role": "welcome_lead"}) == "Welcome Team lead"
    assert f'name="role_id" value="{role["id"]}"' in html and 'value="yes"' in html and 'value="no"' in html


def test_a_leader_sees_their_people_the_late_one_first_and_chief_names_them(db, shell):
    dana = _open(db)
    _open(db, SERVE, MARCUS, team="Hospitality Team")
    for r in db.t["church_follow_ups"]:
        if r["id"] == dana["id"]:
            r["due_at"] = cfu._iso(cfu._now() - timedelta(days=1, hours=2))
    html, status = asyncio.run(mpl.serve(_req(), BUSINESS, {}, _me(TASHA), "/my/lead"))
    assert status == 200
    assert html.index("Dana Rivers") < html.index("Marcus Taylor"), "the late one first"
    assert "Dana is past due. A quick call today?" in html
    assert "Team leader · Hospitality Team" in html and "2 handed to you" in html
    # Robert holds a role but was handed nobody: his list is empty, never Tasha's.
    other, _ = asyncio.run(mpl.serve(_req(), BUSINESS, {}, _me(ROBERT), "/my/lead"))
    assert "Dana Rivers" not in other and "Nobody is waiting on you" in other


def test_one_person_shows_what_they_wrote_the_path_and_the_note_form(db, shell):
    f = _open(db, SERVE, DANA, team="Hospitality Team", nmo="Not yet")
    html, status = asyncio.run(mpl.serve(_req(), BUSINESS, {}, _me(TASHA), f"/my/lead/{f['id']}"))
    assert status == 200 and shell["back"] == ("/my/lead", "Lead")
    assert "Where would you like to serve?" in html and "Not yet" in html
    assert "Mark “Reach out” done" in html and 'action="/my/lead/note"' in html
    assert 'name="pastors_only"' in html and "Why you:</b> They picked Hospitality Team, and Tasha leads it." in html
    assert 'href="mailto:dana@example.com"' in html


def test_someone_elses_follow_up_is_never_shown_by_its_address(db, shell):
    f = _open(db)
    html, _ = asyncio.run(mpl.serve(_req(), BUSINESS, {}, _me(ROBERT), f"/my/lead/{f['id']}"))
    assert "Dana Rivers" not in html


def test_due_labels_read_like_a_person_would_say_them():
    now = datetime(2026, 10, 17, 15, tzinfo=timezone.utc)                       # Sat 11am Detroit
    item = lambda d: {"due_at": (now + d).isoformat()}                           # noqa: E731
    assert mpl.due_label(item(timedelta(days=-2)), BUSINESS, now) == {"text": "2 days late", "cls": "ld-due late"}
    assert mpl.due_label(item(timedelta(days=1)), BUSINESS, now) == {"text": "Due Sun", "cls": "ld-due soon"}
    assert mpl.due_label(item(timedelta(days=20)), BUSINESS, now)["text"] == "Due Nov 6"


# ─── The actions ──────────────────────────────────────────────────────

@pytest.fixture
def lead(db, monkeypatch):
    who = {"me": _me(TASHA), "unavailable": False}

    async def signed_in(request):
        return {"business": BUSINESS, "site": {}}, who["me"], who["unavailable"]
    monkeypatch.setattr(mpc, "_signed_in", signed_in)
    import rate_limit
    monkeypatch.setattr(rate_limit, "allow_strict", lambda *a: True)
    app = FastAPI()
    app.include_router(mpl.router)
    c = TestClient(app)
    c.who = who
    return c


def _post(c, path, **data):
    return c.post(path, data=data, follow_redirects=False)


def test_logging_a_conversation_saves_it_and_moves_them_past_reach_out(lead, db):
    f = _open(db)
    r = _post(lead, "/my/lead/note", fid=f["id"], outcome="talked", text="Called Dana.", pastors_only="yes")
    assert r.status_code == 303 and r.headers["location"] == f"/my/lead/{f['id']}?done=saved"
    note = [n for n in db.t["church_follow_up_notes"] if n["kind"] == "talked"][0]
    assert note["body"] == "Called Dana." and note["pastors_only"] is True and note["author_contact_id"] == TASHA
    assert cfu._one(BIZ, f["id"])["step"] == 1


def test_marking_the_last_step_finishes_and_returns_to_the_list(lead, db):
    f = _open(db)
    for want in ("step", "step", "finished"):
        r = _post(lead, "/my/lead/step", fid=f["id"])
        assert want in r.headers["location"]
    assert cfu._one(BIZ, f["id"])["status"] == "done"


def test_another_leader_cannot_act_on_someone_not_handed_to_them(lead, db):
    f = _open(db)
    lead.who["me"] = _me(ROBERT)
    r = _post(lead, "/my/lead/note", fid=f["id"], outcome="talked", text="hi")
    assert r.headers["location"] == "/my/lead?err=gone"
    assert not [n for n in db.t["church_follow_up_notes"] if n["kind"] == "talked"]


def test_a_member_with_no_role_cannot_act_at_all(lead, db):
    f = _open(db)
    lead.who["me"] = _me(DANA)
    r = _post(lead, "/my/lead/step", fid=f["id"])
    assert r.headers["location"] == "/my/lead" and cfu._one(BIZ, f["id"])["step"] == 0


def test_the_owners_preview_never_saves(lead, db):
    f = _open(db)
    lead.who.update(me=None, unavailable="preview")
    r = _post(lead, "/my/lead/note", fid=f["id"], outcome="talked", text="hi")
    assert r.headers["location"] == f"/my/lead/{f['id']}?err=preview"
    assert not [n for n in db.t["church_follow_up_notes"] if n["kind"] == "talked"]


def test_saying_yes_to_an_invitation_makes_the_role_active(lead, db):
    role = cfu.add_role(BIZ, DANA, "welcome_lead", by_user="u")
    lead.who["me"] = _me(DANA)
    r = _post(lead, "/my/lead/answer", role_id=role["id"], answer="yes")
    assert r.headers["location"] == "/my/lead?done=yes"
    assert [x["status"] for x in cfu.roles_for(BIZ, DANA)] == ["active"]


def test_handing_back_returns_them_to_the_office(lead, db):
    f = _open(db)
    r = _post(lead, "/my/lead/handback", fid=f["id"], text="Away all month.")
    assert r.headers["location"] == "/my/lead?done=back"
    assert cfu._one(BIZ, f["id"])["status"] == "handed_back"


def test_a_redirect_never_leaves_the_lead_pages():
    assert mpl._go("https://evil.example").headers["location"] == "/my/lead"
    assert mpl._go("/my/lead/not-an-id").headers["location"] == "/my/lead"
