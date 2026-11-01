# __tests__/test_giving_sheets.py
#
# Giving by service, step 4: the printable count sheet, and a photo of a
# filled-in sheet kept for good and read into a DRAFT (never gifts): names
# matched to the church's people only when they're one person, a line with
# cash and a check split in two, the sheet's written totals checked against
# the rows, and a photo that can't be read still kept with what went wrong.

import asyncio
import io
import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import giving_services as gs
import giving_sheets as sh
import giving_ways
from __tests__.test_giving_services import BIZ, FakeDB, USER

COUNT = "c0000000-0000-4000-8000-000000000009"
PEOPLE = [{"id": "p1", "name": "Grace Holloway"}, {"id": "p2", "name": "Marcus T. Reed"},
          {"id": "p3", "name": "Ann Lee"}, {"id": "p4", "name": "Ann Lee"}]
JPEG = b"\xff\xd8\xff\xe0" + b"0" * 64


@pytest.fixture
def db(monkeypatch):
    fake = FakeDB(businesses=[{"id": BIZ, "type": "church", "name": "Love City Church",
                               "settings": {"timezone": "America/New_York",
                                            "giving": {"funds": ["Tithes", "Building", "Missions"]}}}],
                  giving_counts=[{"id": COUNT, "business_id": BIZ, "name": "Sunday Worship", "service_date": "2026-11-01",
                                  "status": "open", "starts_at": "2026-11-01T16:00:00+00:00", "collects_online": True}],
                  giving_count_photos=[], contacts=[{**p, "business_id": BIZ} for p in PEOPLE], invoices=[])
    for mod in (gs, sh):
        monkeypatch.setattr(mod, "sb_clients", fake)
    monkeypatch.setattr(giving_ways, "switched_on", lambda b: True)
    import giving_records, church_keys
    monkeypatch.setattr(giving_records, "require_finance", lambda b, u: "owner")
    monkeypatch.setattr(gs.church_keys, "wall", lambda *a, **k: None)
    monkeypatch.setattr(sh, "_store", lambda path, raw, mt: True)
    return fake


# ─── The sheet ─────────────────────────────────────────────────────────

def test_the_sheet_names_the_service_its_funds_and_two_counters(db):
    resp = sh.count_sheet(BIZ, COUNT, USER)
    page = resp.body.decode()
    assert "Love City Church" in page and "Sunday Worship" in page and "Sunday, November 1, 2026" in page
    assert "Tithes · Building · Missions" in page
    assert page.count("Counted by (print and sign)") == 2
    assert page.count('<td class="n">') == sh.SHEET_LINES + sh.APP_LINES
    assert "Given by app (not in the plate)" in page and page.count("&#9744; Cash App") == sh.APP_LINES
    assert resp.headers["cache-control"] == "no-store"


def test_the_sheet_escapes_what_the_church_typed(db):
    db.t["giving_counts"][0]["name"] = "<script>x</script>"
    page = sh.count_sheet(BIZ, COUNT, USER).body.decode()
    assert "<script>x" not in page and "&lt;script&gt;" in page


# ─── Reading a sheet into a draft (pure) ───────────────────────────────

def test_a_draft_matches_names_splits_cash_and_check_and_checks_totals():
    got = {"readable": True, "lines": [
        {"line": 1, "name": "grace holloway", "fund": "tithes", "cash": 0, "check": 150, "check_number": "#3107"},
        {"line": 2, "name": "Marcus Reed", "fund": "", "cash": 20, "check": 50, "check_number": "88"},
        {"line": 3, "name": "Ann Lee", "fund": "Bldg", "cash": 10, "check": 0, "unsure": True},
        {"line": 4, "name": "Loose offering", "cash": 83.5, "check": 0},
        {"line": 5, "name": "Someone New", "cash": 5, "check": 0}],
        "written_cash_total": 118.5, "written_checks_total": 200, "written_total": 300,
        "counters": ["Ann Lee", " Bo Price "]}
    d = sh.draft_from(got, PEOPLE, ["Tithes", "Building", "Missions"])
    rows = d["rows"]
    assert [(r["line"], r["method"], r["amount_cents"]) for r in rows] == [
        (1, "check", 15000), (2, "cash", 2000), (2, "check", 5000), (3, "cash", 1000), (4, "cash", 8350), (5, "cash", 500)]
    assert rows[0]["contact_id"] == "p1" and rows[0]["fund"] == "Tithes" and rows[0]["check_number"] == "3107"
    assert rows[1]["contact_id"] == "p2" and rows[1]["name_match"] == "one"       # first and last name
    assert rows[1]["fund"] == "Tithes"                                            # no fund: the first one
    assert rows[3]["contact_id"] is None and rows[3]["name_match"] == "several"   # two Ann Lees
    assert rows[3]["fund_known"] is False and rows[3]["unsure"] is True
    assert rows[4]["loose"] is True and rows[4]["contact_id"] is None
    assert rows[5]["name_match"] == "none"
    assert d["cash_cents"] == 11850 and d["checks_cents"] == 20000
    assert {c["what"]: c["agrees"] for c in d["checks"]} == {"cash": True, "checks": True, "plate total": False}
    assert d["agrees"] is False and d["counters"] == ["Ann Lee", "Bo Price"]
    assert d["unsure"] == 2      # Ann Lee's line (unsure, two people, unknown fund), Someone New


def test_a_bad_amount_is_never_money():
    d = sh.draft_from({"lines": [{"name": "X", "cash": "abc", "check": float("nan")},
                                 {"name": "Y", "cash": -5, "check": 99999999},
                                 {"name": "Z", "cash": float("inf"), "check": 0}]}, [], ["General"])
    assert [r["amount_cents"] for r in d["rows"]] == [9_999_999_900]      # kept as read; saving refuses it


# ─── The photo ─────────────────────────────────────────────────────────

def _upload(raw=JPEG):
    return SimpleNamespace(read=lambda n=None: _aw(raw))


async def _aw(v):
    return v


def test_a_photo_is_kept_then_read_into_a_draft_never_gifts(db, monkeypatch):
    stored = []
    monkeypatch.setattr(sh, "_store", lambda path, raw, mt: stored.append((path, mt)) or True)

    async def read(biz, raw, mt):
        return {"readable": True, "lines": [{"name": "Grace Holloway", "cash": 0, "check": 150}]}
    monkeypatch.setattr(sh, "read_photo", read)
    out = asyncio.run(sh.upload_photo(BIZ, COUNT, _upload(), USER))
    assert out["ok"] and out["draft"]["rows"][0]["contact_id"] == "p1"
    assert stored and stored[0][0].startswith(f"{BIZ}/{COUNT}/") and stored[0][1] == "image/jpeg"
    row = db.t["giving_count_photos"][0]
    assert row["status"] == "read" and row["draft"]["rows"]
    assert db.t["invoices"] == []                                # a draft, never gifts


def test_a_photo_that_cant_be_read_is_still_kept(db, monkeypatch):
    async def read(biz, raw, mt):
        return {"readable": False, "lines": []}
    monkeypatch.setattr(sh, "read_photo", read)
    with pytest.raises(HTTPException) as e:
        asyncio.run(sh.upload_photo(BIZ, COUNT, _upload(), USER))
    assert e.value.status_code == 422
    row = db.t["giving_count_photos"][0]
    assert row["status"] == "unread" and "count sheet" in row["error"]


@pytest.mark.parametrize("kind,code", [("gif", 415), ("too_big", 413)])
def test_only_a_photo_within_the_limit_is_taken(db, kind, code):
    raw = b"GIF89a" + b"0" * 64 if kind == "gif" else JPEG + b"0" * (8 * 1024 * 1024)
    with pytest.raises(HTTPException) as e:
        asyncio.run(sh.upload_photo(BIZ, COUNT, _upload(raw), USER))
    assert e.value.status_code == code
    assert db.t["giving_count_photos"] == []


def test_a_used_photo_points_only_at_this_counts_gifts(db):
    pid = str(uuid.uuid4())
    mine, theirs = str(uuid.uuid4()), str(uuid.uuid4())
    db.t["giving_count_photos"] = [{"id": pid, "business_id": BIZ, "count_id": COUNT, "status": "read"}]
    db.t["invoices"] = [{"id": mine, "business_id": BIZ, "giving_count_id": COUNT},
                        {"id": theirs, "business_id": BIZ, "giving_count_id": "another-count"}]
    out = sh.photo_used(BIZ, COUNT, pid, {"gift_ids": [mine, theirs, "not-a-uuid"]}, USER)
    assert out["gift_ids"] == [mine] and db.t["giving_count_photos"][0]["status"] == "used"


def test_photos_follow_the_gate(db, monkeypatch):
    monkeypatch.setattr(giving_ways, "switched_on", lambda b: False)
    with pytest.raises(HTTPException) as e:
        sh.count_sheet(BIZ, COUNT, USER)
    assert e.value.status_code == 404


def test_a_read_that_times_out_keeps_the_photo_and_says_so(db, monkeypatch):
    async def read(biz, raw, mt):
        raise TimeoutError("read timed out")
    monkeypatch.setattr(sh, "read_photo", read)
    with pytest.raises(HTTPException) as e:
        asyncio.run(sh.upload_photo(BIZ, COUNT, _upload(), USER))
    assert e.value.status_code == 502 and "photo is kept" in e.value.detail
    row = db.t["giving_count_photos"][0]
    assert row["status"] == "unread" and row["error"]


def test_deleting_a_church_takes_its_sheet_photos_too():
    import account_lifecycle
    assert "giving-sheets" in account_lifecycle.STORAGE_BUCKETS
    assert "giving_count_photos" in account_lifecycle.BUSINESS_CHILD_TABLES


def test_the_sheet_offers_the_churchs_own_apps(db):
    db.t["businesses"][0]["settings"]["giving"]["ways"] = [
        {"app": "zelle", "handle": "give@lovecity.org"}, {"app": "subsplash"},
        {"app": "other", "label": "Givelify"}]
    page = sh.count_sheet(BIZ, COUNT, USER).body.decode()
    assert "&#9744; Zelle" in page and "&#9744; Givelify" in page
    assert "Subsplash" not in page and "&#9744; Cash App" not in page


def test_app_lines_become_rows_on_the_churchs_apps():
    apps = [{"id": "cashapp", "label": "Cash App"}, {"id": "zelle", "label": "Zelle"},
            {"id": "other:Givelify", "label": "Givelify"}]
    got = {"lines": [{"name": "Ann Lee", "cash": 20, "check": 0}],
           "app_lines": [{"line": "A1", "name": "Grace Holloway", "app": "cashapp", "fund": "Building",
                          "amount": 50, "note": "...4821"},
                         {"line": "A2", "name": "Marcus Reed", "app": "Zelle", "amount": 25},
                         {"line": "A3", "name": "Grace Holloway", "app": "givelify", "amount": 10},
                         {"line": "A4", "name": "Grace Holloway", "app": "Venmo", "amount": 5, "unsure": True}],
           "written_apps_total": 90, "written_total": 20}
    d = sh.draft_from(got, PEOPLE, ["Tithes", "Building", "Missions"], apps)
    app_rows = [r for r in d["rows"] if r["method"] not in ("cash", "check")]
    assert [(r["line"], r["method"], r["amount_cents"]) for r in app_rows] == [
        ("A1", "cashapp", 5000), ("A2", "zelle", 2500), ("A3", "other:Givelify", 1000), ("A4", "other:Venmo", 500)]
    assert app_rows[0]["contact_id"] == "p1" and app_rows[0]["fund"] == "Building" and app_rows[0]["note"] == "...4821"
    assert app_rows[3]["app_known"] is False and app_rows[3]["app"] == "Venmo"      # not one of the church's apps
    assert d["cash_cents"] == 2000 and d["apps_cents"] == 9000                     # apps never in the plate
    assert {c["what"]: c["agrees"] for c in d["checks"]} == {"plate total": True, "apps": True}


def test_many_long_app_names_stay_on_one_line_of_boxes(db):
    db.t["businesses"][0]["settings"]["giving"]["ways"] = [
        {"app": "cashapp"}, {"app": "zelle"}, {"app": "venmo"}, {"app": "paypal"},
        {"app": "other", "label": "A Very Long Giving App Name Here"},
        {"app": "other", "label": "Another Long Giving Platform Name"}, {"app": "other", "label": "Third App"}]
    page = sh.count_sheet(BIZ, COUNT, USER).body.decode()
    first_line = page.split('<td class="n">A1</td>', 1)[1].split("</tr>", 1)[0]
    assert first_line.count("&#9744;") == sh.APP_BOXES + 1 and "Other ______" in first_line
    assert "A Very Long Giving App N" in first_line and "Third App" not in first_line
    assert "td.apps { font-size: 10px; line-height: 1.25; }" in page        # the cell wraps

