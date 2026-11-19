"""I'm new here in the member app (member_im_new.py; Kevin, 2026-11-18: "the
i'm new here build it", the Lumen redesign's Connect "Your next step").
Pinned here:

  1. the form: one screen, the member's own words
  2. saving: their record tagged as New here tags a first timer (or "new
     here"), the answers kept, a follow-up handed on, nothing sent to them
  3. saving again updates the same follow-up, never a second; the same
     answers again write nothing
  4. a prayer stays with the pastors: a confidential care request, never in
     the follow-up, kept once
  5. routing: New here's (kind connect, the welcome role first), and a
     member who texted NEW gets a note on that follow-up instead
  6. the owner's preview refuses to save
  7. both switches (MEMBER_LUMEN, MEMBER_IM_NEW), churches, adults, Church
  8. a failed read is "try again" or a part left out, never a 500
  9. Your path: only what the church has, what they asked for first
 10. the card: Start, then Your path, its check kept
 11. the staff: the New here room lists them; its numbers stay the texts'
 12. the rate limit, and the session decides who
"""
import html
import json
import pathlib
import sys
import urllib.parse
import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import member_asks as ma  # noqa: E402
import member_cache  # noqa: E402
import member_im_new as imn  # noqa: E402
import member_portal as mp  # noqa: E402
import sb_clients  # noqa: E402

BIZ = "31111111-1111-4111-8111-111111111111"
HOST = "grace.mysolutionist.app"
ORIGIN = {"origin": f"https://{HOST}"}
ADULT = "1984-03-02"
TEEN = f"{date.today().year - 15}-01-01"


def cid(n: int) -> str:
    return f"00000000-0000-4000-8000-{n:012d}"


ANA, TEO, MARIA, PAUL, GRP, TEAM, CLOSED = cid(1), cid(2), cid(3), cid(4), cid(11), cid(12), cid(13)
OWNER_EMAIL = "owner@example.com"


# ─── a PostgREST-shaped fake ─────────────────────────────────────────


def _path_get(row, key):
    """`metadata->new_here->app->>at`, `submission->>source`, `name`."""
    if "->" not in key:
        return row.get(key)
    parts = key.replace("->>", "->").split("->")
    v = row.get(parts[0])
    for p in parts[1:]:
        v = v.get(p) if isinstance(v, dict) else None
    return None if v is None else (v if isinstance(v, (dict, list)) else str(v))


def _match(row, key, op):
    v = _path_get(row, key)
    if op.startswith("eq."):
        want = op[3:]
        if isinstance(v, bool):
            return str(v).lower() == want
        return v is not None and str(v) == want
    if op.startswith("neq."):
        return str(v) != op[4:]
    if op.startswith("in.("):
        return str(v) in [x.strip('"') for x in op[4:-1].split(",")]
    if op.startswith("like."):
        pat = op[5:]
        if pat.startswith("*"):
            return v is not None and str(v).endswith(pat[1:])
        return str(v) == pat
    if op == "is.null":
        return v is None
    if op.startswith(("gt.", "gte.", "lt.", "lte.")):
        name, want = op.split(".", 1)
        if v is None:
            return False
        a, b = str(v), want
        return {"gt": a > b, "gte": a >= b, "lt": a < b, "lte": a <= b}[name]
    raise AssertionError(f"filter not faked: {key}={op}")


class Fake:
    TABLES = ("contacts", "church_follow_ups", "church_follow_up_notes", "ministry_care_requests", "groups",
              "group_members", "serve_teams", "church_leader_roles", "sms_messages", "audit_log")

    def __init__(self):
        self.t = {k: [] for k in self.TABLES}
        self.biz = {"id": BIZ, "name": "Grace Hill Church", "type": "church", "owner_id": "owner",
                    "settings": {"member_portal": {"enabled": True}}}
        self.writes = []
        self.reads = []
        self.down = set()
        self.rpc = {"mine": [], "programs": [], "open": []}

    def add(self, table, **row):
        row.setdefault("id", str(uuid.uuid4()))
        self.t[table].append(row)
        return row

    def person(self, i, name, *, birthdate=ADULT, email="", tags=None, metadata=None):
        return self.add("contacts", id=i, business_id=BIZ, name=name,
                        email=email or f"{name.split()[0].lower()}@example.com", phone="+15550102030",
                        birthdate=birthdate, status="active", tags=list(tags or []),
                        metadata=dict(metadata or {"other": 1}))

    @staticmethod
    def _split(path):
        table, _, qs = path.lstrip("/").partition("?")
        return table, urllib.parse.parse_qsl(qs, keep_blank_values=True)

    def get(self, path, **kw):
        table, params = self._split(path)
        self.reads.append(path)
        if table in self.down:
            return None
        if table == "businesses":
            return [json.loads(json.dumps(self.biz))]
        rows = [r for r in self.t.get(table, [])
                if all(_match(r, k, v) for k, v in params if k not in ("select", "order", "limit"))]
        order = dict(params).get("order")
        if order:
            key, _, how = order.split(",")[0].partition(".")
            rows.sort(key=lambda r: str(r.get(key) or ""), reverse=how.startswith("desc"))
        out = json.loads(json.dumps(rows))
        select = dict(params).get("select", "")
        if "app:metadata->new_here->app" in select:
            out = [{"id": r["id"], "app": _path_get(r, "metadata->new_here->app")} for r in out]
        return out

    def post(self, path, body, **kw):
        table, _ = self._split(path)
        if table == "rpc/academy_member_classes":
            return None if "rpc" in self.down else json.loads(json.dumps(self.rpc))
        if table in self.down:
            return None
        out = []
        for r in body if isinstance(body, list) else [body]:
            r = json.loads(json.dumps(r))
            r.setdefault("id", str(uuid.uuid4()))
            r.setdefault("created_at", datetime.now(timezone.utc).isoformat())
            if table == "church_follow_ups" and r.get("source_event") and any(
                    f.get("source_event") == r["source_event"] for f in self.t[table]):
                return None                          # the table's unique index
            out.append(r)
        self.t.setdefault(table, []).extend(out)
        self.writes.append(("post", table, out))
        return out

    def patch(self, path, body, **kw):
        table, params = self._split(path)
        if table in self.down:
            return None
        rows = [r for r in self.t.get(table, []) if all(_match(r, k, v) for k, v in params)]
        for r in rows:
            r.update(json.loads(json.dumps(body)))
        self.writes.append(("patch", table, rows))
        return json.loads(json.dumps(rows))

    def written(self, table, kind=None):
        return [w for w in self.writes if w[1] == table and (kind is None or w[0] == kind)]

    def contact(self, i):
        return next(c for c in self.t["contacts"] if c["id"] == i)


@pytest.fixture
def fake(monkeypatch):
    import church_follow_up
    import church_history
    import church_map
    import church_roles
    f = Fake()
    monkeypatch.setattr(sb_clients, "sb_get_as_service", f.get)
    monkeypatch.setattr(sb_clients, "sb_post_as_service", f.post)
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", f.patch)
    monkeypatch.delenv("MEMBER_IM_NEW", raising=False)
    monkeypatch.setenv("MEMBER_LUMEN", "on")
    monkeypatch.setenv("CHURCH_MEMBER_ASKS", "on")
    monkeypatch.setenv("SUNDAY_PLANNING", "on")
    member_cache.forget_all()
    imn._TOLD.clear()
    imn._NOT_YET.clear()
    ma._READY.clear()
    ma._MINOR.clear()
    ma._OWNER_CACHE.clear()
    monkeypatch.setattr(ma, "minor", lambda biz, me: False)
    # The church's roles, as church_follow_up reads them: a Welcome Team lead
    # and a pastor (the first version's keys, so no library is needed).
    f.roles = [
        {"id": "r1", "contact_id": MARIA, "role": "welcome_lead", "scope": "", "status": "active", "name": "Maria Lopez",
         "email": "", "phone": ""},
        {"id": "r2", "contact_id": PAUL, "role": "pastor", "scope": "", "status": "active", "name": "Paul Grant",
         "email": "", "phone": ""},
    ]
    monkeypatch.setattr(church_follow_up, "roles", lambda biz: None if "roles" in f.down else list(f.roles))
    monkeypatch.setattr(church_follow_up, "_load", lambda biz: {})
    monkeypatch.setattr(church_roles, "defs", lambda biz: [])
    monkeypatch.setattr(church_map, "opened", lambda biz: False)
    monkeypatch.setattr(church_history, "note", lambda *a, **kw: True)
    # Nothing goes to the member: any text or email from here fails the test.
    import email_sender
    import sms_service

    def nope(*a, **kw):
        raise AssertionError("nothing is sent to the member")
    monkeypatch.setattr(email_sender, "send_via_resend", nope, raising=False)
    monkeypatch.setattr(sms_service, "_store_sms", nope, raising=False)
    f.person(ANA, "Ana Rivers")
    f.person(TEO, "Teo Rivers", birthdate=TEEN)
    return f


def _app(fake, monkeypatch, me_id, *, preview=False, space="", allow=True, claims=None):
    monkeypatch.setenv("CUSTOMER_TOKEN_SECRET", "test-root-secret")
    monkeypatch.setattr(mp, "_church_for_request", lambda req: {"business": json.loads(json.dumps(fake.biz)), "site": {}})
    import rate_limit
    monkeypatch.setattr(rate_limit, "allow_strict", lambda b, k, **kw: allow)

    def session(request, church):
        if not me_id:
            return None
        row = {k: v for k, v in fake.contact(me_id).items() if k in ("id", "name", "email", "birthdate")}
        out = {"claims": dict(claims or {}), "people": [row], "me": row}
        if preview:
            out["preview"] = True
        return out
    monkeypatch.setattr(mp, "_session_for", session)
    import member_spaces as msp

    async def resolve(b, me, wanted=""):
        return msp._placed(me, space, {"youth": {}} if space == "youth" else {}, space == "kids")
    monkeypatch.setattr(msp, "resolve_async", resolve)

    async def leads(*a, **kw):
        return False
    monkeypatch.setattr(mp, "_leads", leads)
    app = FastAPI()
    app.include_router(imn.router)
    app.include_router(ma.router)

    @app.get("/my/{rest:path}")
    async def page(request: Request, rest: str):
        return await mp.serve(request, "/my/" + rest)
    return TestClient(app, base_url=f"https://{HOST}")


FORM = {"first": "yes", "heard": "A friend or family", "kids": "yes", "ages": "4 and 7",
        "wants": ["group", "baptism"], "prayer": "My dad's surgery is Friday."}


def _t(r):
    """The page as a person reads it (quotes and apostrophes unescaped)."""
    return html.unescape(r.text)


def _post(c, data):
    return c.post(imn.PATH, data=data, headers=ORIGIN, follow_redirects=False)


def _app_row(fake, i=ANA):
    return ((fake.contact(i).get("metadata") or {}).get("new_here") or {}).get("app") or {}


# ─── 1. the form ─────────────────────────────────────────────────────


def test_the_form_is_one_screen_in_their_own_words(fake, monkeypatch):
    c = _app(fake, monkeypatch, ANA)
    r = c.get(imn.PATH)
    assert r.status_code == 200
    page = _t(r)
    assert f'method="post" action="{imn.PATH}"' in page and page.count("<form") >= 1
    for words in ("I'm new", "I've been coming a while", "How did you hear about us?", "Do you have kids?",
                  "Their ages", "I'd like to", "Find a group", "Serve", "Get baptized",
                  "Take a class or learn the faith", "Talk with a pastor", "Only our pastors see this.",
                  "Tell the church"):
        assert words in page, words
    import new_here
    assert all(h in page for h in new_here.HEARD)          # the guest card's own list
    assert 'class="imn al-2"' in page                       # the Lumen look, accent level 2
    assert page.count('name="wants"') == len(imn.WANTS)
    assert not fake.writes


# ─── 2. saving ───────────────────────────────────────────────────────


def test_saving_keeps_their_answers_tags_them_and_hands_them_on(fake, monkeypatch):
    c = _app(fake, monkeypatch, ANA)
    r = _post(c, FORM)
    assert r.status_code == 303 and r.headers["location"] == f"{imn.PATH}?done=saved"
    person = fake.contact(ANA)
    assert person["tags"] == ["first-time guest"]                     # as New here tags a first timer
    assert person["metadata"]["other"] == 1                           # the rest of their record kept
    app = person["metadata"]["new_here"]["app"]
    assert app["first_time"] is True and app["heard"] == "A friend or family"
    assert app["kids"] == "yes" and app["ages"] == "4 and 7" and app["wants"] == ["group", "baptism"]
    assert app["prayer"] is True and app["follow_up"] is True and app["at"]
    assert "surgery" not in json.dumps(person["metadata"])           # the prayer's words aren't on the record
    (fu,) = fake.t["church_follow_ups"]
    assert fu["card_key"] == imn.CARD_KEY == "app:new_here" and fu["card_name"] == imn.CARD_NAME
    assert fu["path_kind"] == "connect" and fu["source_event"] == f"app-new-here:{ANA}"
    assert fu["contact_id"] == ANA and fu["status"] == "open"
    assert {"q": "First time?", "a": "Yes"} in fu["answers"]
    assert {"q": "Kids", "a": "Yes, ages 4 and 7"} in fu["answers"]
    assert {"q": "They'd like to", "a": "Find a group and get baptized"} in fu["answers"]
    assert {"q": "Where", "a": "Told the church in the member app"} in fu["answers"]
    # The page after: Your path, with a thank-you.
    page = _t(c.get(f"{imn.PATH}?done=saved"))
    assert "Your <em>path</em>" in page and "Thank you, Ana." in page and "Grace Hill Church knows you" in page
    assert "Your prayer went only to the pastors." in page
    assert "Someone from the church will reach out to you soon." in page
    # Nothing written anywhere a text or an email would go from.
    assert not fake.written("sms_messages")
    # church_reads counts a first timer from the follow-up's answers.
    import church_reads
    assert church_reads._card_says_first(fu, None, datetime.now(timezone.utc)) is True
    assert church_reads._card_is_for_guests(fu) is True


def test_someone_coming_a_while_is_tagged_new_here(fake, monkeypatch):
    c = _app(fake, monkeypatch, ANA)
    _post(c, {"first": "no", "kids": "no", "ages": "9", "heard": "Not a choice"})
    person = fake.contact(ANA)
    assert person["tags"] == ["new here"]
    app = person["metadata"]["new_here"]["app"]
    assert app["first_time"] is False and app["heard"] == "" and app["kids"] == "no" and app["ages"] == ""
    (fu,) = fake.t["church_follow_ups"]
    assert {"q": "First time?", "a": "Been coming a while"} in fu["answers"]
    import church_reads
    assert church_reads._card_says_first(fu, None, datetime.now(timezone.utc)) is False
    assert not fake.t["ministry_care_requests"]                       # no prayer, no care request


# ─── 3. one save per member ──────────────────────────────────────────


def test_saving_again_updates_the_same_follow_up(fake, monkeypatch):
    c = _app(fake, monkeypatch, ANA)
    _post(c, {**FORM, "prayer": ""})
    (fu,) = fake.t["church_follow_ups"]
    first_at = _app_row(fake)["at"]
    r = _post(c, {**FORM, "prayer": "", "wants": ["serve", "pastor"]})
    assert r.headers["location"] == f"{imn.PATH}?done=saved"
    assert len(fake.t["church_follow_ups"]) == 1                      # never a second
    assert {"q": "They'd like to", "a": "Serve and talk with a pastor"} in fake.t["church_follow_ups"][0]["answers"]
    notes = [n["body"] for n in fake.t["church_follow_up_notes"]]
    assert any(n.startswith("Changed what they told the church in the member app.") for n in notes)
    app = _app_row(fake)
    assert app["wants"] == ["serve", "pastor"] and app["at"] == first_at
    # The same answers again: nothing written at all.
    before = len(fake.writes)
    r = _post(c, {**FORM, "prayer": "", "wants": ["serve", "pastor"]})
    assert r.headers["location"] == f"{imn.PATH}?done=same"
    assert len(fake.writes) == before
    assert "already has this" in _t(c.get(f"{imn.PATH}?done=same"))


def test_a_second_server_copy_never_makes_a_second_follow_up(fake, monkeypatch):
    # The unique source_event: a follow-up made a moment ago on another copy
    # (so not found by card_key here) is "already there", not a failure.
    import church_follow_up
    fake.add("church_follow_ups", business_id=BIZ, contact_id=ANA, card_key="elsewhere", status="open",
             source_event=f"app-new-here:{ANA}")
    assert imn.hand_on(BIZ, ANA, imn.clean({"first": "yes"})) is True
    assert len(fake.t["church_follow_ups"]) == 1
    assert church_follow_up  # the real start ran and was refused by the index


# ─── 4. the prayer ───────────────────────────────────────────────────


def test_a_prayer_stays_with_the_pastors(fake, monkeypatch):
    import church_prayer
    shared = []
    monkeypatch.setattr(church_prayer, "on_new", lambda biz, row: shared.append(row))
    c = _app(fake, monkeypatch, ANA)
    _post(c, FORM)
    (care,) = fake.t["ministry_care_requests"]
    sub = care["submission"]
    assert sub["prayer_request"] == "My dad's surgery is Friday." and sub["confidential"] == "yes"
    assert sub["source"] == imn.SOURCE and care["contact_id"] == ANA and care["status"] == "new"
    assert care["prayer_team"] is False                               # never the prayer team
    assert shared and shared[0]["id"] == care["id"]                   # New here's hand-off, which keeps it there
    # Never in the follow-up, its notes, or the record.
    assert "surgery" not in json.dumps(fake.t["church_follow_ups"] + fake.t["church_follow_up_notes"])
    # Sent again (a double tap, or saving again): kept once.
    _post(c, FORM)
    _post(c, {**FORM, "wants": ["class"]})
    assert len(fake.t["ministry_care_requests"]) == 1
    _post(c, {**FORM, "prayer": "And for my sister."})
    assert len(fake.t["ministry_care_requests"]) == 2


def test_a_prayer_that_doesnt_keep_says_so(fake, monkeypatch):
    c = _app(fake, monkeypatch, ANA)
    fake.down.add("ministry_care_requests")
    r = _post(c, FORM)
    assert r.headers["location"] == f"{imn.PATH}?done=noprayer"
    assert _app_row(fake)["at"]                                       # the rest is saved
    page = _t(c.get(f"{imn.PATH}?done=noprayer"))
    assert "Your prayer didn't send just now" in page and 'href="/my/prayer"' in page


def test_words_that_need_the_crisis_line_get_it(fake, monkeypatch):
    c = _app(fake, monkeypatch, ANA)
    r = _post(c, {**FORM, "prayer": "I want to kill myself"})
    assert r.headers["location"] == f"{imn.PATH}?done=care"
    assert "988" in _t(c.get(f"{imn.PATH}?done=care"))
    assert fake.t["ministry_care_requests"][0]["needs_pastor"] is True


# ─── 5. routing ──────────────────────────────────────────────────────


def test_it_routes_as_new_here_does(fake, monkeypatch):
    c = _app(fake, monkeypatch, ANA)
    _post(c, {**FORM, "wants": ["pastor"], "prayer": ""})
    (fu,) = fake.t["church_follow_ups"]
    # The welcome role first, even when they'd like to talk with a pastor:
    # the answers never re-route it (route_answers=[], as New here's card).
    assert fu["leader_contact_id"] == MARIA and fu["leader_role"] == "welcome_lead"
    assert "New here cards go to the Welcome Team lead" in fu["reason"]
    # With no welcome role, the senior role, as for any connect card.
    fake.roles = [r for r in fake.roles if r["role"] != "welcome_lead"]
    fake.t["church_follow_ups"].clear()
    fake.t["contacts"][0]["metadata"] = {}
    _post(c, {**FORM, "prayer": ""})
    assert fake.t["church_follow_ups"][0]["leader_contact_id"] == PAUL


def test_a_member_who_texted_new_gets_a_note_not_a_second_follow_up(fake, monkeypatch):
    import new_here
    text_fu = fake.add("church_follow_ups", business_id=BIZ, contact_id=ANA, card_key=new_here.CARD_KEY,
                       status="open", source_event=f"new-here:{ANA}:2026-11-15")
    c = _app(fake, monkeypatch, ANA)
    _post(c, {**FORM, "prayer": ""})
    assert len(fake.t["church_follow_ups"]) == 1
    (note,) = fake.t["church_follow_up_notes"]
    assert note["follow_up_id"] == text_fu["id"] and note["body"].startswith("Also told the church in the member app.")
    assert _app_row(fake)["follow_up"] is True


def test_a_follow_up_that_cant_be_checked_is_never_started(fake, monkeypatch):
    c = _app(fake, monkeypatch, ANA)
    fake.down.add("church_follow_ups")
    r = _post(c, {**FORM, "prayer": ""})
    assert r.headers["location"] == f"{imn.PATH}?done=saved"          # their answers are kept
    assert _app_row(fake)["follow_up"] is False
    assert "reach out to you soon" not in _t(c.get(f"{imn.PATH}?done=saved"))
    # The next save tries again.
    fake.down.discard("church_follow_ups")
    _post(c, {**FORM, "prayer": ""})
    assert len(fake.t["church_follow_ups"]) == 1 and _app_row(fake)["follow_up"] is True


# ─── 6. the owner's preview ──────────────────────────────────────────


def test_the_preview_shows_the_form_and_saves_nothing(fake, monkeypatch):
    c = _app(fake, monkeypatch, ANA, preview=True)
    page = _t(c.get(imn.PATH))
    assert "This is a preview, so nothing is saved." in page and "Tell the church" in page
    r = _post(c, FORM)
    assert r.status_code == 303 and r.headers["location"] == f"{imn.PATH}?err=preview"
    assert not fake.writes


# ─── 7. who sees it ──────────────────────────────────────────────────


def test_the_rollback_switch(fake, monkeypatch):
    c = _app(fake, monkeypatch, ANA)
    monkeypatch.setenv("MEMBER_IM_NEW", "off")
    r = c.get(imn.PATH, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/my"
    assert _post(c, FORM).headers["location"] == "/my"
    assert imn.new_here_card(fake.biz, {"me": fake.contact(ANA), "space": "church"}, None) == ""
    assert not fake.writes
    monkeypatch.setenv("MEMBER_IM_NEW", "on")
    assert c.get(imn.PATH).status_code == 200
    monkeypatch.delenv("MEMBER_IM_NEW")
    assert imn.on() is True                                           # on when unset


def test_the_redesigns_switch(fake, monkeypatch):
    import member_lumen
    c = _app(fake, monkeypatch, ANA)
    monkeypatch.setenv("MEMBER_LUMEN", "off")
    assert c.get(imn.PATH, follow_redirects=False).headers["location"] == "/my"
    assert _post(c, FORM).headers["location"] == "/my"
    assert not fake.writes
    # preview (the default): only the platform owner, at their own church.
    monkeypatch.delenv("MEMBER_LUMEN")
    assert member_lumen.mode() == "preview"
    monkeypatch.setenv("PLATFORM_OWNER_EMAIL", OWNER_EMAIL)
    monkeypatch.setattr(ma, "platform_church", lambda b: True)
    assert c.get(imn.PATH, follow_redirects=False).headers["location"] == "/my"   # an ordinary member
    assert _post(c, FORM).headers["location"] == "/my"
    assert not fake.writes
    owner = _app(fake, monkeypatch, ANA, claims={"em": OWNER_EMAIL})                 # the owner's own sign-in
    assert owner.get(imn.PATH).status_code == 200
    assert _post(owner, FORM).headers["location"] == f"{imn.PATH}?done=saved"
    monkeypatch.setattr(ma, "platform_church", lambda b: False)                     # another church
    assert owner.get(imn.PATH, follow_redirects=False).headers["location"] == "/my"


def test_churches_adults_and_church_only(fake, monkeypatch):
    teen = _app(fake, monkeypatch, TEO)
    assert teen.get(imn.PATH, follow_redirects=False).headers["location"] == "/my"
    assert _post(teen, FORM).headers["location"] == "/my"
    assert imn.new_here_card(fake.biz, {"me": fake.contact(TEO), "space": "church"}, None) == ""
    assert imn.new_here_card(fake.biz, {"me": fake.contact(ANA), "space": "kids"}, None) == ""
    fake.biz["type"] = "nonprofit"                                   # has the member page, isn't a church
    c = _app(fake, monkeypatch, ANA)
    assert c.get(imn.PATH, follow_redirects=False).headers["location"] == "/my"
    assert _post(c, FORM).headers["location"] == "/my"
    assert not fake.writes


# ─── 8. a failed read ────────────────────────────────────────────────


def test_failed_reads_never_500(fake, monkeypatch):
    c = _app(fake, monkeypatch, ANA)
    fake.down.add("contacts")
    r = c.get(imn.PATH)
    assert r.status_code == 503 and "try again" in _t(r).lower()
    r = _post(c, FORM)
    assert r.status_code == 303 and r.headers["location"].startswith(f"{imn.PATH}?err=error")
    assert not fake.writes
    # The card: a failed check is Start (whose page reads again), never kept.
    card = imn.new_here_card(fake.biz, {"me": fake.contact(ANA), "space": "church"}, None)
    assert 'href="/my/new">Start' in card
    fake.down.discard("contacts")
    _post(c, {**FORM, "prayer": "", "wants": []})
    # Your path with every part down: still a page, the parts left out.
    fake.down |= {"groups", "group_members", "rpc"}
    monkeypatch.setattr(ma, "entry", lambda *a: (_ for _ in ()).throw(RuntimeError("down")))
    r = c.get(imn.PATH)
    assert r.status_code == 200 and "Your <em>path</em>" in _t(r)
    assert "Grace Hill Church will help you find your next step." in _t(r)
    # A form post with nothing in it still saves sensibly.
    assert imn.clean({}) == {"first_time": True, "heard": "", "kids": "no", "ages": "", "wants": [], "prayer": ""}


# ─── 9. Your path ────────────────────────────────────────────────────


def _church_with_everything(fake):
    fake.biz["settings"]["member_portal"]["asks"] = {"on": ["visit", "life_event", "help"]}
    fake.add("groups", id=GRP, business_id=BIZ, active=True, kind="small_group", join_mode="open", youth=False)
    fake.add("groups", id=TEAM, business_id=BIZ, active=True, kind="team", join_mode="ask", youth=False)
    fake.add("groups", id=CLOSED, business_id=BIZ, active=True, kind="small_group", join_mode="invite", youth=False)
    fake.add("serve_teams", business_id=BIZ, group_id=TEAM)
    fake.rpc = {"mine": [], "open": [], "programs": [{
        "id": "p1", "title": "Next Steps", "tracks": [
            {"course_id": "c1", "title": "Next Steps: Belong", "state": "done"},
            {"course_id": "c2", "title": "Next Steps: Grow", "state": "now"},
            {"course_id": "c3", "title": "Next Steps: Serve", "state": "later"}]}]}


def test_your_path_is_what_the_church_has(fake, monkeypatch):
    _church_with_everything(fake)
    c = _app(fake, monkeypatch, ANA)
    _post(c, {**FORM, "prayer": "", "wants": ["baptism", "pastor"]})
    page = _t(c.get(imn.PATH))
    for words in ("Keep going on Next Steps", "Grow now, then Serve", "Try a group", "Serve on a team",
                  "Get baptized", "Talk with a pastor"):
        assert words in page, words
    assert 'href="/my/classes"' in page and 'href="/my/groups"' in page
    assert 'href="/my/ask/life?pick=baptism"' in page and 'href="/my/ask/visit?pick=talk"' in page
    # What they asked for first, marked.
    assert page.index("Get baptized") < page.index("Keep going on Next Steps")
    assert page.count("Your pick") == 2
    # Ask the church opens on the baptism they picked.
    life = _t(c.get("/my/ask/life?pick=baptism"))
    assert 'value="baptism" required checked' in life
    assert 'value="wedding" required>' in life


def test_your_path_leaves_out_what_the_church_doesnt_have(fake, monkeypatch):
    c = _app(fake, monkeypatch, ANA)
    _post(c, {**FORM, "prayer": "", "wants": ["serve"]})
    page = _t(c.get(imn.PATH))
    for words in ("Keep going on", "Try a group", "Serve on a team", "Get baptized", "Talk with a pastor",
                  "Take a class"):
        assert words not in page, words
    # Their wish with no door here is passed on, because a follow-up carries it.
    assert "You told the church. Someone will talk with you about it." in page
    # A member already on a Sunday team sees their serving instead.
    fake.add("groups", id=TEAM, business_id=BIZ, active=True, kind="team", join_mode="ask", youth=False)
    fake.add("serve_teams", business_id=BIZ, group_id=TEAM)
    fake.add("group_members", business_id=BIZ, group_id=TEAM, contact_id=ANA)
    page = _t(c.get(imn.PATH))
    assert "Your serving" in page and 'href="/my/serving"' in page and "Serve on a team" not in page


def test_the_rows(fake):
    rows = imn.path_rows({"program": None, "open_program": "", "open_n": 2}, {"groups": 0, "teams_open": 0,
                         "serves": False}, ["help"], ["class"], handed=False)
    assert [(r["title"], r["picked"]) for r in rows] == [("Take a class", True), ("Ask for a visit or help", False)]
    assert imn.path_rows(None, None, None, ["group"], handed=False) == []


# ─── 10. the card ────────────────────────────────────────────────────


def test_the_card_says_start_then_your_path(fake, monkeypatch):
    ctx = {"me": fake.contact(ANA), "space": "church"}
    card = imn.new_here_card(fake.biz, ctx, None)
    assert "I'm new here" in card and "Tell the church you're new, and get a simple path to find your place." in card
    assert 'href="/my/new">Start</a>' in card and 'class="imn al-2"' in card
    # Kept: a second draw reads nothing.
    reads = len(fake.reads)
    imn.new_here_card(fake.biz, ctx, None)
    assert len(fake.reads) == reads
    c = _app(fake, monkeypatch, ANA)
    _post(c, {**FORM, "prayer": ""})
    card = imn.new_here_card(fake.biz, ctx, None)                     # this copy knows at once
    assert "Your path" in card and 'href="/my/new">Open</a>' in card and "Start" not in card
    # Another server copy: before is kept a minute; told, ten.
    imn._TOLD.clear()
    imn._NOT_YET.clear()
    assert "Your path" in imn.new_here_card(fake.biz, {"session": {"me": fake.contact(ANA)}, "space": "church"}, None)
    assert imn.TOLD_SECONDS == 600 and imn.NOT_YET_SECONDS == 60


def test_connect_leads_with_the_card(fake, monkeypatch):
    """The Lumen hook (member_lumen.new_here_card) answers with this card, and
    Connect's "Your next step" carries it."""
    import member_lumen
    me = fake.contact(ANA)
    assert "I'm new here" in member_lumen.new_here_card(fake.biz, me)
    assert member_lumen.new_here_card(fake.biz, me) == imn.new_here_card(fake.biz, {"me": me}, None)
    c = _app(fake, monkeypatch, ANA)
    token = member_lumen.CURRENT.set(True)
    try:
        r = c.get("/my/connect")
    finally:
        member_lumen.CURRENT.reset(token)
    assert r.status_code == 200 and 'class="lm-newslot"' in r.text
    assert 'href="/my/new">Start</a>' in r.text.split('class="lm-newslot"', 1)[1]
    monkeypatch.setenv("MEMBER_IM_NEW", "off")
    imn._TOLD.clear()
    imn._NOT_YET.clear()
    assert member_lumen.new_here_card(fake.biz, me) == ""


def test_the_card_follows_the_page_look(fake, monkeypatch):
    import member_lumen
    monkeypatch.setenv("MEMBER_LUMEN", "off")
    ctx = {"me": fake.contact(ANA), "space": "church"}
    assert imn.new_here_card(fake.biz, ctx, None) == ""
    token = member_lumen.CURRENT.set(True)                            # the page wears the redesign
    try:
        assert "Start" in imn.new_here_card(fake.biz, ctx, None)
    finally:
        member_lumen.CURRENT.reset(token)


# ─── 11. the staff side ──────────────────────────────────────────────


def test_the_new_here_room_lists_them(fake, monkeypatch):
    import new_here
    c = _app(fake, monkeypatch, ANA)
    _post(c, FORM)
    now = new_here._iso(new_here._now())
    fake.person(cid(5), "Dana Reyes", metadata={"new_here": {"texted_at": now, "card_at": now,
                                                               "card": {"first_time": True, "kids": "None"}}})
    guests = new_here.guests_of(fake.biz)
    by = {g["contact_id"]: g for g in guests}
    ana, dana = by[ANA], by[cid(5)]
    assert ana["from"] == "app" and ana["texted_at"] is None and ana["app_at"] and ana["card_at"] == ana["app_at"]
    assert ana["card"] == {"first_time": True, "heard": "A friend or family", "kids": "4 and 7", "prayer": True,
                           "wants": ["group", "baptism"]}
    assert ana["follow_up"] == {"leader": "", "status": "open", "reached": False}
    fake.person(MARIA, "Maria Lopez")
    assert {g["contact_id"]: g for g in new_here.guests_of(fake.biz)}[ANA]["follow_up"]["leader"] == "Maria Lopez"
    assert dana["from"] == "text" and dana["app_at"] is None
    # The room's numbers stay the texts': a member in the app isn't a text.
    monkeypatch.setattr(new_here, "tz_of", lambda b: timezone.utc)
    counts = new_here.counts_of(fake.biz, guests)
    assert counts["sunday"] <= 1 and counts["card"] <= 1
    # Their list read failing leaves them out, never the list.
    real = fake.get

    def flaky(path, **kw):
        return None if "new_here->app" in path else real(path, **kw)
    monkeypatch.setattr(sb_clients, "sb_get_as_service", flaky)
    assert [g["contact_id"] for g in new_here.guests_of(fake.biz)] == [cid(5)]


# ─── 12. the rate limit, and who ─────────────────────────────────────


def test_the_rate_limit(fake, monkeypatch):
    c = _app(fake, monkeypatch, ANA, allow=False)
    r = _post(c, FORM)
    assert r.headers["location"].startswith(f"{imn.PATH}?err=slow")
    assert not fake.writes
    import rate_limit
    assert "member_im_new" in rate_limit._LIMITS


def test_the_session_decides_who(fake, monkeypatch):
    other = fake.person(cid(6), "Ben Stone")
    c = _app(fake, monkeypatch, ANA)
    _post(c, {**FORM, "prayer": "", "contact_id": other["id"], "business_id": "elsewhere", "id": other["id"]})
    assert _app_row(fake, ANA)["at"] and not _app_row(fake, other["id"])
    assert fake.t["church_follow_ups"][0]["contact_id"] == ANA
    # A post from another site is refused before anything is read.
    r = c.post(imn.PATH, data=FORM, headers={"origin": "https://evil.example"}, follow_redirects=False)
    assert r.status_code == 403


def test_the_wiring():
    root = pathlib.Path(__file__).resolve().parent.parent
    app = (root / "kmj_intake_automation.py").read_text(encoding="utf-8")
    assert app.index("from member_im_new import router") < app.index("app.include_router(public_site_router)")
    portal = (root / "member_portal.py").read_text(encoding="utf-8")
    assert 'if sub == "/my/new":' in portal and "member_im_new.serve(" in portal
