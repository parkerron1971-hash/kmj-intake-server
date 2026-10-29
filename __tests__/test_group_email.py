# __tests__/test_group_email.py
#
# A church group's news by email (group_email.py; Kevin, 2026-10-20,
# decision 4: phone alerts and email for group news). Pins:
#   1. "Email the rest": the group's people with no phone set up for the
#      app, adults with a valid address, never the author; counted on the post
#   2. one failed address never stops the rest; one email per post per person
#   3. the button opens the post in the church's own member app
#   4. the one-hour follow-up: a leader's post an hour old, once, to members
#      who asked and haven't opened it; never too early, never too late
#   5. the leader's form offers it; the leader's card counts it; a member
#      chooses the follow-up on /my/notifications

import asyncio
import pathlib
import sys
from datetime import date, datetime, timedelta, timezone

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import group_email as ge

BIZ = "11111111-1111-1111-1111-111111111111"
G = "aaaaaaaa-0000-0000-0000-000000000001"
POST = "bbbbbbbb-0000-0000-0000-000000000001"
AUTHOR, PHONE, ADULT, TEEN, BAD, UNKNOWN = (f"cccccccc-0000-0000-0000-00000000000{i}" for i in range(1, 7))
BUSINESS = {"id": BIZ, "name": "Love City Church", "settings": {}}
GROUP = {"id": G, "name": "Sisters in the City"}


def _teen_birthdate():
    t = date.today()
    return date(t.year - 15, 1, 1).isoformat()


class SB:
    def __init__(self, **t):
        self.t = {
            "group_members": [{"contact_id": c} for c in (AUTHOR, PHONE, ADULT, TEEN, BAD, UNKNOWN)],
            "member_push_subscriptions": [{"contact_id": PHONE}],
            "contacts": [
                {"id": AUTHOR, "name": "Tasha Williams", "email": "tasha@example.com", "birthdate": "1980-01-01"},
                {"id": PHONE, "name": "Monique Brown", "email": "monique@example.com", "birthdate": "1985-01-01"},
                {"id": ADULT, "name": "Dana Walker", "email": "dana@example.com", "birthdate": "1979-01-01"},
                {"id": TEEN, "name": "Tia Rivers", "email": "tia@example.com", "birthdate": _teen_birthdate()},
                {"id": BAD, "name": "Brenda Thomas", "email": "not-an-email", "birthdate": "1970-01-01"},
                {"id": UNKNOWN, "name": "Gloria Hayes", "email": "gloria@example.com", "birthdate": None},
            ],
            "business_sites": [{"slug": "love-city-church", "site_config": {"custom_domain": "lovecityc.com"}}],
            "group_posts": [{"id": POST, "emailed": 0}],
            **t,
        }
        self.paths, self.patches = [], []

    def sb_get_as_service(self, path):
        self.paths.append(path)
        table = path.lstrip("/").split("?")[0]
        rows = self.t.get(table, [])
        if table == "contacts" and "id=in.(" in path:
            ids = path.split("id=in.(")[1].split(")")[0].split(",")
            rows = [r for r in rows if r["id"] in ids]
        elif table == "contacts" and "id=eq." in path:
            cid = path.split("id=eq.")[1].split("&")[0]
            rows = [r for r in rows if r["id"] == cid]
        return [dict(r) for r in rows]

    def sb_patch_as_service(self, path, body):
        self.patches.append((path, body))
        if path.startswith("/group_posts") and "missed_checked_at=is.null" in path:
            pid = path.split("id=eq.")[1].split("&")[0]
            hit = [p for p in self.t["group_posts"] if p["id"] == pid and not p.get("missed_checked_at")]
            for p in hit:
                p.update(body)
            return [dict(p) for p in hit]
        for p in self.t.get("group_posts", []):
            if p["id"] in path:
                p.update(body)
        return [body]


@pytest.fixture
def sends(monkeypatch):
    import email_sender
    out = []

    async def send_via_resend(**k):
        if k["to_email"] == "boom@example.com":
            raise RuntimeError("Resend 500")
        out.append(k)
        return {"id": "e1"}
    monkeypatch.setattr(email_sender, "send_via_resend", send_via_resend)
    return out


def _use(monkeypatch, sb):
    monkeypatch.setattr(ge, "sb_clients", sb)
    return sb


# ── 1-3. Email the rest ──────────────────────────────────────────────

def test_email_the_rest_reaches_the_people_without_the_app(monkeypatch, sends):
    sb = _use(monkeypatch, SB())
    post = {"id": POST, "title": "Potluck moved", "body": "We'll meet Nov 19 instead. Bring a dish!"}
    n = asyncio.run(ge.email_rest(BUSINESS, GROUP, post, {"id": AUTHOR, "name": "Tasha Williams"}))
    assert n == 2
    assert sorted(s["to_email"] for s in sends) == ["dana@example.com", "gloria@example.com"]   # not the phone, teen, bad, author
    s = sends[0]
    assert s["subject"] == "Sisters in the City: Potluck moved" and s["from_name"] == "Love City Church"
    assert s["idempotency_key"] == f"group-post-{POST}-{ADULT}" and s["business_id"] == BIZ
    assert f"https://lovecityc.com/my/groups/{G}/board" in s["body"] and "Bring a dish!" in s["body"]
    assert "Tasha posted to Sisters in the City" in s["body"]
    assert sb.t["group_posts"][0]["emailed"] == 2                       # the leader sees it counted


def test_one_failed_address_never_stops_the_rest(monkeypatch, sends):
    sb = SB()
    sb.t["contacts"][2]["email"] = "boom@example.com"
    _use(monkeypatch, sb)
    n = asyncio.run(ge.email_rest(BUSINESS, GROUP, {"id": POST, "title": "", "body": "x"}, {"id": AUTHOR, "name": "Tasha"}))
    assert n == 1 and [s["to_email"] for s in sends] == ["gloria@example.com"]
    assert sends[0]["subject"] == "Sisters in the City: a new post from Tasha"


def test_the_button_falls_back_to_the_churchs_own_address(monkeypatch):
    _use(monkeypatch, SB(business_sites=[{"slug": "love-city-church", "site_config": {}}]))
    assert ge.app_url(BIZ) == "https://love-city-church.mysolutionist.app"
    _use(monkeypatch, SB(business_sites=[]))
    assert ge.app_url(BIZ) is None


def test_only_a_known_minor_is_left_out():
    t = date(2026, 10, 20)
    assert ge._adult({"birthdate": None}, t) and ge._adult({"birthdate": "2008-10-20"}, t)   # 18 today
    assert not ge._adult({"birthdate": "2008-10-21"}, t)                                    # 18 tomorrow


# ── 4. the one-hour follow-up ────────────────────────────────────────

def _due_sb(**extra):
    now = datetime(2026, 10, 20, 20, 0, tzinfo=timezone.utc)
    post = {"id": POST, "business_id": BIZ, "group_id": G, "title": "Prayer tonight", "body": "Meet at 8.",
            "posted_by": AUTHOR, "created_at": (now - timedelta(minutes=70)).isoformat(), "emailed": 0}
    sb = SB(group_posts=[post], businesses=[BUSINESS], groups=[GROUP],
            member_push_prefs=[{"contact_id": c} for c in (PHONE, ADULT, AUTHOR, TEEN)],
            group_post_seen=[{"contact_id": ADULT}], **extra)
    return sb, now


def test_the_follow_up_reaches_who_asked_and_hasnt_opened_it(monkeypatch, sends):
    sb, now = _due_sb()
    _use(monkeypatch, sb)
    out = asyncio.run(ge.sweep_tick(now))
    assert out == {"posts": 1, "emails": 1}
    assert [s["to_email"] for s in sends] == ["monique@example.com"]   # asked; Dana opened it; Tia is 15; Tasha wrote it
    assert "asked for an email when your phone misses" in sends[0]["body"]
    q = next(p for p in sb.paths if p.startswith("/group_posts?missed_checked_at=is.null"))
    assert "group_id=not.is.null" in q and "created_at=lte." in q and "created_at=gte." in q
    sends.clear()
    assert asyncio.run(ge.sweep_tick(now)) == {"posts": 0, "emails": 0} and sends == []   # once


def test_the_follow_up_window(monkeypatch, sends):
    sb, now = _due_sb()
    _use(monkeypatch, sb)
    asyncio.run(ge.sweep_tick(now))
    q = next(p for p in sb.paths if p.startswith("/group_posts?missed_checked_at=is.null"))
    from urllib.parse import unquote
    lte = unquote(q.split("created_at=lte.")[1].split("&")[0])
    gte = unquote(q.split("created_at=gte.")[1].split("&")[0])
    assert lte == (now - timedelta(hours=1)).isoformat()             # an hour old, not sooner
    assert gte == (now - timedelta(hours=6)).isoformat()             # and not catching up last week


# ── 5. the forms ─────────────────────────────────────────────────────

def test_the_leaders_form_and_card():
    import member_portal_groups as mpg
    assert 'name="email" value="1"' in mpg._compose({"id": G, "name": "Sisters"})
    card = mpg._post_card({"id": POST, "title": "T", "body": "B", "emailed": 4, "ask_ack": False, "author": {"name": "Tasha W"}},
                          {"id": G, "name_display": "full"}, leader=True, me_id=AUTHOR, size=18, back="/x")
    assert "4 by email" in card


def test_create_post_email_flag(monkeypatch):
    import member_portal_groups as mpg
    import test_member_portal_group_space as gs
    f = gs.Fake()
    for mod in (mpg.sb_clients,):
        monkeypatch.setattr(mod, "sb_get_as_service", f.get)
        monkeypatch.setattr(mod, "sb_post_as_service", f.post)
        monkeypatch.setattr(mod, "sb_patch_as_service", f.patch)
    import member_push
    monkeypatch.setattr(member_push, "tell_group_post", lambda *a, **k: None)
    gs._screen(monkeypatch, "ok")
    spawned = []
    monkeypatch.setattr(ge, "spawn", lambda coro: spawned.append(coro) or coro.close())
    me = gs._me(gs.TASHA, "Tasha")
    assert asyncio.run(mpg.create_post(gs.BUSINESS, me, gs.G, "Quiet", "No email", False, True)) == (True, "post_up")
    assert spawned == [] and not f.t["group_posts"][-1].get("email_rest")
    assert asyncio.run(mpg.create_post(gs.BUSINESS, me, gs.G, "Loud", "Email it", False, True, False, True)) == (True, "post_up")
    assert len(spawned) == 1 and f.t["group_posts"][-1]["email_rest"] is True


def test_the_member_chooses_the_follow_up(monkeypatch):
    import member_push as mp
    from starlette.requests import Request as SR
    monkeypatch.setattr(mp, "ready", lambda: True)
    monkeypatch.setattr(mp, "vapid_public", lambda: "k")
    import member_portal
    monkeypatch.setattr(member_portal, "_shell", lambda biz, site, title, body, **k: body)
    req = SR({"type": "http", "query_string": b"", "headers": []})
    biz = {"id": BIZ, "name": "LCC", "settings": {"member_portal": {"notifications": {"groups": True}}}}
    page = mp.render_page(biz, None, req, {"id": "m"}, set(), {"quiet": True, "after_hours": True, "email_missed": True})
    assert "By email" in page and 'name="q_email" checked' in page and 'name="email_shown"' in page
    biz["settings"]["member_portal"]["notifications"] = {"messages": True}
    assert "By email" not in mp.render_page(biz, None, req, {"id": "m"}, set(), None)
