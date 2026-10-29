# __tests__/test_group_lead.py
#
# "My group" on the member app's Lead tab (group_lead.py; the approved
# canvas "Church Groups, Together", board Lead). Pins:
#   1. a group's leaders get the Lead tab and their group on it, even with
#      no church role; a member who leads nothing sees nothing to lead
#   2. this month (people, asking to join, came last time, saw the pinned
#      post), Quick, Needs you (Say yes / Not now right here, who's missed
#      the last three gatherings, a request that went to a pastor), Chief's
#      draft, your last post
#   3. answering from the Lead tab lands back on it; a back address that
#      isn't ours goes to the group as before
#   4. a failed read says try again, never "nothing needs you"

import asyncio
import pathlib
import sys
from datetime import datetime, timezone

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import group_lead as gl
import member_portal_lead as mpl
from test_group_gatherings import THURSDAY_NIGHT, meet  # noqa: F401
from test_member_portal_group_space import (BIZ, BUSINESS, G, MONIQUE, ROCHELLE, TASHA, TEEN,  # noqa: F401
                                            _client, _me, _req, fake)


@pytest.fixture
def lead(meet, monkeypatch):
    import church_follow_up as cfu
    monkeypatch.setattr(cfu, "roles_for", lambda b, c: [])
    meet.t.update(group_prayers=[], group_studies=[], sermons=[], group_bring=[])
    return meet


def _page(who, gid=""):
    req = _req()
    html, status = asyncio.run(mpl.serve_groups(req, BUSINESS, None, _me(who, "Tasha Williams" if who == TASHA else "Monique Brown"), gid))
    return html, status


def _meeting(fake, mid, day, came):
    fake.t["group_meetings"].append({"id": mid, "business_id": BIZ, "group_id": G, "met_on": day, "visitors": 0, "notes": ""})
    fake.t["group_meeting_attendance"] += [{"meeting_id": mid, "contact_id": c, "business_id": BIZ, "how": "office"} for c in came]


# ── 1. who gets it ───────────────────────────────────────────────────

def test_a_groups_leader_has_their_group(lead):
    assert [g["id"] for g in gl.led_groups(BIZ, TASHA)] == [G]
    assert gl.led_groups(BIZ, MONIQUE) == []
    html, status = _page(TASHA)
    assert status == 200 and "You lead Sisters in the City" in html and "Good " in html


def test_someone_who_leads_nothing(lead):
    html, status = _page(MONIQUE)
    assert status == 200 and "You don’t lead a group right now" in html and "Quick" not in html


def test_the_lead_tab_opens_on_the_group_without_a_church_role(lead):
    html, status = asyncio.run(mpl.serve(_req(), BUSINESS, None, _me(TASHA, "Tasha Williams"), "/my/lead"))
    assert status == 200 and "You lead Sisters in the City" in html


def test_the_segment_names_the_group_first():
    seg = mpl._seg("groups", True, True, 0, 0, 1)
    assert seg.index("My group") < seg.index("People") < seg.index("Prayer")
    assert "My groups" in mpl._seg("groups", True, False, 0, 0, 2)
    assert mpl._seg("groups", False, False, 0, 0, 1) == ""          # one thing to lead: no segment


# ── 2. the page ──────────────────────────────────────────────────────

def test_this_month_quick_and_needs_you(lead):
    lead.t["group_join_requests"].append({"id": "eeeeeeee-0000-0000-0000-00000000aaaa", "business_id": BIZ, "group_id": G,
                                          "contact_id": ROCHELLE, "status": "waiting", "asked_at": "2026-10-16T12:00:00+00:00"})
    for i, day in enumerate(["2026-10-15", "2026-10-08", "2026-10-01"]):
        _meeting(lead, f"mmmmmmmm-0000-0000-0000-00000000000{i}", day, [TASHA, MONIQUE])     # Kayla missed all three
    lead.t["group_prayers"].append({"business_id": BIZ, "group_id": G, "to_pastor": True,
                                    "created_at": datetime.now(timezone.utc).isoformat()})
    html, _ = _page(TASHA)
    assert "<b>3</b><small>people · 1 asking to join</small>" in html
    assert "<b>2</b><small>came Thursday" in html
    assert f'href="/my/groups/{G}/board#post"' in html and f'href="/my/groups/{G}/meet"' in html
    assert "Rochelle" in html and f'name="back" value="/my/lead/groups/{G}"' in html and "Say yes" in html
    assert "Haven’t been in a while" in html and "Kayla" in html
    assert "A pastor has one request" in html


def test_nothing_needs_you(lead):
    html, _ = _page(TASHA)
    assert "Nothing needs you right now." in html


def test_someone_new_isnt_missing(lead):
    for i, day in enumerate(["2026-10-15", "2026-10-08", "2026-10-01"]):
        _meeting(lead, f"mmmmmmmm-0000-0000-0000-00000000000{i}", day, [TASHA, MONIQUE])
    for m in lead.t["group_members"]:
        if m["contact_id"] == TEEN:
            m["joined_on"] = "2026-10-10"                              # joined after the first of the three
    html, _ = _page(TASHA)
    assert "Haven’t been in a while" not in html


def test_chiefs_draft_and_your_last_post(lead):
    import group_study as gy
    lead.t["sermons"] = [{"id": "55555555-0000-0000-0000-000000000001", "business_id": BIZ, "series_id": None,
                          "title": "Built to Last", "scripture": "Luke 6:46-49", "summary": "", "questions": "What holds?\nWhat shook?",
                          "preached_on": datetime.now(timezone.utc).date().isoformat(), "video_url": "", "audio_url": "",
                          "published": True, "created_at": "2026-10-18T00:00:00+00:00"}]
    for g in lead.t["groups"]:
        g["study_on"] = True
    gy.sweep_tick()
    lead.t["group_posts"].append({"id": "pppppppp-0000-0000-0000-000000000001", "business_id": BIZ, "group_id": G,
                                  "title": "No gathering Thanksgiving week", "body": "Potluck the 19th.", "pinned": True,
                                  "ask_ack": True, "posted_by": TASHA, "removed_at": None, "emailed": 2,
                                  "created_at": "2026-10-19T12:00:00+00:00"})
    html, _ = _page(TASHA)
    assert "Post them as they are" in html and "Built to Last" in html
    assert "Your last post" in html and "No gathering Thanksgiving week" in html and "2 got it by email" in html
    assert "saw your pinned post" in html


# ── 3. answering from here ───────────────────────────────────────────

def test_say_yes_lands_back_on_the_lead_tab(lead, monkeypatch):
    lead.t["group_join_requests"].append({"id": "eeeeeeee-0000-0000-0000-00000000aaaa", "business_id": BIZ, "group_id": G,
                                          "contact_id": ROCHELLE, "status": "waiting", "asked_at": "2026-10-16T12:00:00+00:00"})
    r = _client(monkeypatch, _me(TASHA, "Tasha")).post(
        "/my/groups/answer", data={"id": "eeeeeeee-0000-0000-0000-00000000aaaa", "yes": "1", "back": f"/my/lead/groups/{G}"})
    assert r.headers["location"] == f"/my/lead/groups/{G}?done=said_yes"
    lead.t["group_join_requests"].append({"id": "eeeeeeee-0000-0000-0000-00000000bbbb", "business_id": BIZ, "group_id": G,
                                          "contact_id": ROCHELLE, "status": "waiting", "asked_at": "2026-10-16T12:00:00+00:00"})
    r = _client(monkeypatch, _me(TASHA, "Tasha")).post(
        "/my/groups/answer", data={"id": "eeeeeeee-0000-0000-0000-00000000bbbb", "yes": "0", "back": "https://elsewhere.example"})
    assert r.headers["location"].startswith(f"/my/groups/{G}")


# ── 4. a failed read ─────────────────────────────────────────────────

def test_a_failed_read_says_try_again(lead):
    lead.fail.add("group_meetings")
    html, status = _page(TASHA)
    assert status == 503 and "couldn’t load" in html and "Nothing needs you" not in html


def test_the_lead_tab_is_in_the_bar_for_a_groups_leader(monkeypatch):
    # The whole app (member_portal.serve), as messaging's tests drive it.
    import member_portal as mp
    import church_follow_up as cfu
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import test_member_messaging as tmm
    env = tmm.DB()
    for g in env.t["groups"]:
        g["active"] = True
    import sb_clients
    for name, fn in (("sb_get_as_service", env.get), ("sb_post_as_service", env.post), ("sb_patch_as_service", env.patch)):
        monkeypatch.setattr(sb_clients, name, fn)
    biz = {"id": tmm.BIZ, "name": "First Light Church", "type": "church", "settings": {}, "stripe_account_id": None}
    monkeypatch.setattr(mp, "_church_for_request", lambda req: {"business": biz, "site": {"slug": "first-light"}})
    monkeypatch.setattr(mp, "portal_active", lambda b: True)
    who = {"id": tmm.BEN}
    monkeypatch.setattr(mp, "_session_for", lambda req, church: {
        "claims": {}, "people": [], "me": next(dict(c) for c in env.t["contacts"] if c["id"] == who["id"]), "preview": False})
    monkeypatch.setattr(cfu, "roles_for", lambda b, c: [])
    monkeypatch.setattr(cfu, "is_church", lambda b: True)
    import giving_router
    monkeypatch.setattr(giving_router, "giving_is_active", lambda b: False)
    app = FastAPI()

    @app.get("/my/groups")
    async def _home(request: mp.Request):
        return await mp.serve(request, "/my/groups")
    client = TestClient(app, base_url=f"https://{tmm.HOST}")
    assert 'href="/my/lead"' in client.get("/my/groups").text          # Ben leads a group
    who["id"] = tmm.ANA
    assert 'href="/my/lead"' not in client.get("/my/groups").text      # Ana leads nothing


def test_an_archived_group_isnt_on_the_tab(lead):
    for g in lead.t["groups"]:
        if g["id"] == G:
            g["active"] = False
    assert gl.led_groups(BIZ, TASHA) == []


def test_the_greeting_is_escaped(lead):
    said = gl.hello(BUSINESS, {"name": "<b>Eve</b> Smith"})
    assert "&lt;b&gt;Eve&lt;/b&gt;." in said and "<b>" not in said
