# __tests__/test_worship_team.py
#
# Who does what in a church's ChurchSavvy (worship_team.py). Pins:
#   * an admin invites someone to a part, by link and (with an email) by
#     email; nobody else can, and a stranger gets 404
#   * the link joins once: the same person again is fine, someone else is
#     refused, a taken-back or month-old link is dead, and joining a church
#     you're already on adds the new parts
#   * each part changes only its own: the booth runs the screens and fixes a
#     typo but never the plan; the worship leader plans but never runs the
#     screens; only an admin sets up screens and the look
#   * a volunteer is never a seat (business_users is never written)
#   * someone taken off the team is a stranger again
#   * the church's starting workspace colors live in the look

import pathlib
import sys
import uuid as uuidlib
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import email_sender
import sb_clients
import worship_router as wr
import worship_show as wsh
import worship_show_router as wsr
import worship_team as wt
from auth_supabase import AuthedUser, require_user

BIZ = "11111111-1111-4111-8111-111111111111"
OWNER_EMAIL = "kmjcreativesolution@gmail.com"
PEOPLE = {name: AuthedUser(id=f"u-{name}", email=f"{name}@lovecity.org", role="authenticated")
          for name in ("owner", "member", "sam", "jo", "ana", "lee", "stranger")}
SEATS = {("u-owner", BIZ): "owner", ("u-member", BIZ): "member"}
SONG_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
# Made-up words: no song's real lyrics in this repo's tests.
SONG = {"id": SONG_ID, "business_id": BIZ, "title": "A Test Song", "song_key": "D", "archived_at": None,
        "lines_per_slide": 2, "public_domain": True,
        "sections": [{"id": "v1", "kind": "verse", "number": 1, "label": "Verse 1",
                      "lines": ["First line of the verse", "Secnd line with a typo", "Third line", "Fourth line"]}],
        "arrangements": [{"id": "main", "name": "Main", "order": ["v1"]}]}


class FakeDb:
    """sb_*_as_service over a few tables, with eq./is.null/in.() filters."""

    KEYS = {"worship_settings": "business_id", "worship_live": "business_id"}

    def __init__(self):
        self.t = {"businesses": [{"id": BIZ, "name": "Love City Church", "owner_id": "u-owner", "is_active": True,
                                  "settings": {"practitioner_name": "Pastor Kevin"}}],
                  "business_users": [], "worship_team": [], "worship_songs": [dict(SONG)], "worship_services": [],
                  "worship_screens": [], "worship_settings": [], "worship_live": []}

    @staticmethod
    def _split(path):
        table, _, q = path.lstrip("/").partition("?")
        return table, [(k, v) for k, v in parse_qsl(q, keep_blank_values=True)
                       if k not in ("select", "order", "limit", "on_conflict")]

    @staticmethod
    def _match(row, filters):
        for k, v in filters:
            if v == "is.null" and row.get(k) is not None:
                return False
            have = str(row.get(k)).lower() if isinstance(row.get(k), bool) else str(row.get(k))
            if v.startswith("eq.") and have != v[3:]:
                return False
            if v.startswith("in.(") and str(row.get(k)) not in v[4:-1].split(","):
                return False
        return True

    def get(self, path, **_):
        table, f = self._split(path)
        return [dict(r) for r in self.t.get(table, []) if self._match(r, f)]

    def post(self, path, body, prefer=None, **_):
        table, _f = self._split(path)
        out = []
        for b in (body if isinstance(body, list) else [body]):
            key = self.KEYS.get(table)
            hit = next((r for r in self.t[table] if key and r.get(key) == b.get(key)), None)
            if hit is not None and "merge-duplicates" in (prefer or ""):
                hit.update(b)
                out.append(dict(hit))
                continue
            row = {"id": str(uuidlib.uuid4()), "archived_at": None, "created_at": "2026-10-20T00:00:00+00:00", **b}
            if table == "worship_team":
                row.setdefault("token", str(uuidlib.uuid4()))
                row.setdefault("user_id", None)
                row.setdefault("joined_at", None)
            self.t[table].append(row)
            out.append(dict(row))
        return None if prefer == "return=minimal" else out

    def patch(self, path, body):
        table, f = self._split(path)
        hit = [r for r in self.t[table] if self._match(r, f)]
        for r in hit:
            r.update(body)
        return [dict(r) for r in hit]


@pytest.fixture
def api(monkeypatch):
    db = FakeDb()
    mail = []
    monkeypatch.setattr(sb_clients, "sb_get_as_service", db.get)
    monkeypatch.setattr(sb_clients, "sb_post_as_service", db.post)
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", db.patch)
    monkeypatch.setenv("PLATFORM_OWNER_EMAIL", OWNER_EMAIL)
    monkeypatch.setenv("WORSHIP_SONGS", "on")
    monkeypatch.setattr(wsr, "HUB", wsr.LiveHub())
    monkeypatch.setattr(wt, "role_of", lambda biz, uid: SEATS.get((uid, biz)))

    async def send(**kw):
        mail.append(kw)
        return {"ok": True}

    monkeypatch.setattr(email_sender, "send_via_resend", send)
    who = {"user": PEOPLE["owner"]}
    app = FastAPI()
    for r in (wt.router, wsr.router, wr.router):
        app.include_router(r)
    app.dependency_overrides[require_user] = lambda: who["user"]
    client = TestClient(app)

    def as_(name):
        who["user"] = PEOPLE[name]
        return client

    return db, as_, mail


def invite(as_, who="owner", **body):
    return as_(who).post("/worship/team/invite", json={"business_id": BIZ, "name": "Sam", "roles": ["booth"], **body})


def join(as_, db, name, roles, email=None):
    r = invite(as_, name=name.title(), roles=roles, email=email)
    assert r.status_code == 200, r.text
    token = r.json()["link"].split("t=")[1]
    assert as_(name).post("/worship/team/accept", json={"token": token}).status_code == 200
    return r.json()["member"]["id"], token


def test_an_admin_invites_by_link_and_email(api):
    db, as_, mail = api
    r = invite(as_, name="Sam", email="Sam@Example.org", roles=["booth", "worship"])
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["link"].startswith("https://") and "/churchsavvy/join?t=" in j["link"]
    assert j["emailed"] is True and mail[0]["to_email"] == "sam@example.org"
    assert j["link"] in mail[0]["body"] and "Love City Church" in mail[0]["subject"]
    # Parts come back in their own order, whatever order they were sent in.
    assert j["member"]["roles"] == ["worship", "booth"] and j["member"]["status"] == "invited"
    team = as_("owner").get(f"/worship/team?business_id={BIZ}").json()
    assert [m["name"] for m in team["team"]] == ["Sam"] and team["team"][0]["link"] == j["link"]
    assert team["staff"][0] == {"name": "Pastor Kevin", "kind": "owner", "you": True}
    # Without an email: a link to send any way they like.
    r2 = invite(as_, name="Jo", roles=["planner"])
    assert r2.status_code == 200 and r2.json()["emailed"] is False and len(mail) == 1
    # The same email twice is refused; a volunteer never becomes a seat.
    assert invite(as_, name="Sam", email="sam@example.org").status_code == 409
    assert db.t["business_users"] == []


def test_only_an_admin_invites(api):
    db, as_, _ = api
    assert invite(as_, "member").status_code == 403
    assert invite(as_, "stranger").status_code == 404
    assert as_("member").get(f"/worship/team?business_id={BIZ}").status_code == 403
    assert invite(as_, roles=[]).status_code == 400
    assert invite(as_, roles=["pastor"]).status_code == 400
    assert invite(as_, name="  ").status_code == 400
    assert invite(as_, email="not an email").status_code == 400
    # A booth volunteer can't add to the team either.
    join(as_, db, "sam", ["booth"])
    assert invite(as_, "sam", name="Lee").status_code == 403


def test_the_link_joins_once(api):
    db, as_, _ = api
    r = invite(as_, name="Sam", roles=["booth"])
    token = r.json()["link"].split("t=")[1]
    j = as_("sam").post("/worship/team/accept", json={"token": token})
    assert j.status_code == 200 and j.json() == {"business_id": BIZ, "church": "Love City Church", "roles": ["booth"]}
    assert as_("sam").post("/worship/team/accept", json={"token": token}).status_code == 200
    assert as_("jo").post("/worship/team/accept", json={"token": token}).status_code == 409
    assert as_("sam").get("/worship/team/mine").json() == {
        "churches": [{"business_id": BIZ, "name": "Love City Church", "roles": ["booth"]}]}
    assert as_("jo").get("/worship/team/mine").json() == {"churches": []}
    # A second invite for the same person adds its parts to the ones they have.
    r2 = invite(as_, name="Sam again", roles=["worship"])
    t2 = r2.json()["link"].split("t=")[1]
    assert as_("sam").post("/worship/team/accept", json={"token": t2}).json()["roles"] == ["worship", "booth"]
    active = [m for m in db.t["worship_team"] if m["status"] == "active"]
    assert len(active) == 1 and active[0]["roles"] == ["worship", "booth"]


def test_the_link_says_whose_team_before_sign_in(api):
    db, as_, _ = api
    r = invite(as_, name="Sam", email="sam@example.org", roles=["booth"])
    token = r.json()["link"].split("t=")[1]
    info = as_("stranger").get(f"/worship/team/invite?t={token}")
    assert info.json() == {"church": "Love City Church", "name": "Sam", "email": "sam@example.org", "roles": ["booth"]}
    as_("sam").post("/worship/team/accept", json={"token": token})
    assert as_("stranger").get(f"/worship/team/invite?t={token}").status_code == 409
    assert as_("stranger").get(f"/worship/team/invite?t={uuidlib.uuid4()}").status_code == 410


def test_a_dead_link_says_so(api):
    db, as_, _ = api
    r = invite(as_, name="Sam")
    member, token = r.json()["member"]["id"], r.json()["link"].split("t=")[1]
    for row in db.t["worship_team"]:
        row["invited_at"] = (datetime.now(timezone.utc) - timedelta(days=40)).isoformat()
    assert as_("sam").post("/worship/team/accept", json={"token": token}).status_code == 410
    assert as_("owner").delete(f"/worship/team/{member}?business_id={BIZ}").status_code == 200
    gone = as_("sam").post("/worship/team/accept", json={"token": token})
    assert gone.status_code == 410 and "taken back" in gone.json()["detail"]
    assert as_("sam").post("/worship/team/accept", json={"token": str(uuidlib.uuid4())}).status_code == 410
    assert as_("sam").post("/worship/team/accept", json={"token": "nope"}).status_code == 400


def test_an_expired_invite_says_so_and_gets_a_new_link(api):
    db, as_, mail = api
    r = invite(as_, name="Sam", email="sam@example.org")
    member, old = r.json()["member"]["id"], r.json()["link"].split("t=")[1]
    for row in db.t["worship_team"]:
        row["invited_at"] = (datetime.now(timezone.utc) - timedelta(days=40)).isoformat()
    shown = as_("owner").get(f"/worship/team?business_id={BIZ}").json()["team"][0]
    assert shown["expired"] is True and "link" not in shown
    # Inviting the same email again isn't refused by a dead invite.
    assert invite(as_, name="Sam", email="sam@example.org").status_code == 200
    fresh = as_("owner").post(f"/worship/team/{member}/new-link", json={"business_id": BIZ})
    assert fresh.status_code == 200 and fresh.json()["member"]["expired"] is False
    token = fresh.json()["link"].split("t=")[1]
    assert token != old and mail[-1]["body"].count(token) == 1
    assert as_("sam").post("/worship/team/accept", json={"token": old}).status_code == 410
    assert as_("sam").post("/worship/team/accept", json={"token": token}).status_code == 200
    assert as_("owner").post(f"/worship/team/{member}/new-link", json={"business_id": BIZ}).status_code == 409
    assert as_("sam").post(f"/worship/team/{member}/new-link", json={"business_id": BIZ}).status_code == 403


def test_a_second_accept_that_lost_the_race_still_joins(api, monkeypatch):
    db, as_, _ = api
    token = invite(as_, name="Sam").json()["link"].split("t=")[1]
    real = db.patch

    def other_tab_won(path, body):
        # The other tab's accept lands first; this one's conditional write then matches nothing.
        if body.get("status") == "active":
            for r in db.t["worship_team"]:
                if r["token"] == token:
                    r.update(body)
            return []
        return real(path, body)

    monkeypatch.setattr(sb_clients, "sb_patch_as_service", other_tab_won)
    r = as_("sam").post("/worship/team/accept", json={"token": token})
    assert r.status_code == 200 and r.json()["roles"] == ["booth"]


def _service(as_, who="owner"):
    return as_(who).post("/worship/services", json={
        "business_id": BIZ, "title": "Sunday", "starts_at": "2026-10-25T15:05:00Z",
        "items": [{"id": "s1", "kind": "song", "song_id": SONG_ID}]})


def test_each_part_changes_only_its_own(api):
    db, as_, _ = api
    join(as_, db, "sam", ["booth"])
    join(as_, db, "jo", ["worship"])
    join(as_, db, "ana", ["planner"])
    join(as_, db, "lee", ["admin"])
    sid = _service(as_).json()["service"]["id"]
    live = {"business_id": BIZ, "state": {"service_id": sid, "item_id": "s1", "slide": 0}}

    # Booth: reads everything, runs the screens, never the plan or the setup.
    booth = as_("sam")
    assert booth.get(f"/worship/services?business_id={BIZ}").json()["can"] == {
        "plan": False, "songs": False, "media": False, "fix": True, "run": True, "setup": False,
        "live": True, "clips": False, "sermons": False}
    assert booth.get(f"/worship/services/{sid}/show?business_id={BIZ}").status_code == 200
    assert booth.post("/worship/live", json=live).status_code == 200
    refused = booth.put(f"/worship/services/{sid}", json={"business_id": BIZ, "title": "Mine now"})
    assert refused.status_code == 403 and "doesn't change the plan" in refused.json()["detail"]
    assert _service(as_, "sam").status_code == 403
    assert booth.put("/worship/look", json={"business_id": BIZ, "look": {}}).status_code == 403
    assert booth.post("/worship/screens", json={"business_id": BIZ, "name": "Mine"}).status_code == 403
    assert booth.post("/worship/songs", json={"business_id": BIZ, "title": "Mine"}).status_code == 403
    # Screen links are for the setup only.
    as_("owner").post("/worship/screens", json={"business_id": BIZ, "name": "Projector"})
    assert "token" not in as_("sam").get(f"/worship/screens?business_id={BIZ}").json()["screens"][0]

    # Worship leader: the plan and the songs, never the screens.
    lead = as_("jo")
    assert lead.put(f"/worship/services/{sid}", json={"business_id": BIZ, "title": "Sunday, with the band"}).status_code == 200
    assert lead.post("/worship/songs", json={"business_id": BIZ, "title": "Another Test Song"}).status_code == 200
    no_run = lead.post("/worship/live", json=live)
    assert no_run.status_code == 403 and "doesn't run the screens" in no_run.json()["detail"]

    # Planner: plans and runs, never the setup.
    plan = as_("ana")
    assert _service(as_, "ana").status_code == 200
    assert plan.post("/worship/live", json=live).status_code == 200
    assert plan.post("/worship/screens", json={"business_id": BIZ, "name": "Side"}).status_code == 403

    # An invited admin: the setup too, and the screen links.
    admin = as_("lee")
    assert admin.post("/worship/screens", json={"business_id": BIZ, "name": "Side"}).status_code == 200
    assert "token" in admin.get(f"/worship/screens?business_id={BIZ}").json()["screens"][0]
    assert admin.get(f"/worship/team?business_id={BIZ}").status_code == 200

    # A member seat reads and changes nothing; a stranger doesn't see the church.
    assert as_("member").get(f"/worship/services?business_id={BIZ}").json()["can"]["run"] is False
    assert as_("member").post("/worship/live", json=live).status_code == 403
    assert as_("stranger").get(f"/worship/services?business_id={BIZ}").status_code == 404


def test_changing_parts_and_taking_someone_off(api):
    db, as_, _ = api
    member, _t = join(as_, db, "sam", ["booth"])
    assert as_("sam").get(f"/worship/status?business_id={BIZ}").json()["roles"] == ["booth"]
    r = as_("owner").put(f"/worship/team/{member}", json={"business_id": BIZ, "roles": ["planner", "booth"]})
    assert r.status_code == 200 and r.json()["member"]["roles"] == ["planner", "booth"]
    assert _service(as_, "sam").status_code == 200
    assert as_("owner").put(f"/worship/team/{member}", json={"business_id": BIZ, "roles": []}).status_code == 400
    assert as_("sam").put(f"/worship/team/{member}", json={"business_id": BIZ, "roles": ["admin"]}).status_code == 403
    assert as_("owner").delete(f"/worship/team/{member}?business_id={BIZ}").status_code == 200
    assert as_("sam").get(f"/worship/services?business_id={BIZ}").status_code == 404
    assert as_("sam").get("/worship/team/mine").json() == {"churches": []}
    assert as_("owner").delete(f"/worship/team/{member}?business_id={BIZ}").status_code == 404


def test_the_booth_fixes_a_typo_in_the_song(api):
    db, as_, _ = api
    join(as_, db, "sam", ["booth"])
    fix = {"business_id": BIZ, "section_id": "v1", "old": ["First line of the verse", "Secnd line with a typo"],
           "new": ["First line of the verse", "Second line, fixed"]}
    r = as_("sam").post(f"/worship/songs/{SONG_ID}/fix", json=fix)
    assert r.status_code == 200, r.text
    assert db.t["worship_songs"][0]["sections"][0]["lines"] == [
        "First line of the verse", "Second line, fixed", "Third line", "Fourth line"]
    # The words moved on since the slide went up: say so, change nothing.
    again = as_("sam").post(f"/worship/songs/{SONG_ID}/fix", json=fix)
    assert again.status_code == 409 and "changed" in again.json()["detail"]
    # The same number of lines, never empty, and only for someone on the team with a part.
    assert as_("sam").post(f"/worship/songs/{SONG_ID}/fix", json={**fix, "old": ["Third line"], "new": ["a", "b"]}).status_code == 400
    assert as_("sam").post(f"/worship/songs/{SONG_ID}/fix", json={**fix, "old": ["Third line"], "new": [" "]}).status_code == 400
    assert as_("member").post(f"/worship/songs/{SONG_ID}/fix",
                              json={**fix, "old": ["Third line"], "new": ["Third line!"]}).status_code == 403
    # A blank line would start a new slide mid-service.
    assert as_("sam").post(f"/worship/songs/{SONG_ID}/fix", json={**fix, "old": ["Third line", "Fourth line"], "new": ["Third", ""]}).status_code == 400
    # Fixing is all the booth may do to the library.
    assert as_("sam").put(f"/worship/songs/{SONG_ID}", json={"business_id": BIZ, "title": "Renamed"}).status_code == 403


def test_workspace_colors_live_in_the_look():
    assert wsh.clean_look({})["workspace"] == "dark"
    assert wsh.clean_look({"workspace": "split"})["workspace"] == "split"
    with pytest.raises(ValueError):
        wsh.clean_look({"workspace": "blue"})


def test_the_switch_off_closes_joining(api, monkeypatch):
    db, as_, _ = api
    r = invite(as_, name="Sam")
    token = r.json()["link"].split("t=")[1]
    monkeypatch.setenv("WORSHIP_SONGS", "off")
    assert as_("sam").post("/worship/team/accept", json={"token": token}).status_code == 404
    assert as_("sam").get("/worship/team/mine").json() == {"churches": []}
    assert invite(as_, name="Jo").status_code == 404



def test_a_fix_lands_on_the_slide_it_names(api):
    db, as_, _ = api
    join(as_, db, "sam", ["booth"])
    db.t["worship_songs"][0]["sections"][0]["lines"] = ["Same line here", "And again", "Same line here", "And again"]
    two = {"business_id": BIZ, "section_id": "v1", "old": ["Same line here", "And again"], "new": ["Same line here", "And AGAIN"], "start": 2}
    assert as_("sam").post(f"/worship/songs/{SONG_ID}/fix", json=two).status_code == 200
    assert db.t["worship_songs"][0]["sections"][0]["lines"] == ["Same line here", "And again", "Same line here", "And AGAIN"]
    # The slide moved on since it went up: refused, nothing changed.
    assert as_("sam").post(f"/worship/songs/{SONG_ID}/fix", json={**two, "start": 1}).status_code == 409


def test_each_song_slide_knows_where_it_starts():
    import worship_lyrics as wl
    song = {"sections": [{"id": "v1", "label": "Verse 1", "lines": ["a", "b", "c", "", "d", "e"]}]}
    assert [(s["lines"], s["start"]) for s in wl.slides_for_song(song, ["v1", "v1"], 2)] == [
        (["a", "b"], 0), (["c"], 2), (["d", "e"], 4), (["a", "b"], 0), (["c"], 2), (["d", "e"], 4)]
