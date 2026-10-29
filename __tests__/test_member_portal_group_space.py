# __tests__/test_member_portal_group_space.py
#
# A group's own page in the member app (member_portal_groups.py, Kevin
# 2026-10-20: "there is no area where people can communicate like a chat.
# recieve announcements from group leader"). Pins:
#   1. names: people in a group see FULL names unless the group's leader
#      chose first names; a teen always shows by first name; the office's
#      contact details never reach the page
#   2. who sees what: a member sees the Board and who's in it; someone
#      outside sees what the group is and who leads it, never the people in
#      it; an invite-only group is "not here" to an outsider
#   3. joining goes the group's way: open = in now, ask = a waiting request
#      the leaders hear about, invite = refused; asking twice is one request
#   4. only a leader of THAT group answers a request; yes puts them in and
#      tells them; an answered request can't be answered again
#   5. the Board: only the group's leaders post, after the message check;
#      a refused or unchecked post never goes up; one pin per group; the
#      alert carries the title, never the words
#   6. "Got it" is for people in the group, and is saved with a write that
#      reports success (return=representation); a leader sees seen counts,
#      a member doesn't
#   7. routes: no session → sign in; the preview never writes; a "back"
#      field can't send anyone off the group pages
#   8. a failed read is "try again", never an empty group

import asyncio
import pathlib
import sys
import urllib.parse
from datetime import date

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import member_portal_church as mpc
import member_portal_groups as mpg

BIZ = "11111111-1111-1111-1111-111111111111"
OTHER = "22222222-2222-2222-2222-222222222222"
G = "aaaaaaaa-0000-0000-0000-000000000001"          # Sisters in the City (ask)
G_OPEN = "aaaaaaaa-0000-0000-0000-000000000002"     # open
G_INVITE = "aaaaaaaa-0000-0000-0000-000000000003"   # invite only
G_THEIRS = "aaaaaaaa-0000-0000-0000-000000000004"   # another church's
TASHA = "cccccccc-0000-0000-0000-000000000001"      # leads G
MONIQUE = "cccccccc-0000-0000-0000-000000000002"    # in G
TEEN = "cccccccc-0000-0000-0000-000000000003"       # in G, 15
ROCHELLE = "cccccccc-0000-0000-0000-000000000004"   # outside
POST1 = "dddddddd-0000-0000-0000-000000000001"

ADULT = f"{date.today().year - 40}-01-01"
KID = f"{date.today().year - 15}-01-01"


def _params(path):
    table, _, qs = path.lstrip("/").partition("?")
    return table, urllib.parse.parse_qsl(qs, keep_blank_values=True)


def _cond(row, key, expr):
    op, _, val = expr.partition(".")
    cur = row.get(key)
    if op == "eq":
        return str(cur).lower() == val.lower() if cur is not None else val == "None"
    if op == "neq":
        return str(cur).lower() != val.lower()
    if op == "is":
        return cur is None if val == "null" else str(cur).lower() == val
    if op == "in":
        return str(cur) in val.strip("()").split(",")
    if op in ("lt", "lte", "gt", "gte"):
        if cur is None:
            return False
        c, v = str(cur), val
        return {"lt": c < v, "lte": c <= v, "gt": c > v, "gte": c >= v}[op]
    return True


class Fake:
    def __init__(self):
        def g(gid, name, mode, biz=BIZ, **k):
            return {"id": gid, "business_id": biz, "name": name, "kind": "small_group", "description": "",
                    "meets": "Thursdays · 7 PM", "location": "Renée's home", "capacity": None, "open_to_join": mode != "invite",
                    "join_mode": mode, "name_display": "full", "youth": False, "active": True, "updated_at": "x", **k}
        self.t = {
            "groups": [g(G, "Sisters in the City", "ask"), g(G_OPEN, "Prayer Warriors", "open"),
                       g(G_INVITE, "Ministers Alliance", "invite"), g(G_THEIRS, "Theirs", "open", OTHER)],
            "group_members": [
                {"group_id": G, "contact_id": TASHA, "business_id": BIZ, "role": "leader", "joined_on": "2023-01-05",
                 "can_host_live": False},
                {"group_id": G, "contact_id": MONIQUE, "business_id": BIZ, "role": "member", "joined_on": "2024-02-01",
                 "can_host_live": False},
                {"group_id": G, "contact_id": TEEN, "business_id": BIZ, "role": "member", "joined_on": "2025-03-01",
                 "can_host_live": False},
            ],
            "contacts": [
                {"id": TASHA, "business_id": BIZ, "name": "Tasha Williams", "birthdate": ADULT, "metadata": {},
                 "email": "tasha@example.com", "phone": "555-0101", "status": "active", "created_at": "2021-01-01"},
                {"id": MONIQUE, "business_id": BIZ, "name": "Monique Brown", "birthdate": ADULT, "metadata": {},
                 "email": "monique@example.com", "phone": "555-0102", "status": "active", "created_at": "2022-01-01"},
                {"id": TEEN, "business_id": BIZ, "name": "Kayla Young", "birthdate": KID, "metadata": {},
                 "status": "active", "created_at": "2024-01-01"},
                {"id": ROCHELLE, "business_id": BIZ, "name": "Rochelle Taylor", "birthdate": ADULT, "metadata": {},
                 "status": "lead", "created_at": "2026-09-01"},
            ],
            "group_join_requests": [],
            "group_posts": [],
            "group_post_seen": [],
            "group_live_sessions": [],
        }
        self.fail = set()
        self.writes = []
        self._n = 0

    def _rows(self, table, params):
        out = []
        for r in self.t.get(table, []):
            ok = True
            for k, v in params:
                if k in ("select", "order", "limit", "on_conflict"):
                    continue
                if k == "or":
                    parts = v.strip("()").split(",")
                    if not any(_cond(r, p.split(".", 1)[0], p.split(".", 1)[1]) for p in parts):
                        ok = False
                    continue
                if not _cond(r, k, v):
                    ok = False
            if ok:
                out.append(r)
        return out

    def get(self, path, **kw):
        table, params = _params(path)
        if table in self.fail:
            return None
        return [dict(r) for r in self._rows(table, params)]

    def post(self, path, body, prefer=None, **kw):
        table, params = _params(path)
        if table in self.fail:
            return None
        self.writes.append(("post", table, body, prefer))
        rows = body if isinstance(body, list) else [body]
        out = []
        for b in rows:
            b = dict(b)
            if table == "group_join_requests" and any(
                    r["group_id"] == b["group_id"] and r["contact_id"] == b["contact_id"] and r["status"] == "waiting"
                    for r in self.t[table]):
                return None  # the one-waiting index
            if table == "group_post_seen":
                cur = next((r for r in self.t[table] if r["post_id"] == b["post_id"] and r["contact_id"] == b["contact_id"]), None)
                if cur:
                    if "merge-duplicates" in (prefer or ""):
                        cur.update(b)
                    out.append(cur)
                    continue
            if table == "group_members" and any(
                    m["group_id"] == b["group_id"] and m["contact_id"] == b["contact_id"] for m in self.t[table]):
                continue
            self._n += 1
            b.setdefault("id", f"eeeeeeee-0000-0000-0000-{self._n:012d}")
            b.setdefault("created_at", f"2026-10-20T1{self._n % 10}:00:00+00:00")
            if table == "group_join_requests":
                b.setdefault("status", "waiting")
                b.setdefault("asked_at", "2026-10-19T12:00:00+00:00")
            if table == "group_posts":
                b.setdefault("removed_at", None)
            self.t.setdefault(table, []).append(b)
            out.append(b)
        # A minimal write hands back nothing, like PostgREST.
        return None if "return=minimal" in (prefer or "return=representation") else out

    def patch(self, path, body, **kw):
        table, params = _params(path)
        if table in self.fail:
            return None
        self.writes.append(("patch", table, body, path))
        hit = self._rows(table, params)
        for r in hit:
            r.update(body)
        return [dict(r) for r in hit]


@pytest.fixture
def fake(monkeypatch):
    f = Fake()
    for mod in (mpg.sb_clients, mpc.sb_clients):
        monkeypatch.setattr(mod, "sb_get_as_service", f.get)
        monkeypatch.setattr(mod, "sb_post_as_service", f.post)
        monkeypatch.setattr(mod, "sb_patch_as_service", f.patch)
    told = []
    import member_push
    monkeypatch.setattr(member_push, "tell_join_request", lambda biz, g, me: told.append(("ask", g["id"], me["id"])))
    monkeypatch.setattr(member_push, "tell_join_yes", lambda biz, gid, cid: told.append(("yes", gid, cid)))
    f.rang = []
    monkeypatch.setattr(member_push, "tell_group_post",
                        lambda biz, g, pid, me, title, ring=False: told.append(("post", g["id"], pid, title))
                        or f.rang.append(ring))
    import member_portal_group_live as mgl
    monkeypatch.setattr(mgl, "open_sessions", lambda *a: {})
    f.told = told
    return f


def _me(cid, name):
    return {"id": cid, "name": name}


BUSINESS = {"id": BIZ, "name": "Love City Church", "settings": {}}


# ── 1. names ─────────────────────────────────────────────────────────

def test_full_names_by_default_first_names_by_the_leaders_choice():
    adult = {"name": "Monique Brown", "birthdate": ADULT}
    assert mpg.display_name(adult, "full") == "Monique Brown"
    assert mpg.display_name(adult, "first") == "Monique"


def test_a_teen_always_shows_by_first_name():
    assert mpg.display_name({"name": "Kayla Young", "birthdate": KID}, "full") == "Kayla"


def test_people_tab_shows_full_names_and_no_contact_details(fake):
    data = mpg.space(BIZ, G, _me(MONIQUE, "Monique Brown"), tab="people")
    html, status = mpg.render(BUSINESS, None, _req(), _me(MONIQUE, "Monique Brown"), data, "people")
    assert status == 200
    assert "Tasha Williams" in html and "Monique Brown" in html
    assert "Kayla" in html and "Kayla Young" not in html
    assert ">KY<" not in html  # her initials don't give her last name away either
    assert "tasha@example.com" not in html and "555-0101" not in html


def test_people_tab_in_first_name_mode(fake):
    fake.t["groups"][0]["name_display"] = "first"
    data = mpg.space(BIZ, G, _me(MONIQUE, "Monique Brown"), tab="people")
    html, _ = mpg.render(BUSINESS, None, _req(), _me(MONIQUE, "Monique Brown"), data, "people")
    assert "Tasha" in html and "Tasha Williams" not in html and "Monique Brown" not in html


def test_only_a_leader_of_the_group_changes_the_names(fake):
    assert mpg.set_names(BIZ, _me(MONIQUE, "Monique"), G, "first") == (False, "not_group_leader")
    assert fake.t["groups"][0]["name_display"] == "full"
    assert mpg.set_names(BIZ, _me(TASHA, "Tasha"), G, "first") == (True, "names_first")
    assert fake.t["groups"][0]["name_display"] == "first"
    assert mpg.set_names(BIZ, _me(TASHA, "Tasha"), G, "everyone") == (False, "error")


# ── 2. who sees what ─────────────────────────────────────────────────

def test_an_outsider_sees_the_group_and_its_leaders_never_its_people(fake):
    me = _me(ROCHELLE, "Rochelle Taylor")
    data = mpg.space(BIZ, G, me)
    assert data["role"] is None and "posts" not in data
    html, status = mpg.render(BUSINESS, None, _req(), me, data)
    assert status == 200 and "Ask to join" in html and "Tasha" in html
    assert "Monique" not in html and "Kayla" not in html


def test_an_invite_only_group_is_not_here_for_an_outsider(fake):
    assert mpg.space(BIZ, G_INVITE, _me(ROCHELLE, "Rochelle")) == {}
    html, status = mpg.render(BUSINESS, None, _req(), _me(ROCHELLE, "Rochelle"), {}, "")
    assert status == 404


def test_another_churchs_group_is_not_here(fake):
    assert mpg.space(BIZ, G_THEIRS, _me(ROCHELLE, "Rochelle")) == {}


# ── 3. joining ───────────────────────────────────────────────────────

def test_open_group_joins_right_away(fake):
    assert mpg.ask(BUSINESS, _me(ROCHELLE, "Rochelle"), G_OPEN) == (True, "joined")
    assert any(m["group_id"] == G_OPEN and m["contact_id"] == ROCHELLE and m["role"] == "member"
               for m in fake.t["group_members"])


def test_asking_makes_one_waiting_request_and_tells_the_leaders(fake):
    me = _me(ROCHELLE, "Rochelle Taylor")
    assert mpg.ask(BUSINESS, me, G) == (True, "asked")
    assert mpg.ask(BUSINESS, me, G) == (True, "asked")
    waiting = [r for r in fake.t["group_join_requests"] if r["status"] == "waiting"]
    assert len(waiting) == 1 and waiting[0]["contact_id"] == ROCHELLE
    assert not any(m["contact_id"] == ROCHELLE for m in fake.t["group_members"])  # not in yet
    assert fake.told == [("ask", G, ROCHELLE)]


def test_invite_only_refuses_asking(fake):
    assert mpg.ask(BUSINESS, _me(ROCHELLE, "Rochelle"), G_INVITE) == (False, "group_invite")
    assert fake.t["group_join_requests"] == []


def test_a_full_group_refuses_asking(fake):
    fake.t["groups"][0]["capacity"] = 3
    assert mpg.ask(BUSINESS, _me(ROCHELLE, "Rochelle"), G) == (False, "group_full")


def test_member_join_points_an_ask_group_to_its_page(fake):
    assert mpc.member_join(BIZ, _me(ROCHELLE, "Rochelle"), G) == (False, "group_ask")


def test_withdraw_takes_back_only_my_request(fake):
    mpg.ask(BUSINESS, _me(ROCHELLE, "Rochelle"), G)
    assert mpg.withdraw(BIZ, _me(ROCHELLE, "Rochelle"), G) == (True, "withdrawn")
    assert fake.t["group_join_requests"][0]["status"] == "withdrawn"


# ── 4. answering ─────────────────────────────────────────────────────

def _asked(fake):
    mpg.ask(BUSINESS, _me(ROCHELLE, "Rochelle Taylor"), G)
    return fake.t["group_join_requests"][0]["id"]


def test_only_a_leader_of_the_group_answers(fake):
    rid = _asked(fake)
    assert mpg.answer(BUSINESS, _me(MONIQUE, "Monique"), rid, True)[:2] == (False, "not_group_leader")
    assert fake.t["group_join_requests"][0]["status"] == "waiting"


def test_yes_puts_them_in_and_tells_them(fake):
    rid = _asked(fake)
    assert mpg.answer(BUSINESS, _me(TASHA, "Tasha"), rid, True) == (True, "said_yes", G)
    r = fake.t["group_join_requests"][0]
    assert r["status"] == "yes" and r["decided_by"] == TASHA
    assert any(m["group_id"] == G and m["contact_id"] == ROCHELLE and m["role"] == "member"
               for m in fake.t["group_members"])
    assert ("yes", G, ROCHELLE) in fake.told
    # …and it can't be answered twice.
    assert mpg.answer(BUSINESS, _me(TASHA, "Tasha"), rid, False)[:2] == (False, "answered")


def test_not_now_leaves_them_out(fake):
    rid = _asked(fake)
    assert mpg.answer(BUSINESS, _me(TASHA, "Tasha"), rid, False) == (True, "not_now", G)
    assert not any(m["contact_id"] == ROCHELLE for m in fake.t["group_members"])


def test_a_leader_sees_who_is_asking(fake):
    _asked(fake)
    data = mpg.space(BIZ, G, _me(TASHA, "Tasha Williams"))
    html, _ = mpg.render(BUSINESS, None, _req(), _me(TASHA, "Tasha Williams"), data)
    assert "Asking to join" in html and "Rochelle Taylor" in html and "Say yes" in html
    member_html, _ = mpg.render(BUSINESS, None, _req(), _me(MONIQUE, "Monique"),
                                mpg.space(BIZ, G, _me(MONIQUE, "Monique")))
    assert "Asking to join" not in member_html and "Rochelle" not in member_html


# ── 5. the Board ─────────────────────────────────────────────────────

def _screen(monkeypatch, verdict):
    import msg_screen

    async def screen(biz, text):
        if verdict == "down":
            raise msg_screen.ScreenUnavailable("down")
        return verdict
    monkeypatch.setattr(msg_screen, "screen", screen)


def _post(me, **k):
    return asyncio.run(mpg.create_post(BUSINESS, me, G, k.get("title", "No gathering Thanksgiving week"),
                                       k.get("body", "Potluck on Nov 19 instead."), k.get("pin", False), True))


def test_only_the_groups_leaders_post(fake, monkeypatch):
    _screen(monkeypatch, "ok")
    assert _post(_me(MONIQUE, "Monique")) == (False, "not_group_leader")
    assert fake.t["group_posts"] == []


@pytest.mark.parametrize("verdict,code", [("harm", "post_no"), ("self_harm", "post_no"), ("down", "post_busy")])
def test_a_refused_or_unchecked_post_never_goes_up(fake, monkeypatch, verdict, code):
    _screen(monkeypatch, verdict)
    assert _post(_me(TASHA, "Tasha")) == (False, code)
    assert fake.t["group_posts"] == [] and not any(t[0] == "post" for t in fake.told)


def test_a_post_goes_up_and_the_alert_carries_the_title_only(fake, monkeypatch):
    _screen(monkeypatch, "ok")
    assert _post(_me(TASHA, "Tasha Williams")) == (True, "post_up")
    p = fake.t["group_posts"][0]
    assert p["group_id"] == G and p["posted_by"] == TASHA and p["ask_ack"] is True
    kind, gid, pid, title = fake.told[-1]
    assert (kind, gid, title) == ("post", G, "No gathering Thanksgiving week")


def test_one_pin_per_group(fake, monkeypatch):
    _screen(monkeypatch, "ok")
    _post(_me(TASHA, "Tasha"), title="First", pin=True)
    _post(_me(TASHA, "Tasha"), title="Second", pin=True)
    pinned = [p["title"] for p in fake.t["group_posts"] if p["pinned"]]
    assert pinned == ["Second"]


def test_only_the_author_or_a_leader_takes_a_post_down(fake, monkeypatch):
    _screen(monkeypatch, "ok")
    _post(_me(TASHA, "Tasha"))
    pid = fake.t["group_posts"][0]["id"]
    assert mpg.remove_post(BIZ, _me(MONIQUE, "Monique"), pid)[:2] == (False, "not_group_leader")
    assert mpg.remove_post(BIZ, _me(TASHA, "Tasha"), pid) == (True, "post_down", G)
    assert fake.t["group_posts"][0]["removed_at"]


# ── 6. "Got it" and seen ─────────────────────────────────────────────

def _one_post(fake):
    fake.t["group_posts"].append({"id": POST1, "business_id": BIZ, "group_id": G, "title": "Hello", "body": "Body words",
                                  "pinned": True, "ask_ack": True, "posted_by": TASHA,
                                  "created_at": "2026-10-19T18:00:00+00:00", "removed_at": None})


def test_got_it_is_for_people_in_the_group(fake):
    _one_post(fake)
    assert mpg.ack(BIZ, _me(ROCHELLE, "Rochelle"), POST1)[:2] == (False, "not_in_group")
    assert mpg.ack(BIZ, _me(MONIQUE, "Monique"), POST1) == (True, "got_it", G)
    row = fake.t["group_post_seen"][0]
    assert row["contact_id"] == MONIQUE and row["acked_at"]
    # A write that reports success: return=minimal hands back nothing.
    assert "return=representation" in next(w[3] for w in fake.writes if w[1] == "group_post_seen")


def test_a_leader_sees_seen_counts_a_member_does_not(fake):
    _one_post(fake)
    mpg.ack(BIZ, _me(MONIQUE, "Monique"), POST1)
    lead = mpg.space(BIZ, G, _me(TASHA, "Tasha"), tab="board")
    html, _ = mpg.render(BUSINESS, None, _req(), _me(TASHA, "Tasha"), lead, "board")
    assert "Seen by 1 of 3" in html and "1 said got it" in html
    assert 'class="gs-ack" type="submit"' not in html  # nobody says "Got it" to their own post
    mem = mpg.space(BIZ, G, _me(MONIQUE, "Monique"), tab="board")
    html, _ = mpg.render(BUSINESS, None, _req(), _me(MONIQUE, "Monique"), mem, "board")
    assert "Seen by" not in html and "You saw this" in html


def test_a_member_who_hasnt_said_got_it_gets_the_button(fake):
    _one_post(fake)
    data = mpg.space(BIZ, G, _me(TEEN, "Kayla Young"))
    html, _ = mpg.render(BUSINESS, None, _req(), _me(TEEN, "Kayla Young"), data)
    assert "Got it" in html and "Body words" in html


# ── 7. routes ────────────────────────────────────────────────────────

def _req(qs=b""):
    from starlette.requests import Request
    return Request({"type": "http", "query_string": qs, "headers": []})


def _client(monkeypatch, me, unavailable=False):
    async def signed_in(request):
        return {"business": BUSINESS}, me, unavailable
    monkeypatch.setattr(mpc, "_signed_in", signed_in)
    monkeypatch.setattr(mpc, "_allowed", lambda church, who: True)
    app = FastAPI()
    app.include_router(mpg.router)
    return TestClient(app, follow_redirects=False)


def test_route_without_a_session_goes_to_sign_in(fake, monkeypatch):
    r = _client(monkeypatch, None).post("/my/groups/ask", data={"group_id": G})
    assert r.headers["location"] == "/my"


def test_the_preview_never_writes(fake, monkeypatch):
    r = _client(monkeypatch, None, "preview").post("/my/groups/ask", data={"group_id": G})
    assert r.headers["location"] == "/my/groups?err=preview"
    assert fake.t["group_join_requests"] == []


def test_ask_route_lands_on_the_groups_page(fake, monkeypatch):
    r = _client(monkeypatch, _me(ROCHELLE, "Rochelle")).post("/my/groups/ask", data={"group_id": G})
    assert r.headers["location"] == f"/my/groups/{G}?done=asked"


def test_a_back_field_cannot_leave_the_group_pages(fake, monkeypatch):
    _one_post(fake)
    r = _client(monkeypatch, _me(MONIQUE, "Monique")).post(
        "/my/groups/post/ack", data={"id": POST1, "back": "https://evil.example/x"})
    assert r.headers["location"] == f"/my/groups/{G}/board"
    r = _client(monkeypatch, _me(MONIQUE, "Monique")).post(
        "/my/groups/post/ack", data={"id": POST1, "back": f"/my/groups/{G}"})
    assert r.headers["location"] == f"/my/groups/{G}"


def test_a_malformed_group_id_is_refused(fake, monkeypatch):
    r = _client(monkeypatch, _me(ROCHELLE, "Rochelle")).post("/my/groups/ask", data={"group_id": "x;drop"})
    assert r.headers["location"] == "/my/groups?err=group_gone"


# ── 8. failed reads ──────────────────────────────────────────────────

@pytest.mark.parametrize("table", ["groups", "group_members", "contacts", "group_posts", "group_post_seen"])
def test_a_failed_read_is_try_again(fake, table):
    _one_post(fake)
    fake.fail.add(table)
    data = mpg.space(BIZ, G, _me(MONIQUE, "Monique"))
    assert data is None
    html, status = mpg.render(BUSINESS, None, _req(), _me(MONIQUE, "Monique"), None)
    assert status == 503 and "couldn" in html
