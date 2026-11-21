"""An event's flyer (event_volunteers PUT/DELETE /{entry_id}/flyer and every
reader through flyer_of; docs/EVENT_VOLUNTEERS.md 6.12, step S3).

Pins, each one broken on purpose once to see it go red:
  * the gate: an office login that may ask, with the switch open; a Viewer is
    a 403, another church's event or picture a 404
  * each limit (10 MB, 8000 px a side, JPG, PNG or WebP) is a plain 400
  * an upload goes through image_studio (normalize_image, its own store, an
    image_artworks row in the owner's name), then two copies: the full one at
    most 1600 px on its long side, the thumb 480 px wide, RGB JPEGs with no
    EXIF, at {business}/event-flyers/{entry}/{artwork}.jpg and -thumb.jpg in
    business-assets
  * the whole new data comes back
  * every reader shows a valid flyer and drops one that isn't (another
    church's folder, http, a query string, a size that isn't a whole number)
  * a church-only event's flyer never reaches the public page"""
from __future__ import annotations

import asyncio
import copy
import io
import os
import sys
from datetime import date, timedelta

import pytest
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (ROOT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import event_volunteers as evv  # noqa: E402
import image_studio  # noqa: E402
import member_portal_church as mpc  # noqa: E402
import sunday_serving as sv  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from test_event_volunteers import BIZ, E_LOCK, E_THEIRS, MOD, NOW, OTHER, ask, church  # noqa: E402,F401
from test_sunday_planning import JO, ZONE  # noqa: E402
from test_church_week import THU, app, db, week  # noqa: E402,F401

BASE = "https://proj.supabase.co"
PUBLIC = f"{BASE}/storage/v1/object/public/business-assets"
ART = "a7700000-0000-4000-8000-000000000001"
THEIR_ART = "a7700000-0000-4000-8000-000000000002"
LATE_ART = "a7700000-0000-4000-8000-000000000003"
E_SOON, E_CHURCH = "e2000000-0000-4000-8000-000000000001", "e2000000-0000-4000-8000-000000000002"


def picture(w=2000, h=1000, kind="JPEG", exif=True, turn=None) -> bytes:
    im = Image.new("RGB", (w, h), (200, 40, 40))
    buf = io.BytesIO()
    kw = {}
    if kind == "JPEG" and (exif or turn):
        x = Image.Exif()
        x[0x010F] = "Phone maker"
        x[0x8298] = "A secret in the EXIF"
        if turn:
            x[0x0112] = turn
        kw["exif"] = x.tobytes()
    im.save(buf, kind, **kw)
    return buf.getvalue()


def flyer(biz=BIZ, eid=E_LOCK, art=ART, **change):
    f = {"artwork_id": art, "url": f"{PUBLIC}/{biz}/event-flyers/{eid}/{art}.jpg",
         "thumb": f"{PUBLIC}/{biz}/event-flyers/{eid}/{art}-thumb.jpg", "w": 1600, "h": 800, "at": NOW.isoformat()}
    f.update(change)
    return f


BAD = {
    "another church's folder": flyer(biz=OTHER),
    "http": flyer(url=f"http://proj.supabase.co/storage/v1/object/public/business-assets/{BIZ}/event-flyers/x.jpg"),
    "a query string": flyer(thumb=flyer()["thumb"] + "?w=9999"),
    "a size that isn't a whole number": flyer(w="1600"),
    "a size past 8000": flyer(h=8001),
    "a way out of the folder": flyer(url=f"{PUBLIC}/{BIZ}/event-flyers/../../{OTHER}/x.jpg"),
}


@pytest.fixture
def fly(church, monkeypatch):
    c = church
    monkeypatch.setenv("SUPABASE_URL", BASE)
    c.db.t["image_artworks"] = [
        {"id": ART, "business_id": BIZ, "owner_id": "u-owner", "status": "ready", "storage_path": f"{BIZ}/{ART}.png"},
        {"id": THEIR_ART, "business_id": OTHER, "owner_id": "u-else", "status": "ready",
         "storage_path": f"{OTHER}/{THEIR_ART}.png"},
        {"id": LATE_ART, "business_id": BIZ, "owner_id": "u-owner", "status": "working", "storage_path": None},
    ]
    stored, made = {}, []
    png = io.BytesIO()
    Image.new("RGBA", (1200, 1800), (10, 120, 200, 255)).save(png, "PNG")
    stored[("image-originals", f"{BIZ}/{ART}.png")] = (png.getvalue(), "image/png")

    async def store(client, path, content, mime, bucket=image_studio.BUCKET):
        assert image_studio.build_actor.get() == {"business_id": BIZ, "user_id": "u-owner"}, "as the owner, set here"
        stored[(bucket, path)] = (content, mime)

    async def db(client, method, path, body=None, *, server_write=False):
        assert (method, path, server_write) == ("POST", "/image_artworks", True)
        made.append(body)
        c.db.t["image_artworks"].append(dict(body))
        return [dict(body)]

    async def original(client, row):
        assert row["storage_path"].startswith(BIZ + "/")
        return stored[("image-originals", row["storage_path"])][0]
    monkeypatch.setattr(image_studio, "store", store)
    monkeypatch.setattr(image_studio, "db", db)
    monkeypatch.setattr(image_studio, "original", original)
    c.stored, c.made = stored, made
    return c


def put(c, raw=None, who="owner", eid=E_LOCK, art=None, biz=BIZ, name="flyer.jpg", mime="image/jpeg"):
    path = f"/church/event-volunteers/{eid}/flyer"
    if art is not None:
        return c.as_(who).put(path, json={"business_id": biz, "artwork_id": art})
    return c.as_(who).put(path, data={"business_id": biz}, files={"file": (name, raw, mime)})


def entry(c, eid=E_LOCK):
    return next(e for e in c.db.t["module_entries"] if e["id"] == eid)


def copies(c):
    return {path: content for (bucket, path), (content, mime) in c.stored.items()
            if bucket == "business-assets"}


# ─── the routes ──────────────────────────────────────────────────────


def test_an_upload_lands_in_the_gallery_and_as_two_plain_jpegs(fly):
    c = fly
    r = put(c, picture(2000, 1000))
    assert r.status_code == 200, r.text
    body = r.json()
    art = c.made[0]["id"]
    assert c.made == [{"id": art, "business_id": BIZ, "owner_id": "u-owner", "prompt": "Flyer: Youth Lock-in",
                       "status": "ready", "storage_path": f"{BIZ}/{art}.png", "cost_usd": 0}], \
        "an image_artworks row in the owner's name: the gallery and the Light Table"
    assert ("image-originals", f"{BIZ}/{art}.png") in c.stored
    full_path = f"{BIZ}/event-flyers/{E_LOCK}/{art}.jpg"
    thumb_path = f"{BIZ}/event-flyers/{E_LOCK}/{art}-thumb.jpg"
    got = copies(c)
    assert set(got) == {full_path, thumb_path}
    assert all(c.stored[("business-assets", p)][1] == "image/jpeg" for p in got)
    with Image.open(io.BytesIO(got[full_path])) as im:
        assert (im.format, im.mode, im.size) == ("JPEG", "RGB", (1600, 800))
        assert dict(im.getexif()) == {} and "exif" not in im.info, "EXIF stripped"
    with Image.open(io.BytesIO(got[thumb_path])) as im:
        assert (im.format, im.size) == ("JPEG", (480, 240)) and dict(im.getexif()) == {}
    want = {"artwork_id": art, "url": f"{PUBLIC}/{full_path}", "thumb": f"{PUBLIC}/{thumb_path}", "w": 1600, "h": 800}
    assert {k: body["data"]["_flyer"][k] for k in want} == want and body["data"]["_flyer"]["at"]
    assert body["flyer"] == {"url": want["url"], "thumb": want["thumb"], "w": 1600, "h": 800}
    # The whole data comes back, so the form saves on top of it.
    assert body["data"]["title"] == "Youth Lock-in" and body["data"]["_roles"][0]["id"] == "chap"
    assert entry(c)["data"] == body["data"]


def test_a_phone_photo_is_turned_upright_and_a_small_one_isnt_made_bigger(fly):
    c = fly
    assert put(c, picture(1000, 600, turn=6)).status_code == 200
    art = c.made[0]["id"]
    with Image.open(io.BytesIO(copies(c)[f"{BIZ}/event-flyers/{E_LOCK}/{art}.jpg"])) as im:
        assert im.size == (600, 1000), "EXIF orientation 6: turned, then dropped"
    with Image.open(io.BytesIO(copies(c)[f"{BIZ}/event-flyers/{E_LOCK}/{art}-thumb.jpg"])) as im:
        assert im.size == (480, 800)
    c.stored.clear()
    assert put(c, picture(300, 200, kind="PNG")).status_code == 200
    art = c.made[1]["id"]
    with Image.open(io.BytesIO(copies(c)[f"{BIZ}/event-flyers/{E_LOCK}/{art}-thumb.jpg"])) as im:
        assert im.size == (300, 200)


def test_a_picture_from_the_gallery_attaches_without_a_second_row(fly):
    c = fly
    r = put(c, art=ART)
    assert r.status_code == 200, r.text
    assert c.made == []
    assert set(copies(c)) == {f"{BIZ}/event-flyers/{E_LOCK}/{ART}.jpg", f"{BIZ}/event-flyers/{E_LOCK}/{ART}-thumb.jpg"}
    with Image.open(io.BytesIO(copies(c)[f"{BIZ}/event-flyers/{E_LOCK}/{ART}.jpg"])) as im:
        assert im.size == (1067, 1600) and im.mode == "RGB", "the long side at most 1600"
    assert r.json()["data"]["_flyer"]["artwork_id"] == ART
    # Again: the same addresses, replaced.
    assert put(c, art=ART).status_code == 200 and len(copies(c)) == 2


def test_take_it_off(fly):
    c = fly
    put(c, art=ART)
    r = c.as_("owner").delete(f"/church/event-volunteers/{E_LOCK}/flyer?business_id={BIZ}")
    assert r.status_code == 200 and "_flyer" not in r.json()["data"] and r.json()["flyer"] is None
    assert "_flyer" not in entry(c)["data"] and entry(c)["data"]["title"] == "Youth Lock-in"
    assert any(a["id"] == ART for a in c.db.t["image_artworks"]), "the picture stays in the gallery"


def test_the_gate(fly, monkeypatch):
    c = fly
    assert put(c, art=ART, who="viewer").status_code == 403
    assert c.as_("viewer").delete(f"/church/event-volunteers/{E_LOCK}/flyer?business_id={BIZ}").status_code == 403
    assert put(c, art=ART, who="outsider").status_code == 403
    assert put(c, art=ART, who="stranger").status_code == 404
    r = put(c, art=THEIR_ART)
    assert r.status_code == 404 and "gallery" in r.json()["detail"], "another church's picture"
    assert put(c, art="not-a-uuid").status_code == 404
    assert put(c, art=LATE_ART).status_code == 409
    assert put(c, art=ART, eid=E_THEIRS).status_code == 404, "another church's event"
    assert put(c, art=ART, who="shapretta").status_code == 200, "any office login that may ask"
    monkeypatch.setenv("EVENT_VOLUNTEERS", "off")
    assert put(c, art=ART).status_code == 404
    assert c.as_("owner").delete(f"/church/event-volunteers/{E_LOCK}/flyer?business_id={BIZ}").status_code == 404
    assert copies(c) and len(copies(c)) == 2


LIMITS = {
    "more than 10 MB": lambda: picture(100, 100, kind="PNG") + bytes(10 * 1024 * 1024),   # a real PNG, padded
    "more than 8000 px a side": lambda: picture(8001, 10, kind="PNG"),
    "a GIF": lambda: picture(40, 40, kind="GIF"),
    "not a picture": lambda: b"this is not a picture at all",
    "nothing": lambda: b"",
}


@pytest.mark.parametrize("what", list(LIMITS))
def test_each_limit_is_a_plain_400(fly, what):
    c = fly
    r = put(c, LIMITS[what]())
    assert r.status_code == 400, what
    assert r.json()["detail"] in (evv.NOT_A_FLYER, "Choose a picture at most 8000 pixels on a side.",
                                  "Choose a picture to upload.")
    assert c.made == [] and copies(c) == {} and "_flyer" not in entry(c)["data"]


def test_a_picture_normalize_image_refuses_is_a_plain_400(fly, monkeypatch):
    c = fly

    def refuse(raw):
        raise HTTPException(422, "That file is not a supported image.")
    monkeypatch.setattr(image_studio, "normalize_image", refuse)
    r = put(c, picture(100, 100))
    assert r.status_code == 400 and r.json()["detail"] == evv.NOT_A_FLYER


def test_no_file_and_no_artwork_is_a_400(fly):
    c = fly
    r = c.as_("owner").put(f"/church/event-volunteers/{E_LOCK}/flyer", json={"business_id": BIZ})
    assert r.status_code == 400 and "gallery" in r.json()["detail"]


# ─── the one validator ───────────────────────────────────────────────


def test_flyer_of_takes_only_this_churchs_own_folder(fly):
    assert evv.flyer_of({"_flyer": flyer()}, BIZ) == {k: flyer()[k] for k in ("url", "thumb", "w", "h")}
    for why, bad in BAD.items():
        assert evv.flyer_of({"_flyer": bad}, BIZ) is None, why
    assert evv.flyer_of({"_flyer": "x"}, BIZ) is None and evv.flyer_of({}, BIZ) is None


# ─── every reader ────────────────────────────────────────────────────


def _soon(days=14):
    return (date.today() + timedelta(days=days)).isoformat() + "T18:00"


@pytest.fixture
def readers(fly):
    """Two events still to come by the real calendar (the member app and
    the public page read date.today()): a public one and a church-only one."""
    c = fly
    c.db.t["module_entries"] += [
        {"id": E_SOON, "business_id": BIZ, "module_id": MOD, "status": "active", "created_at": NOW.isoformat(),
         "data": {"title": "Fall festival", "date": _soon(), "location": "The lot", "_flyer": flyer(eid=E_SOON)}},
        {"id": E_CHURCH, "business_id": BIZ, "module_id": MOD, "status": "active", "created_at": NOW.isoformat(),
         "data": {"title": "Leaders dinner", "date": _soon(15), "_visibility": "private",
                  "_flyer": flyer(eid=E_CHURCH, art=THEIR_ART)}},
    ]
    c.db.t["businesses"][0]["settings"] = {"events_public": {"enabled": True}}
    return c


def _public_page(c, monkeypatch, query=""):
    import public_site

    async def service(client, path):
        return c.db.get(path)
    monkeypatch.setattr(public_site, "_sb_service", service)
    import church_event_signups
    monkeypatch.setattr(church_event_signups, "annotate", lambda biz, occ, contact_id=None: occ)
    got = asyncio.run(public_site._serve_events_page(None, BIZ, "lovecity", query=query))
    return got.body.decode()


def test_the_public_page_shows_a_public_events_flyer_and_never_a_church_only_one(readers, monkeypatch):
    c = readers
    html = _public_page(c, monkeypatch)
    assert flyer(eid=E_SOON)["thumb"] in html and 'class="ev-flyer"' in html
    assert flyer(eid=E_CHURCH, art=THEIR_ART)["thumb"] not in html and "Leaders dinner" not in html
    assert f'property="og:image" content="{flyer(eid=E_SOON)["url"]}"' not in html, "the page of every event"
    one = _public_page(c, monkeypatch, f"event={E_SOON}")
    assert f'<meta property="og:image" content="{flyer(eid=E_SOON)["url"]}">' in one
    assert '<meta property="og:title" content="Fall festival">' in one
    assert flyer(eid=E_CHURCH, art=THEIR_ART)["url"] not in _public_page(c, monkeypatch, f"event={E_CHURCH}")
    for why, bad in BAD.items():
        entry(c, E_SOON)["data"]["_flyer"] = bad
        html = _public_page(c, monkeypatch, f"event={E_SOON}")
        assert 'class="ev-flyer"' not in html and str(bad["thumb"]) not in html, why


def test_the_member_app_shows_it_in_both_looks_only_where_the_event_shows(readers):
    c = readers
    me = {"id": JO, "name": "Jo Park", "email": ""}
    occ = {o["entry_id"]: o for o in mpc.upcoming_for(BIZ, me)}
    assert occ[E_SOON]["flyer"]["thumb"] == flyer(eid=E_SOON)["thumb"]
    assert E_CHURCH not in occ, "church-only: not on a member's own page either (can_see)"
    for render in (lambda o: mpc.occasion_card(o, "/my/events"), mpc._lumen_occasion,
                   lambda o: mpc.coming_up([o])):
        assert flyer(eid=E_SOON)["thumb"] in render(occ[E_SOON])
    for why, bad in BAD.items():
        entry(c, E_SOON)["data"]["_flyer"] = bad
        o = {x["entry_id"]: x for x in mpc.upcoming_for(BIZ, me)}[E_SOON]
        assert o["flyer"] is None, why
        assert "mp-flyer" not in mpc.occasion_card(o, "/my/events") and "lm-evflyer" not in mpc._lumen_occasion(o)


def test_my_serving_and_the_office_show_an_event_dates_flyer(readers):
    c = readers
    r = ask(c, "owner", E_LOCK, {c.greeter: 1})
    sid = r.json()["date"]["id"]
    entry(c)["data"]["_flyer"] = flyer()
    want = {"thumb": flyer()["thumb"], "url": flyer()["url"]}
    got = sv._services(BIZ, ZONE, NOW, NOW + timedelta(days=30), flyers=True)[sid]["flyer"]
    assert {k: got[k] for k in want} == want
    assert "flyer" not in sv._services(BIZ, ZONE, NOW, NOW + timedelta(days=30))[sid], "only My serving reads it"
    sched = c.as_("owner").get(f"/planning/schedule?business_id={BIZ}&weeks=3").json()
    assert next(s for s in sched["services"] if s["id"] == sid)["flyer"] == want
    # The scheduler's list: an ask that waits.
    ask(c, "shapretta", E_SOON, {c.greeter: 1})
    reqs = c.as_("owner").get(f"/planning/requests?business_id={BIZ}").json()["requests"]
    assert next(x for x in reqs if x["entry_id"] == E_SOON)["flyer"] == {"thumb": flyer(eid=E_SOON)["thumb"],
                                                                       "url": flyer(eid=E_SOON)["url"]}
    import member_portal_serving as mps
    item = {"id": "a1", "service": sv._services(BIZ, ZONE, NOW, NOW + timedelta(days=30), flyers=True)[sid],
            "place": "Greeter", "team": "Welcome", "asked_by": "Dee", "asked_at": None, "from": None}
    assert flyer()["thumb"] in mps._ask_row(item)
    for why, bad in BAD.items():
        entry(c)["data"]["_flyer"] = bad
        entry(c, E_SOON)["data"]["_flyer"] = bad
        assert sv._services(BIZ, ZONE, NOW, NOW + timedelta(days=30), flyers=True)[sid]["flyer"] is None, why
        sched = c.as_("owner").get(f"/planning/schedule?business_id={BIZ}&weeks=3").json()
        assert next(s for s in sched["services"] if s["id"] == sid)["flyer"] is None, why
        reqs = c.as_("owner").get(f"/planning/requests?business_id={BIZ}").json()["requests"]
        assert next(x for x in reqs if x["entry_id"] == E_SOON)["flyer"] is None, why
        assert "sv-fly" not in mps._ask_row({**item, "service": sv._services(
            BIZ, ZONE, NOW, NOW + timedelta(days=30), flyers=True)[sid]})


def test_the_ask_page_shows_it(readers):
    c = readers
    sid = ask(c, "owner", E_LOCK, {c.greeter: 1}).json()["date"]["id"]
    entry(c)["data"]["_flyer"] = flyer()
    c.db.t["serve_assignments"].append({"id": "a5600000-0000-4000-8000-000000000001", "business_id": BIZ,
                                        "service_id": sid, "position_id": c.greeter, "slot": 1, "contact_id": JO,
                                        "status": "asked", "notified_at": NOW.isoformat(), "note": "",
                                        "swap_to": None, "asked_by": "Dee"})
    biz = c.db.t["businesses"][0]
    v = sv.ask_view(biz, JO, "a5600000-0000-4000-8000-000000000001")
    assert v["flyer"]["thumb"] == flyer()["thumb"]
    entry(c)["data"]["_flyer"] = BAD["a query string"]
    assert sv.ask_view(biz, JO, "a5600000-0000-4000-8000-000000000001")["flyer"] is None


def test_the_week_shows_an_event_dates_flyer(app, db, monkeypatch):
    """The week (church_week) on its own made-up church: Thursday's
    Outreach night is an event date."""
    monkeypatch.setenv("SUPABASE_URL", BASE)
    thu = next(s for s in db.t["worship_services"] if s["id"] == THU)
    hope, eid = thu["business_id"], "e3000000-0000-4000-8000-000000000001"
    thu["event_entry_id"] = eid
    db.t["module_entries"] = [{"id": eid, "business_id": hope, "module_id": MOD, "status": "active",
                               "data": {"title": "Outreach night", "_flyer": flyer(biz=hope, eid=eid)}}]
    want = {"thumb": flyer(biz=hope, eid=eid)["thumb"], "url": flyer(biz=hope, eid=eid)["url"]}

    def shown(body):
        return [s for c in body["departments"] for s in c["services"]]
    got = shown(week(app, "sunny"))
    assert {s.get("flyer") is not None for s in got if s["service_id"] == THU} == {True}
    assert all(s["flyer"] == want for s in got if s["service_id"] == THU)
    assert all("flyer" not in s for s in got if s["service_id"] != THU), "a Sunday reads as it did"
    for why, bad in BAD.items():
        db.t["module_entries"][0]["data"]["_flyer"] = {**bad, "url": bad["url"].replace(BIZ, hope),
                                                       "thumb": bad["thumb"].replace(BIZ, hope)}
        assert all(s["flyer"] is None for s in shown(week(app, "sunny")) if s["service_id"] == THU), why


def test_chief_keeps_a_roles_kids_and_open(fly):
    import chief_roster
    module = {"archetype_params": {}}
    before = {"title": "Youth Lock-in", "_roles": [{"id": "chap", "label": "Chaperones", "needed": 3, "kids": True},
                                                   {"id": "grill", "label": "Grill", "needed": 1, "open": True},
                                                   {"id": "set", "label": "Set up", "needed": 2, "open": False}]}
    out, said = chief_roster.shape(module, {"_roles": [{"label": "Chaperones", "needed": 5}, "Clean up"]},
                                   before=copy.deepcopy(before))
    roles = {r["id"]: r for r in out["_roles"]}
    assert roles["chap"] == {"id": "chap", "label": "Chaperones", "needed": 5, "kids": True}
    assert roles["grill"]["open"] is True and roles["set"]["open"] is False
    assert "kids" not in roles["grill"] and "open" not in roles["chap"]
    assert chief_roster.clean_roles([{"id": "x", "label": "X", "kids": "yes", "open": 1}]) == [
        {"id": "x", "label": "X", "needed": 1}], "only true or false is kept"
