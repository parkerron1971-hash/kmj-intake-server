"""The member directory (member_directory.py; Kevin, 2026-10-27: "member
directory is a go sense we have safety room"). Pins:

  1. off by default: nothing served, nothing offered, nothing saved
  2. opt-in only: nobody is listed until they say yes themselves
  3. hidden fields stay hidden: a phone, email or household nobody turned on
     is never in the data or the page
  4. minors are never listed and never see it (birthdate, a child on a
     family, a teen linked to a parent, a youth/kids tag)
  5. other churches never: not their people, not their office
  6. only the owner flips the church's switch; an admin seat sees the list
  7. a member the office took out stays out until the office lets them back
  plus: visitors (leads) aren't listed and don't see it; messages go through
  member messaging only when it's on; households show together only when
  each adult chose it; the tab is offered only while it's on.
"""
import asyncio
import json
import pathlib
import re
import sys
import urllib.parse
from datetime import date
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import member_app_ui as ui
import member_directory as md
import member_portal as mp
import member_portal_church as mpc

BIZ = "11111111-1111-1111-1111-111111111111"
OTHER = "22222222-2222-2222-2222-222222222222"
HOST = "love-city.mysolutionist.app"
ORIGIN = {"origin": f"https://{HOST}"}


def cid(n: int) -> str:
    return f"00000000-0000-4000-8000-{n:012d}"


ANA, BEN, CARA, DEV, ELI, FAY, GUS, HAL, IVY, JO, KAI = (cid(i) for i in range(1, 12))
STRANGER = cid(90)
H1 = "aaaaaaaa-0000-4000-8000-000000000001"
ADULT = "1980-05-01"
TEEN = f"{date.today().year - 15}-01-01"


def _q(path, name):
    return urllib.parse.parse_qs(path.split("?", 1)[1]).get(name, [""])[0]


def _in(path, name):
    v = _q(path, name)
    return [x for x in v[len("in.("):-1].split(",") if x] if v.startswith("in.(") else []


def _contains(have, want):
    if isinstance(want, dict):
        return isinstance(have, dict) and all(k in have and _contains(have[k], v) for k, v in want.items())
    return have == want


class Fake:
    """Two churches' records, read and written the way PostgREST would."""

    def __init__(self):
        self.messaging = False
        self.contacts = {}
        self.children = []          # {business_id, contact_id}
        self.guardians = []         # {business_id, teen_contact_id}
        self.house_adults = []      # {business_id, household_id, contact_id}
        self.houses = {}            # id -> {business_id, name}
        self.msg_members = {}       # contact -> enabled
        self.biz = {BIZ: {"id": BIZ, "name": "Love City Church", "type": "church", "owner_id": "owner",
                          "settings": {"member_portal": {"enabled": True}}},
                    OTHER: {"id": OTHER, "name": "Other Church", "type": "church", "owner_id": "other-owner",
                            "settings": {"member_portal": {"enabled": True, "directory": {"on": True}}}}}
        self.patches = []
        self.reads = []

    def add(self, i, name, *, biz=BIZ, status="active", birthdate=ADULT, phone="", email="", tags=None, directory=None):
        meta = {"note": "keep me"}
        if directory is not None:
            meta["directory"] = directory
        self.contacts[i] = {"id": i, "business_id": biz, "name": name, "status": status, "birthdate": birthdate,
                            "phone": phone, "email": email, "tags": tags or [], "metadata": meta, "updated_at": "r1"}

    def _row(self, c, select):
        out = {}
        for part in select.split(","):
            if ":" in part:
                alias, expr = part.split(":", 1)
                key = re.split(r"->>?", expr)[1]
                out[alias] = (c["metadata"] or {}).get(key)
            else:
                out[part] = c.get(part)
        return out

    def get(self, path, **kw):
        self.reads.append(path)
        biz = _q(path, "business_id").removeprefix("eq.")
        if path.startswith("/businesses"):
            b = self.biz.get(_q(path, "id").removeprefix("eq."))
            return [json.loads(json.dumps(b))] if b else []
        if path.startswith("/contacts"):
            sel = _q(path, "select")
            rows = [c for c in self.contacts.values() if c["business_id"] == biz]
            one = _q(path, "id")
            if one:
                rows = [c for c in rows if c["id"] == one.removeprefix("eq.")]
            cs = _q(path, "metadata")
            if cs.startswith("cs."):
                want = json.loads(cs[3:])
                rows = [c for c in rows if _contains(c["metadata"], want)]
            rows.sort(key=lambda c: c["name"])
            return [self._row(json.loads(json.dumps(c)), sel) for c in rows]
        if path.startswith("/children"):
            ids = _in(path, "contact_id")
            return [{"contact_id": r["contact_id"]} for r in self.children if r["business_id"] == biz and r["contact_id"] in ids]
        if path.startswith("/msg_guardians"):
            ids = _in(path, "teen_contact_id")
            return [{"teen_contact_id": r["teen_contact_id"]} for r in self.guardians
                    if r["business_id"] == biz and r["teen_contact_id"] in ids]
        if path.startswith("/household_adults"):
            ids = _in(path, "contact_id")
            return [dict(r) for r in self.house_adults if r["business_id"] == biz and r["contact_id"] in ids]
        if path.startswith("/households"):
            ids = _in(path, "id")
            return [{"id": h, "name": v["name"]} for h, v in self.houses.items() if v["business_id"] == biz and h in ids]
        if path.startswith("/msg_members"):
            ids = _in(path, "contact_id")
            return [{"contact_id": i, "enabled": on} for i, on in self.msg_members.items()
                    if i in ids and self.contacts.get(i, {}).get("business_id") == biz]
        if path.startswith("/business_users"):
            return []
        return []

    def patch(self, path, body):
        self.patches.append((path, body))
        if path.startswith("/contacts"):
            c = self.contacts.get(_q(path, "id").removeprefix("eq."))
            if not c or c["business_id"] != _q(path, "business_id").removeprefix("eq."):
                return []
            if _q(path, "updated_at").removeprefix("eq.") != c["updated_at"]:
                return []
            c.update(json.loads(json.dumps(body)))
            c["updated_at"] += "x"
            return [c]
        if path.startswith("/businesses"):
            b = self.biz[_q(path, "id").removeprefix("eq.")]
            b.update(json.loads(json.dumps(body)))
            return [b]
        return []

    def turn_on(self, biz=BIZ):
        self.biz[biz]["settings"]["member_portal"]["directory"] = {"on": True}
        if self.messaging:
            self.biz[biz]["settings"]["messaging"] = {"enabled": True}

    def business(self, b=BIZ):
        return json.loads(json.dumps(self.biz[b]))


@pytest.fixture
def fake(monkeypatch):
    f = Fake()
    monkeypatch.setattr(md.sb_clients, "sb_get_as_service", f.get)
    monkeypatch.setattr(md.sb_clients, "sb_patch_as_service", f.patch)
    return f


def _yes(**fields):
    return {"listed": True, **{k: fields.get(k, False) for k in md.FIELDS}}


def _people(v):
    return [p for c in v["cards"] for p in c["people"]]


def _names(v):
    return sorted(p["name"] for p in _people(v))


# ─── 1. off by default ───────────────────────────────────────────────


def test_off_until_the_church_turns_it_on(fake):
    for biz in ({}, None, {"settings": {}}, {"settings": {"member_portal": {"enabled": True}}},
                {"settings": {"member_portal": {"directory": {"on": "yes"}}}},
                {"settings": {"member_portal": {"directory": True}}}):
        assert md.church_on(biz) is False
    biz = fake.business()
    assert not md.church_on(biz)
    # Not offered as a tab, not on Connect, not in My details.
    assert "directory" not in {c["key"] for c in ui.tab_choices(biz)}
    assert ui.church_tabs({**biz, "settings": {"member_portal": {"tabs": ["home", "directory", "give"]}}}) == (
        ui.CHURCH_TABS["home"], ui.CHURCH_TABS["give"])
    assert "/my/directory" not in mpc.connect_tabs(biz, "groups")
    fake.add(ANA, "Ana Rivers")
    assert md.details_block(biz, ANA) == ""


def test_off_the_page_isnt_served_and_nothing_saves(fake, monkeypatch):
    fake.add(ANA, "Ana Rivers", email="ana@example.com")
    c = _app(fake, monkeypatch, ANA)
    r = c.get("/my/directory", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/my"
    r = c.post("/my/directory/me", data={"listed": "yes"}, headers=ORIGIN, follow_redirects=False)
    assert r.headers["location"] == "/my?err=dir_closed"
    assert not fake.patches and "directory" not in fake.contacts[ANA]["metadata"]


# ─── 2. opt-in only ──────────────────────────────────────────────────


def test_nobody_is_listed_until_they_say_yes(fake):
    fake.turn_on()
    for i, n in ((ANA, "Ana Rivers"), (BEN, "Ben Rivers"), (CARA, "Cara Stone")):
        fake.add(i, n)
    fake.contacts[CARA]["metadata"]["directory"] = {"listed": False, "phone": True}
    v = md.view(fake.business(), ANA)
    assert v["state"] == "ok" and v["count"] == 0 and v["cards"] == []
    assert md.save_choice(BIZ, BEN, _yes()) == "dir_on"
    v = md.view(fake.business(), ANA)
    assert _names(v) == ["Ben Rivers"] and not v["listed_me"]
    # Other metadata is kept.
    assert fake.contacts[BEN]["metadata"]["note"] == "keep me"
    # Saying no takes them out and turns every field off.
    md.save_choice(BIZ, BEN, _yes(phone=True))
    assert md.save_choice(BIZ, BEN, {"listed": False, "phone": True}) == "dir_off"
    assert fake.contacts[BEN]["metadata"]["directory"]["phone"] is False
    assert md.view(fake.business(), ANA)["count"] == 0


def test_a_member_says_yes_from_the_page_or_my_details(fake, monkeypatch):
    fake.turn_on()
    fake.add(ANA, "Ana Rivers", email="ana@example.com", phone="555 010 2030")
    c = _app(fake, monkeypatch, ANA)
    page = c.get("/my/directory").text
    assert "Show me in the directory" in page and 'action="/my/directory/me"' in page
    r = c.post("/my/directory/me", data={"listed": "yes", "back": "/my/directory"}, headers=ORIGIN,
               follow_redirects=False)
    assert r.headers["location"] == "/my/directory?done=dir_on"
    rec = fake.contacts[ANA]["metadata"]["directory"]
    assert rec["listed"] is True and not any(rec[f] for f in md.FIELDS)     # name and photo only
    r = c.post("/my/directory/me", data={"listed": "yes", "email": "yes", "back": "/my/details"}, headers=ORIGIN,
               follow_redirects=False)
    assert r.headers["location"] == "/my/details?done=dir_saved"
    assert fake.contacts[ANA]["metadata"]["directory"]["email"] is True
    # An open redirect isn't possible through back.
    r = c.post("/my/directory/me", data={"listed": "yes", "back": "https://evil.example"}, headers=ORIGIN,
               follow_redirects=False)
    assert r.headers["location"].startswith("/my/directory?")
    # Cross-site is refused.
    r = c.post("/my/directory/me", data={"listed": "no"}, headers={"origin": "https://evil.example"},
               follow_redirects=False)
    assert r.status_code == 403


def test_signed_out_is_sent_to_sign_in(fake, monkeypatch):
    fake.turn_on()
    fake.add(ANA, "Ana Rivers")
    c = _app(fake, monkeypatch, None)
    r = c.post("/my/directory/me", data={"listed": "yes"}, headers=ORIGIN, follow_redirects=False)
    assert r.headers["location"] == "/my" and not fake.patches


# ─── 3. hidden fields stay hidden ────────────────────────────────────


def test_a_field_nobody_turned_on_is_never_sent(fake, monkeypatch):
    fake.turn_on()
    fake.add(ANA, "Ana Rivers")
    fake.add(BEN, "Ben Rivers", phone="(555) 777-1111", email="ben@secret.example", directory=_yes())
    fake.add(CARA, "Cara Stone", phone="555-222-3333", email="cara@show.example", directory=_yes(email=True))
    fake.add(DEV, "Dev Hart", phone="555-444-5555", email="dev@secret.example", directory=_yes(phone=True))
    v = md.view(fake.business(), ANA)
    by = {p["name"]: p for p in _people(v)}
    assert "phone" not in by["Ben Rivers"] and "email" not in by["Ben Rivers"]
    assert by["Cara Stone"]["email"] == "cara@show.example" and "phone" not in by["Cara Stone"]
    assert by["Dev Hart"]["phone"] == "555-444-5555" and "email" not in by["Dev Hart"]
    page = _app(fake, monkeypatch, ANA).get("/my/directory").text
    for secret in ("777-1111", "ben@secret.example", "222-3333", "dev@secret.example"):
        assert secret not in page
    assert "cara@show.example" in page and 'href="tel:5554445555"' in page


def test_a_household_shows_together_only_when_each_adult_chose_it(fake):
    fake.turn_on()
    fake.houses[H1] = {"business_id": BIZ, "name": "The Rivers"}
    for i in (ANA, BEN, CARA):
        fake.house_adults.append({"business_id": BIZ, "household_id": H1, "contact_id": i})
    fake.add(ANA, "Ana Rivers", directory=_yes(household=True))
    fake.add(BEN, "Ben Rivers", directory=_yes(household=True))
    fake.add(CARA, "Cara Rivers", directory=_yes())             # listed, household off
    fake.add(DEV, "Dev Hart")
    v = md.view(fake.business(), DEV)
    rivers = [c for c in v["cards"] if c["household"]]
    assert len(rivers) == 1 and rivers[0]["title"] == "The Rivers"
    assert [p["name"] for p in rivers[0]["people"]] == ["Ana Rivers", "Ben Rivers"]
    alone = [c for c in v["cards"] if not c["household"]]
    assert [c["title"] for c in alone] == ["Cara Rivers"]
    # One adult alone who chose household shows nothing about the household.
    fake.contacts[BEN]["metadata"]["directory"]["household"] = False
    v = md.view(fake.business(), DEV)
    assert not any(c["household"] for c in v["cards"]) and "The Rivers" not in json.dumps(v)
    # The cards themselves group only those who chose it, whatever is known.
    rows = [dict(fake.contacts[i], directory=fake.contacts[i]["metadata"]["directory"]) for i in (ANA, BEN, CARA)]
    out = md.cards(rows, house_of={ANA: H1, BEN: H1, CARA: H1}, house_names={H1: "The Rivers"}, me_id=DEV,
                   can_message=set())
    assert [c["household"] for c in out] == [False, False, False]


def test_search_by_name_finds_the_household(fake):
    fake.turn_on()
    fake.houses[H1] = {"business_id": BIZ, "name": "The Rivers"}
    for i in (ANA, BEN):
        fake.house_adults.append({"business_id": BIZ, "household_id": H1, "contact_id": i})
    fake.add(ANA, "Ana Rivers", directory=_yes(household=True))
    fake.add(BEN, "Ben Rivers", directory=_yes(household=True))
    fake.add(CARA, "Cara Stone", directory=_yes())
    v = md.view(fake.business(), CARA, q="ben")
    assert [c["title"] for c in v["cards"]] == ["The Rivers"] and v["found"] == 2 and v["count"] == 3
    assert md.view(fake.business(), CARA, q="  STONE ")["found"] == 1
    assert md.view(fake.business(), CARA, q="nobody")["cards"] == []


# ─── 4. minors ───────────────────────────────────────────────────────


def test_minors_are_never_listed(fake):
    fake.turn_on()
    fake.add(ANA, "Ana Rivers")
    fake.add(BEN, "Ben Teen", birthdate=TEEN, directory=_yes(phone=True))            # under 18
    # Each flag keeps a person out even when the record's birthdate says adult.
    fake.add(CARA, "Cara Child", directory=_yes())                                   # a child on a family
    fake.children.append({"business_id": BIZ, "contact_id": CARA})
    fake.add(DEV, "Dev Linked", directory=_yes())                                    # a teen linked to a parent
    fake.guardians.append({"business_id": BIZ, "teen_contact_id": DEV})
    fake.add(ELI, "Eli Tagged", tags=[" Youth "], directory=_yes())                  # tagged by the office
    fake.add(FAY, "Fay Leader", tags=["Youth leader"], directory=_yes())             # an adult who leads youth
    fake.add(GUS, "Gus Nodate", birthdate=None, directory=_yes())                    # no birthdate: could be a child
    v = md.view(fake.business(), ANA)
    assert _names(v) == ["Fay Leader"]
    # The office sees why they're not shown.
    out = md.office_view(fake.business(), can_switch=True)
    hidden = {p["name"]: p["hidden"] for p in out["listed"]}
    assert hidden == {"Ben Teen": "under_18", "Cara Child": "under_18", "Dev Linked": "under_18",
                      "Eli Tagged": "under_18", "Fay Leader": "", "Gus Nodate": "no_birthdate"}
    assert out["shown"] == 1


def test_a_minor_cant_join_or_see_it(fake, monkeypatch):
    fake.turn_on()
    fake.add(ANA, "Ana Rivers", directory=_yes())
    fake.add(BEN, "Ben Teen", birthdate=TEEN)
    assert md.save_choice(BIZ, BEN, _yes()) == "dir_adults"
    assert "directory" not in fake.contacts[BEN]["metadata"]
    assert md.view(fake.business(), BEN)["state"] == "minor"
    # A teen is always in Youth, where the directory isn't.
    r = _app(fake, monkeypatch, BEN).get("/my/directory", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/my"
    assert md.details_block(fake.business(), BEN) == ""
    # A child on a family with no birthdate is in Church, and still sees nobody.
    fake.add(DEV, "Dev Child", birthdate=None)
    fake.children.append({"business_id": BIZ, "contact_id": DEV})
    page = _app(fake, monkeypatch, DEV).get("/my/directory").text
    assert "Ana Rivers" not in page and "for adults" in page
    assert md.details_block(fake.business(), DEV) == ""
    # With no birthdate on record nobody is listed (they could be a child),
    # but they may look, and are told what the office needs.
    fake.add(CARA, "Cara Nodate", birthdate=None)
    assert md.save_choice(BIZ, CARA, _yes()) == "dir_birthdate"
    assert "directory" not in fake.contacts[CARA]["metadata"]
    v = md.view(fake.business(), CARA)
    assert v["state"] == "ok" and _names(v) == ["Ana Rivers"] and v["can_join"] is False
    page = _app(fake, monkeypatch, CARA).get("/my/directory").text
    assert "needs your birthdate" in page and 'name="listed" value="yes"' not in page
    block = md.details_block(fake.business(), CARA)
    assert "needs your birthdate" in block and 'name="listed" value="yes"' not in block
    # A listed adult's photo shows.
    fake.contacts[ANA]["metadata"]["member_photo"] = {"path": f"{BIZ}/member-photos/x/1.webp", "v": "1"}
    p = {x["name"]: x for x in _people(md.view(fake.business(), CARA))}["Ana Rivers"]
    assert p["photo"].startswith(f"/my/photo/{ANA}?v=")


# ─── 5. other churches ───────────────────────────────────────────────


def test_another_churchs_people_never_show(fake):
    fake.turn_on()
    fake.add(ANA, "Ana Rivers", directory=_yes(phone=True), phone="555-000-1111")
    fake.add(STRANGER, "Sam Elsewhere", biz=OTHER, directory=_yes(phone=True, email=True), phone="555-999-0000")
    assert _names(md.view(fake.business(), ANA)) == ["Ana Rivers"]
    assert _names(md.view(fake.business(OTHER), STRANGER)) == ["Sam Elsewhere"]
    # Someone from another church isn't a person here: no view, no write.
    assert md.view(fake.business(), STRANGER)["state"] == "error"
    assert md.save_choice(BIZ, STRANGER, {"listed": False}) == "gone"
    assert md.office_remove(BIZ, STRANGER, "Not ours", "owner") == "gone"
    assert fake.contacts[STRANGER]["metadata"]["directory"]["listed"] is True
    # Every read is scoped to the church.
    for path in fake.reads:
        if not path.startswith("/businesses"):
            assert "business_id=eq." in path, path


def test_another_churchs_office_is_refused(fake, monkeypatch):
    import business_access
    fake.turn_on()
    fake.add(ANA, "Ana Rivers", directory=_yes())

    def no_role(b, user, min_role="viewer"):
        raise HTTPException(404, "business not found")
    monkeypatch.setattr(business_access, "assert_access", no_role)
    outsider = SimpleNamespace(id="other-owner", email="o@example.com")
    for call in (lambda: md.get_directory(BIZ, outsider),
                 lambda: md.remove_from_directory(BIZ, {"contact_id": ANA, "reason": "spam"}, outsider),
                 lambda: md.restore_to_directory(BIZ, {"contact_id": ANA}, outsider)):
        with pytest.raises(HTTPException) as e:
            call()
        assert e.value.status_code == 404
    assert not fake.patches


# ─── 6. the switch ───────────────────────────────────────────────────


def test_only_the_owner_flips_the_switch(fake, monkeypatch):
    monkeypatch.setattr(mp.sb_clients, "sb_get_as_service", fake.get)
    import business_access
    monkeypatch.setattr(business_access, "assert_access", lambda b, u, r="viewer": "admin")
    admin = SimpleNamespace(id="an-admin", email="admin@example.com")
    with pytest.raises(HTTPException) as e:
        md.switch_directory(BIZ, {"on": True}, admin)
    assert e.value.status_code == 403 and not fake.patches
    # An admin seat sees the list, and is told it can't switch.
    assert md.get_directory(BIZ, admin)["can_switch"] is False
    owner = SimpleNamespace(id="owner", email="pastor@example.com")
    with pytest.raises(HTTPException) as e:
        md.switch_directory(BIZ, {"on": "yes"}, owner)
    assert e.value.status_code == 400
    out = md.switch_directory(BIZ, {"on": True}, owner)
    assert out["on"] is True and out["can_switch"] is True
    cfg = fake.biz[BIZ]["settings"]["member_portal"]
    assert cfg["directory"]["on"] is True and cfg["enabled"] is True
    assert md.church_on(fake.business())


def test_the_tab_is_offered_only_while_its_on(fake, monkeypatch):
    monkeypatch.setattr(mp.sb_clients, "sb_get_as_service", fake.get)
    owner = SimpleNamespace(id="owner", email="pastor@example.com")
    md.switch_directory(BIZ, {"on": True}, owner)
    biz = fake.business()
    assert {c["key"]: c for c in ui.tab_choices(biz)}["directory"]["ready"]
    assert "/my/directory" in mpc.connect_tabs(biz, "groups")
    fake.biz[BIZ]["settings"]["member_portal"]["tabs"] = ["home", "directory", "give"]
    on = fake.business()
    assert [t[0] for t in ui.church_tabs(on)] == ["home", "directory", "give"]
    assert 'aria-current="page"' in re.search(r'href="/my/directory"[^>]*', ui.nav("directory", biz=on)).group(0)
    # Turning it off takes it off the bar, so the tab never leads nowhere.
    md.switch_directory(BIZ, {"on": False}, owner)
    cfg = fake.biz[BIZ]["settings"]["member_portal"]
    assert cfg["tabs"] == ["home", "give"] and not md.church_on(fake.business())
    assert "directory" not in mp._tabs_payload(fake.business())["tabs"]
    # And a bar saved while it's off doesn't keep it.
    fake.biz[BIZ]["settings"]["member_portal"]["tabs"] = ["home", "directory", "give"]
    assert "directory" not in mp._tabs_payload(fake.business())["tabs"]


def test_a_saved_bar_drops_the_directory_while_its_off(fake, monkeypatch):
    monkeypatch.setattr(mp.sb_clients, "sb_get_as_service", fake.get)
    monkeypatch.setattr(mp.sb_clients, "sb_patch_as_service", fake.patch)
    import business_sites_helpers
    monkeypatch.setattr(business_sites_helpers, "ensure_business_site",
                        lambda biz: ({"slug": "love-city", "site_config": {}}, False))
    owner = SimpleNamespace(id="owner", email="pastor@example.com")
    mp.patch_member_portal_config(BIZ, {"tabs": ["home", "directory", "events", "give"]}, owner)
    assert fake.biz[BIZ]["settings"]["member_portal"]["tabs"] == ["home", "events", "give"]
    fake.turn_on()
    out = mp.patch_member_portal_config(BIZ, {"tabs": ["home", "directory", "events", "give"]}, owner)
    assert out["tabs"] == ["home", "directory", "events", "give"]


def test_the_office_routes_need_a_signed_in_user():
    app = FastAPI()
    app.include_router(md.router)
    c = TestClient(app)
    assert c.get(f"/member-portal/{BIZ}/directory").status_code in (401, 403)
    assert c.put(f"/member-portal/{BIZ}/directory", json={"on": True}).status_code in (401, 403)
    assert c.post(f"/member-portal/{BIZ}/directory/remove", json={"contact_id": ANA, "reason": "x"}).status_code in (401, 403)


# ─── 7. taken out stays out ──────────────────────────────────────────


def test_a_member_the_office_took_out_stays_out(fake, monkeypatch):
    fake.turn_on()
    fake.add(ANA, "Ana Rivers", directory=_yes(phone=True), phone="555-123-4567")
    fake.add(BEN, "Ben Rivers")
    owner = SimpleNamespace(id="owner", email="pastor@example.com")
    with pytest.raises(HTTPException) as e:
        md.remove_from_directory(BIZ, {"contact_id": ANA, "reason": " "}, owner)
    assert e.value.status_code == 400                                       # a reason is needed
    out = md.remove_from_directory(BIZ, {"contact_id": ANA, "reason": "Asked us to   take her off"}, owner)
    assert out["removed"] == [{"id": ANA, "name": "Ana Rivers", "reason": "Asked us to take her off",
                               "at": out["removed"][0]["at"]}] and out["listed"] == []
    assert md.view(fake.business(), BEN)["count"] == 0
    # She can't put herself back, and sees why.
    assert md.save_choice(BIZ, ANA, _yes()) == "dir_removed"
    assert md.view(fake.business(), BEN)["count"] == 0
    v = md.view(fake.business(), ANA)
    assert v["state"] == "removed" and v["cards"] == []
    page = _app(fake, monkeypatch, ANA).get("/my/directory").text
    assert "Asked us to take her off" in page and "Ben Rivers" not in page
    assert "Asked us to take her off" in md.details_block(fake.business(), ANA)
    # Taking herself out still works, and keeps the office's word.
    assert md.save_choice(BIZ, ANA, {"listed": False}) == "dir_saved"
    assert fake.contacts[ANA]["metadata"]["directory"]["removed"]["reason"] == "Asked us to take her off"
    # The office lets her back: she isn't listed until she says yes again.
    out = md.restore_to_directory(BIZ, {"contact_id": ANA}, owner)
    assert out["removed"] == [] and out["listed"] == []
    assert md.save_choice(BIZ, ANA, _yes()) == "dir_on"
    assert _names(md.view(fake.business(), BEN)) == ["Ana Rivers"]


def test_a_reason_in_the_data_is_never_a_listing(fake):
    # Even a record that says listed with a removal on it stays out.
    fake.turn_on()
    fake.add(ANA, "Ana Rivers", directory={**_yes(), "removed": {"reason": "No", "at": "x"}})
    fake.add(BEN, "Ben Rivers")
    assert md.view(fake.business(), BEN)["count"] == 0


# ─── visitors, and messages ──────────────────────────────────────────


def test_visitors_arent_listed_and_dont_see_it(fake, monkeypatch):
    fake.turn_on()
    fake.add(ANA, "Ana Rivers", directory=_yes())
    fake.add(BEN, "Ben Visitor", status="lead", directory=_yes())
    fake.add(CARA, "Cara Guest", status="lead")
    fake.add(DEV, "Dev Gone", status="churned", directory=_yes())
    fake.add(ELI, "Eli Vip", status="vip", directory=_yes())
    assert _names(md.view(fake.business(), ANA)) == ["Ana Rivers", "Eli Vip"]
    assert md.view(fake.business(), CARA)["state"] == "not_member"
    assert md.save_choice(BIZ, CARA, _yes()) == "dir_members"
    page = _app(fake, monkeypatch, CARA).get("/my/directory").text
    assert "Ana Rivers" not in page and "for members" in page


def test_reaching_someone_goes_through_member_messages(fake, monkeypatch):
    fake.turn_on()
    fake.add(ANA, "Ana Rivers")
    fake.add(BEN, "Ben Rivers", directory=_yes())
    fake.add(CARA, "Cara Stone", directory=_yes())
    fake.msg_members.update({BEN: True, CARA: False})
    v = md.view(fake.business(), ANA)
    assert not any(p["message"] for p in _people(v))                       # messaging off: nothing to tap
    fake.messaging = True
    fake.turn_on()
    v = md.view(fake.business(), ANA)
    by = {p["name"]: p for p in _people(v)}
    assert by["Ben Rivers"]["message"] and not by["Cara Stone"]["message"]
    page = _app(fake, monkeypatch, ANA).get("/my/directory").text
    assert f'href="/my/messages/to/{BEN}"' in page and f"/my/messages/to/{CARA}" not in page
    # Never a button to message yourself.
    md.save_choice(BIZ, ANA, _yes())
    fake.msg_members[ANA] = True
    me = {p["name"]: p for p in _people(md.view(fake.business(), ANA))}["Ana Rivers"]
    assert me["me"] and not me["message"]


def test_a_failed_read_shows_nothing(fake, monkeypatch):
    fake.turn_on()
    fake.add(ANA, "Ana Rivers")
    fake.add(BEN, "Ben Rivers", directory=_yes())
    real = fake.get
    monkeypatch.setattr(md.sb_clients, "sb_get_as_service",
                        lambda p, **kw: None if p.startswith("/msg_guardians") else real(p))
    v = md.view(fake.business(), ANA)
    assert v["state"] == "error" and v["cards"] == []
    html, status = md.render_page(fake.business(), {}, _request(), {"id": ANA, "name": "Ana Rivers"}, v)
    assert status == 503 and "Ben Rivers" not in html


# ─── the page, end to end ────────────────────────────────────────────


def _request(query: str = ""):
    return Request({"type": "http", "method": "GET", "path": "/my/directory", "query_string": query.encode(),
                    "headers": [], "server": (HOST, 443), "scheme": "https"})


def _app(fake, monkeypatch, me_id, space=""):
    """The church's address with `me_id` signed in (None: signed out),
    in the space they switched to (an approved Youth leader, a parent)."""
    monkeypatch.setenv("CUSTOMER_TOKEN_SECRET", "test-root-secret")
    monkeypatch.setattr(mp, "_church_for_request", lambda req: {"business": fake.business(), "site": {}})
    import rate_limit
    monkeypatch.setattr(rate_limit, "allow_strict", lambda b, k: True)

    def session(request, church):
        if not me_id:
            return None
        row = dict(fake.contacts[me_id])
        return {"claims": {}, "people": [row], "me": row}
    monkeypatch.setattr(mp, "_session_for", session)
    import member_spaces as msp

    async def resolve(b, me, wanted=""):
        return msp._placed(me, space, {"youth": {}} if space == "youth" else {}, space == "kids")
    monkeypatch.setattr(msp, "resolve_async", resolve)

    async def leads(*a, **kw):
        return False
    monkeypatch.setattr(mp, "_leads", leads)
    app = FastAPI()
    app.include_router(md.router)

    @app.get("/my/{rest:path}")
    async def page(request: Request, rest: str):
        return await mp.serve(request, "/my/" + rest)
    return TestClient(app, base_url=f"https://{HOST}")


def test_the_page_on_a_phone(fake, monkeypatch):
    fake.turn_on()
    fake.add(ANA, "Ana Rivers", directory=_yes())
    fake.add(BEN, "Ben Rivers", directory=_yes(email=True), email="ben@example.com")
    page = _app(fake, monkeypatch, ANA).get("/my/directory").text
    assert "<h1>Directory</h1>" in page and 'type="search"' in page and "2 people" in page
    assert "You're in the directory." in page and "Show me in the directory" not in page
    assert 'name="viewport"' in page and "Only signed-in members of Love City Church see this" in page
    # It sits under Connect, beside Groups.
    assert 'href="/my/groups"' in page and re.search(r'href="/my/directory" aria-current="page"', page)
    # My details offers the choices, with what's saved ticked.
    md.save_choice(BIZ, ANA, _yes(phone=True))
    block = md.details_block(fake.business(), ANA)
    assert 'name="listed" value="yes" checked' in block and 'name="phone" value="yes" checked' in block
    assert 'name="email" value="yes">' in block and 'name="household" value="yes">' in block


def test_never_in_the_youth_or_kids_space(fake, monkeypatch):
    fake.turn_on()
    fake.add(ANA, "Ana Leader", directory=_yes())
    for space in ("youth", "kids"):
        r = _app(fake, monkeypatch, ANA, space).get("/my/directory", follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/my", space
    assert _app(fake, monkeypatch, ANA, "church").get("/my/directory").status_code == 200


def test_signed_out_never_sees_it(fake, monkeypatch):
    fake.turn_on()
    fake.add(ANA, "Ana Rivers", directory=_yes())
    r = _app(fake, monkeypatch, None).get("/my/directory", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/my"
