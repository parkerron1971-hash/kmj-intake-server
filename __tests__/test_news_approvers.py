"""Who approves good news, and where: news_approvers + member_serving_approve.

Kevin, 2026-11-24 (canvas "Good News Approvals"): the pastors and the leaders
the office picks approve what members share from the member app's Serve
page, hear about it on their phones, and whoever answers first decides.
"""
from __future__ import annotations

import asyncio
import pathlib
import sys

from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import church_news as cn  # noqa: E402
import member_serving_approve as msa  # noqa: E402
import news_approvers as nap  # noqa: E402
import news_share as ns  # noqa: E402
from test_member_portal_group_space import BIZ, MONIQUE, ROCHELLE, TASHA  # noqa: F401
from test_news_share import _User, fake, _share  # noqa: F401
from test_church_news import _me  # noqa: E402

PASTOR_C = TASHA          # the church's own member record for the owner
LEADER_C = ROCHELLE       # a leader the office picked
ADMIN_C = "cccccccc-0000-0000-0000-000000000099"


def _biz(**news):
    return {"id": BIZ, "name": "Love City Church", "owner_id": "o1",
            "settings": {"church_owner_contact_id": PASTOR_C, "news": {"approvers": [LEADER_C], **news}}}


# ── who ──────────────────────────────────────────────────────────────

def test_the_pastors_and_the_picked_leaders_approve(fake):
    b = _biz()
    fake.t["business_users"] = [{"business_id": BIZ, "status": "active", "role": "admin", "contact_id": ADMIN_C},
                                {"business_id": BIZ, "status": "active", "role": "manager", "contact_id": MONIQUE}]
    assert nap.role(b, PASTOR_C) == nap.PASTOR
    assert nap.role(b, ADMIN_C) == nap.PASTOR
    assert nap.role(b, LEADER_C) == nap.LEADER
    assert nap.role(b, MONIQUE) == ""          # a manager login isn't a pastor here
    fake.fail.add("business_users")
    assert nap.role(b, MONIQUE) is None        # a failed read is never "no"
    assert nap.role(b, PASTOR_C) == nap.PASTOR  # the owner needs no read


def test_a_picked_leader_never_sees_words_about_self_harm():
    care = {"attach": {"flag": "care"}}
    plain = {"attach": {"share": "grad"}}
    assert nap.may_see(nap.PASTOR, care) and nap.may_see(nap.PASTOR, plain)
    assert nap.may_see(nap.LEADER, plain) and not nap.may_see(nap.LEADER, care)
    assert not nap.may_see("", plain)


# ── the note ─────────────────────────────────────────────────────────

def test_a_share_tells_the_approvers_and_opens_serve(fake):
    b = _biz()
    fake.t["business_users"] = [{"business_id": BIZ, "status": "active", "role": "admin", "contact_id": ADMIN_C}]
    post = {"id": "p1", "title": "A graduation", "posted_by": MONIQUE, "attach": {"share": "grad"}}
    assert nap.notify(b, post, "Monique Brown") == 1
    kind, kw = fake.pushed[-1]
    assert kind == "news"                                   # the church doesn't use Serving notes
    assert kw["contact_ids"] == [PASTOR_C, ADMIN_C, LEADER_C]
    assert kw["url"] == "/my/serving#approve" and kw["wait"] is True
    assert kw["title"] == "Good news is waiting for you"
    assert kw["body"] == "Monique shared: a graduation. Tap to read it and post it for the church."
    assert kw["ref_id"] == "good-news-ask:p1"


def test_the_note_goes_as_serving_where_the_church_has_those_on(fake):
    b = _biz()
    b["settings"]["member_portal"] = {"notifications": {"serving": True}}
    nap.notify(b, {"id": "p2", "title": "A new job", "posted_by": MONIQUE, "attach": {}}, "Monique Brown")
    assert fake.pushed[-1][0] == "serving"


def test_no_note_when_off_and_none_to_leaders_for_self_harm(fake):
    nap.notify(_biz(approver_alerts=False), {"id": "p3", "title": "x", "posted_by": MONIQUE, "attach": {}}, "M")
    assert fake.pushed == []
    nap.notify(_biz(), {"id": "p4", "title": "x", "posted_by": MONIQUE, "attach": {"flag": "care"}}, "Monique")
    kind, kw = fake.pushed[-1]
    assert kw["contact_ids"] == [PASTOR_C]
    assert kw["body"] == "Monique shared good news. Read it first, then post it or save it for later."


def test_the_writer_is_never_told_about_their_own(fake):
    b = _biz()
    nap.notify(b, {"id": "p5", "title": "x", "posted_by": LEADER_C, "attach": {}}, "Rochelle")
    assert fake.pushed[-1][1]["contact_ids"] == [PASTOR_C]


def test_sharing_rings_the_approvers(fake):
    import test_church_news as tcn
    before = dict(tcn.BUSINESS.get("settings") or {})
    tcn.BUSINESS["settings"] = {**before, "church_owner_contact_id": PASTOR_C}
    try:
        ok, code, pid = _share()
        assert (ok, code) == (True, "shared")
        kind, kw = fake.pushed[-1]
        assert kw["url"] == "/my/serving#approve" and kw["contact_ids"] == [PASTOR_C]
    finally:
        tcn.BUSINESS["settings"] = before


# ── To approve, and first answer wins ────────────────────────────────

def test_to_approve_lists_what_waits_and_who_answered(fake):
    _ok, _code, pid = _share()
    b = _biz()
    got = nap.for_me(b, LEADER_C)
    assert got["role"] == nap.LEADER and [c["id"] for c in got["waiting"]] == [pid]
    c = got["waiting"][0]
    assert (c["name"], c["what"], c["for"]) == ("Monique Brown", "A graduation", "the whole church")
    assert nap.for_me(b, MONIQUE) == {}
    # The leader posts it; the pastor's list says who did, without buttons.
    code, post, told = nap.settle(b, pid, "post", decided_by=f"contact:{LEADER_C}", statuses=("waiting",))
    assert code == "posted" and told is True
    assert post["decided_by"] == f"contact:{LEADER_C}"
    assert [p["id"] for p in cn.feed(BIZ, MONIQUE)] == [pid]
    mine = nap.for_me(b, PASTOR_C)
    assert mine["waiting"] == [] and mine["taken"][0]["by"] == "Rochelle Taylor"
    html = msa.section(mine)
    assert "Rochelle Taylor posted this" in html and "Post it" not in html
    # Their own answer doesn't come back to them as someone else's.
    assert nap.for_me(b, LEADER_C)["taken"] == []
    # The second answer finds it decided.
    assert nap.settle(b, pid, "later", decided_by=f"contact:{PASTOR_C}", statuses=("waiting",))[0] == "gone"


def test_the_office_answer_is_named_too(fake, monkeypatch):
    _ok, _code, pid = _share()
    b = _biz()
    code, _p, _t = nap.settle(b, pid, "post", decided_by="o1")
    assert code == "posted"
    assert nap.for_me(b, LEADER_C)["taken"][0]["by"] == "Tasha Williams"   # the owner, by their member record


def test_edit_first_and_leave_the_photo_off(fake):
    _ok, _code, pid = _share(photo=b"raw")
    row = fake.t["church_posts"][0]
    path = row["attach"]["pics"][0]["path"]
    code, post, _t = nap.settle(_biz(), pid, "post", decided_by=f"contact:{PASTOR_C}", body="  Imani is a nurse!  ",
                                drop_photo=True, statuses=("waiting",))
    assert code == "posted" and row["body"] == "Imani is a nurse!" and "pics" not in row["attach"]
    assert fake.dropped == [path]
    assert nap.settle(_biz(), pid, "post", decided_by="x", body="")[0] == "gone"


def test_an_empty_edit_posts_nothing(fake):
    _ok, _code, pid = _share()
    assert nap.settle(_biz(), pid, "post", decided_by="x", body="   ")[0] == "empty"
    assert fake.t["church_posts"][0]["status"] == "waiting"


def test_not_now_from_the_app_saves_it_for_later(fake):
    _ok, _code, pid = _share()
    assert nap.settle(_biz(), pid, "later", decided_by=f"contact:{LEADER_C}", statuses=("waiting",))[0] == "later"
    assert fake.t["church_posts"][0]["status"] == "declined"
    # Not now in the app is final there; the office can still post it.
    assert nap.settle(_biz(), pid, "post", decided_by="x", statuses=("waiting",))[0] == "gone"
    assert nap.settle(_biz(), pid, "post", decided_by="o1")[0] == "posted"


def test_a_leader_doesnt_see_or_decide_words_about_self_harm(fake):
    _ok, _code, pid = _share()
    fake.t["church_posts"][0]["attach"]["flag"] = "care"
    assert nap.for_me(_biz(), LEADER_C)["waiting"] == []
    assert nap.one(_biz(), LEADER_C, pid) == {}
    assert nap.one(_biz(), PASTOR_C, pid)["flag"] == "care"


def test_the_section_draws_the_buttons(fake):
    _ok, _code, pid = _share()
    html = msa.section(nap.for_me(_biz(), PASTOR_C))
    assert 'id="approve"' in html and "To approve" in html and '<span class="ap-n">1</span>' in html
    assert html.count('action="/my/serving/approve"') == 2
    assert f'href="/my/serving/approve/{pid}">Edit first</a>' in html
    assert ">Post it</button>" in html and ">Not now</button>" in html
    assert "Whoever answers first decides" in html
    assert msa.section({}) == "" and msa.section(None) == ""


def test_an_approver_sees_a_waiting_photo_and_nobody_else_does(fake):
    _ok, _code, pid = _share(photo=b"raw")
    fake.t["businesses"][0]["settings"] = _biz()["settings"]
    assert ns.photo_link(BIZ, pid, 0, LEADER_C).startswith("https://signed.example/")
    assert ns.photo_link(BIZ, pid, 0, PASTOR_C).startswith("https://signed.example/")
    assert ns.photo_link(BIZ, pid, 0, "cccccccc-0000-0000-0000-000000000077") == ""
    assert ns.photo_link(BIZ, pid, 0, MONIQUE).startswith("https://signed.example/")   # their own


def test_the_office_home_count(fake):
    _share()
    _share(kind="job", text="New job at St. Luke's!")
    got = nap.count(_biz())
    assert got["waiting"] == 2 and got["first"][0]["name"] == "Monique Brown"


def test_a_picked_leaders_home_strip(fake):
    _share()
    assert nap.leader_desk(_biz(), LEADER_C)["good"] == 1
    assert nap.leader_desk(_biz(), MONIQUE) == {}


# ── the office picks ─────────────────────────────────────────────────

def _office(monkeypatch, role):
    import kids_router
    from auth_supabase import require_user
    monkeypatch.setattr(kids_router, "role_for", lambda biz, user: role)
    app = FastAPI()
    app.include_router(cn.router)
    app.include_router(ns.router)
    app.dependency_overrides[require_user] = lambda: _User()
    return TestClient(app)


def test_the_owner_and_admins_pick_the_leaders(fake, monkeypatch):
    body = {"business_id": BIZ, "add": [ROCHELLE]}
    assert _office(monkeypatch, "manager").post("/church/news/approvers", json=body).status_code == 403
    r = _office(monkeypatch, "admin").post("/church/news/approvers", json=body)
    assert r.status_code == 200 and r.json()["picked"] == [ROCHELLE]
    assert fake.t["businesses"][0]["settings"]["news"]["approvers"] == [ROCHELLE]
    r = _office(monkeypatch, "admin").post("/church/news/approvers",
                                          json={"business_id": BIZ, "add": ["cccccccc-0000-0000-0000-000000000077"]})
    assert r.status_code == 404                                          # not one of their people
    r = _office(monkeypatch, "owner").post("/church/news/approvers", json={"business_id": BIZ, "remove": [ROCHELLE]})
    assert r.json()["picked"] == []


def test_the_note_switch_and_the_home_count_route(fake, monkeypatch):
    c = _office(monkeypatch, "admin")
    assert c.post("/church/news/settings", json={"business_id": BIZ, "approver_alerts": False}).status_code == 200
    assert fake.t["businesses"][0]["settings"]["news"]["approver_alerts"] is False
    c.post("/church/news/settings", json={"business_id": BIZ, "approver_alerts": True})
    assert "approver_alerts" not in fake.t["businesses"][0]["settings"]["news"]
    _share()
    r = _office(monkeypatch, "viewer").get(f"/church/news/shared/count?business_id={BIZ}")
    assert r.status_code == 200 and r.json()["waiting"] == 1


def test_the_office_still_posts_through_the_same_step(fake, monkeypatch):
    _ok, _code, pid = _share()
    r = _office(monkeypatch, "admin").post(f"/church/news/shared/{pid}", json={"business_id": BIZ, "action": "post"})
    assert r.status_code == 200
    row = fake.t["church_posts"][0]
    assert row["status"] == "posted" and row["decided_by"] == "u1"
    r = _office(monkeypatch, "admin").post(f"/church/news/shared/{pid}", json={"business_id": BIZ, "action": "post"})
    assert r.status_code == 404


def test_the_approve_route_is_mounted_before_the_catch_all():
    import kmj_intake_automation as app_mod
    paths = [getattr(r, "path", "") for r in app_mod.app.routes]
    assert "/my/serving/approve" in paths and "/church/news/approvers" in paths
    assert "/church/news/shared/count" in paths
    catch = next(i for i, p in enumerate(paths) if "{" in p and p.count("/") <= 2 and "path" in p)
    assert paths.index("/my/serving/approve") < catch


def test_decide_from_the_app(fake, monkeypatch):
    """POST /my/serving/approve: signed in, theirs to decide, then settle."""
    _ok, _code, pid = _share()
    church = {"business": _biz(), "site": None}
    me = _me(LEADER_C, "Rochelle Taylor")

    async def signed_in(request):
        return church, me, False
    import member_portal_church as mpc
    import rate_limit
    monkeypatch.setattr(mpc, "_signed_in", signed_in)
    monkeypatch.setattr(rate_limit, "allow_strict", lambda *a, **k: True)

    class Req:
        def __init__(self, form):
            self._form = form

        async def form(self):
            return self._form
    r = asyncio.run(msa.decide(Req({"id": pid, "action": "post"})))
    assert r.status_code == 303 and r.headers["location"] == "/my/serving?done=ap_posted#approve"
    assert fake.t["church_posts"][0]["decided_by"] == f"contact:{LEADER_C}"
    r = asyncio.run(msa.decide(Req({"id": pid, "action": "later"})))
    assert r.headers["location"] == "/my/serving?err=ap_gone#approve"
    me["id"] = MONIQUE                                                   # not an approver
    _ok, _code, pid2 = _share(kind="job", text="A new job!")
    r = asyncio.run(msa.decide(Req({"id": pid2, "action": "post"})))
    assert r.headers["location"] == "/my/serving?err=ap_gone#approve"
    assert next(p for p in fake.t["church_posts"] if p["id"] == pid2)["status"] == "waiting"
