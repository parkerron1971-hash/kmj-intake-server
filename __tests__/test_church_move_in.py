"""The Move-in room (church_move_in.py). Kevin 2026-11-11, with the first
founding church signing up: "create upload areas of the information that
they need to hand into the system and I don't directly have to load it".

Pins:
  * the switch: off hides it, owner opens it to the platform's own church
    only, and tables that aren't there yet are a quiet no and 503s
  * who: the owner, admins and Office logins; another area's login is
    refused, a viewer reads and can't hand in, a stranger gets nothing,
    another church's room is unreachable
  * the list is the handout's eleven, in its order
  * answers: only the item's own fields are kept, typed and trimmed
  * hand-in: refused in words until what's needed is there; emails the
    platform owner once, with what was handed in; a second press is quiet
  * a change after hand-in takes the item back
  * files: judged from their bytes, kept under the church's own folder in
    the private bucket, capped per item, never linked for the church
  * giving follows Stripe and can't be handed in or marked
  * the platform owner reads every room with links, marks an item checked
    or asks for a change with a note the church then sees; nobody else can
  * the last hand-in opens one ticket, with nothing private in it
"""
from __future__ import annotations

import io
import os
import sys

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.dirname(os.path.abspath(__file__))
for p in (ROOT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import church_areas  # noqa: E402
import church_move_in as mi  # noqa: E402
import email_sender  # noqa: E402
import lead_admin  # noqa: E402
import member_asks  # noqa: E402
import sb_clients  # noqa: E402
from auth_supabase import AuthedUser, require_user  # noqa: E402
from test_church_roles import FakeDB  # noqa: E402

BIZ = "11111111-1111-4111-8111-111111111111"
OTHER = "22222222-2222-4222-8222-222222222222"
SALON = "33333333-3333-4333-8333-333333333333"
NAMES = ("owner", "admin", "office", "singer", "viewer", "stranger", "other_owner", "kevin")
PEOPLE = {n: AuthedUser(id=f"00000000-0000-4000-8000-{i:012d}", email=f"{n}@gracehill.org", role="authenticated")
          for i, n in enumerate(NAMES, start=1)}
PEOPLE["kevin"] = AuthedUser(id=PEOPLE["kevin"].id, email="kevin@solutionist.test", role="authenticated")
ID = {n: u.id for n, u in PEOPLE.items()}
CSV = b"Name,Email,Mobile,Household\nAda Hill,ada@example.com,555-0100,Hill\n"


def picture() -> bytes:
    from PIL import Image
    out = io.BytesIO()
    Image.new("RGB", (64, 64), (30, 60, 200)).save(out, "PNG")
    return out.getvalue()


class MoveDB(FakeDB):
    def _gone(self, path):
        return self.missing and path.lstrip("/").split("?")[0].startswith("church_move_")

    def get(self, path, **kw):
        return None if self._gone(path) else super().get(path, **kw)

    def post(self, path, body, prefer=None, **kw):
        if self._gone(path):
            return None
        table = path.lstrip("/").split("?")[0]
        if table == "church_move_items":
            body = {"state": "todo", "answers": {}, "note": None, "handed_in_at": None, "handed_in_by": None,
                    "checked_at": None, **body}
            if any(r["business_id"] == body["business_id"] and r["item"] == body["item"] for r in self.t[table]):
                return None      # the primary key
        return super().post(path, body, prefer=prefer, **kw)

    def remove(self, path, **kw):
        super().delete(path, **kw)
        return True


@pytest.fixture
def db(monkeypatch):
    fake = MoveDB(
        businesses=[{"id": BIZ, "name": "Grace Hill Church", "type": "ministry", "owner_id": ID["owner"],
                     "settings": {}, "stripe_account_id": None},
                    {"id": OTHER, "name": "Second Baptist", "type": "ministry", "owner_id": ID["other_owner"],
                     "settings": {}, "stripe_account_id": None},
                    {"id": SALON, "name": "Shear Joy", "type": "salon", "owner_id": ID["owner"], "settings": {},
                     "stripe_account_id": None}],
        business_users=[{"business_id": BIZ, "user_id": ID[n], "role": r, "status": "active",
                         "invited_email": f"{n}@gracehill.org"}
                        for n, r in (("admin", "admin"), ("office", "member"), ("singer", "member"),
                                     ("viewer", "viewer"))],
        business_collaborators=[], contacts=[], church_move_items=[], church_move_files=[], support_tickets=[],
    )
    fake.missing = False
    for name in ("get", "post", "patch"):
        monkeypatch.setattr(sb_clients, f"sb_{name}_as_service", getattr(fake, name))
    monkeypatch.setattr(sb_clients, "sb_delete_as_service", fake.remove)
    monkeypatch.setattr(sb_clients, "sb_count_as_service", lambda path: len(fake.get(path)))
    monkeypatch.setenv("CHURCH_MOVE_IN", "on")
    monkeypatch.setenv("CHURCH_AREAS", "on")
    monkeypatch.setenv("PLATFORM_OWNER_EMAIL", "kevin@solutionist.test")
    monkeypatch.setattr(lead_admin, "PLATFORM_OWNER_EMAIL", "kevin@solutionist.test")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-key")
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    areas = {ID["office"]: ["office"], ID["viewer"]: ["office"], ID["singer"]: ["worship_media"]}
    monkeypatch.setattr(church_areas, "my_areas", lambda biz, uid, role: {"areas": areas.get(uid), "by": "picked"})
    fake.files, fake.dropped, fake.mail = {}, [], []
    monkeypatch.setattr(mi, "_storage_put",
                        lambda path, data, media: (fake.files.__setitem__(path, (data, media)) or (True, 200, "")))
    monkeypatch.setattr(mi, "_storage_drop", lambda path: (fake.dropped.append(path), fake.files.pop(path, None)))
    monkeypatch.setattr(mi, "_signed", lambda path, name: f"https://signed.test/{path}?as={name}")

    async def send(**kw):
        fake.mail.append(kw)
        return {"id": "em_1"}
    monkeypatch.setattr(email_sender, "send_via_resend", send)
    return fake


def client(name) -> TestClient:
    app = FastAPI()
    app.include_router(mi.router)
    app.include_router(mi.platform_router)
    app.dependency_overrides[require_user] = lambda: PEOPLE[name]
    return TestClient(app)


def room(name="owner", biz=BIZ):
    got = client(name).get(f"/church/move-in?business_id={biz}")
    assert got.status_code == 200, got.text
    return got.json()


def item(page, key):
    return next(i for i in page["items"] if i["key"] == key)


def save(name, key, answers, biz=BIZ):
    return client(name).put(f"/church/move-in/{key}", json={"business_id": biz, "answers": answers})


def hand_in(name, key, biz=BIZ):
    return client(name).post(f"/church/move-in/{key}/hand-in", json={"business_id": biz})


def upload(name, key, filename, data, biz=BIZ):
    return client(name).post(f"/church/move-in/{key}/files", data={"business_id": biz},
                             files={"file": (filename, data, "application/octet-stream")})


def status(name, biz=BIZ):
    return client(name).get(f"/church/move-in/status?business_id={biz}").json()


# ─── 1. the switch ────────────────────────────────────────────────────

def test_off_hides_the_room(db, monkeypatch):
    monkeypatch.setenv("CHURCH_MOVE_IN", "off")
    assert status("owner") == {"enabled": False, "write": False}
    assert client("owner").get(f"/church/move-in?business_id={BIZ}").status_code == 404


def test_unset_opens_it_to_the_platforms_own_church_only(db, monkeypatch):
    monkeypatch.delenv("CHURCH_MOVE_IN")
    monkeypatch.setattr(member_asks, "platform_church", lambda biz: str(biz) == OTHER)
    assert status("owner")["enabled"] is False
    assert status("other_owner", OTHER)["enabled"] is True


def test_a_word_that_isnt_a_mode_is_off(db, monkeypatch):
    monkeypatch.setenv("CHURCH_MOVE_IN", "yes please")
    assert mi.mode() == "off"


def test_tables_not_made_yet_are_a_quiet_no_and_a_503(db):
    db.missing = True
    assert status("owner") == {"enabled": False, "write": False}
    assert client("owner").get(f"/church/move-in?business_id={BIZ}").status_code == 503


# ─── 2. who ───────────────────────────────────────────────────────────

def test_the_owner_admins_and_office_logins_get_in(db):
    for name in ("owner", "admin", "office"):
        assert status(name) == {"enabled": True, "write": True, "finished": False}
    assert status("viewer") == {"enabled": True, "write": False, "finished": False}


def test_the_move_is_finished_when_every_thing_is_checked_and_giving_is_live(db):
    """The menu lets the room go only then. Handed in is not finished: it
    can still come back needing a change."""
    keys = [i["key"] for i in mi.ITEMS if i.get("live") != "giving"]
    for k in keys:
        db.t["church_move_items"].append({"business_id": BIZ, "item": k, "state": "checked", "answers": {"x": "y"},
                                          "note": None, "handed_in_at": "2026-11-12T00:00:00Z", "handed_in_by": None,
                                          "checked_at": "2026-11-12T00:00:00Z", "updated_at": "2026-11-12T00:00:00Z"})
    assert status("owner")["finished"] is False                              # giving isn't live yet
    db.t["businesses"][0].update(stripe_account_id="acct_1", settings={"stripe": {"charges_enabled": True}})
    assert status("owner")["finished"] is True
    assert client("owner").get(f"/church/move-in?business_id={BIZ}").status_code == 200   # its address still opens
    db.t["church_move_items"][0]["state"] = "handed_in"
    assert status("owner")["finished"] is False
    db.t["church_move_items"][0]["state"] = "needs"
    assert status("owner")["finished"] is False


def test_a_finished_question_that_cant_be_read_keeps_the_room_on_the_menu(db, monkeypatch):
    monkeypatch.setattr(mi, "_finished", lambda biz: (_ for _ in ()).throw(RuntimeError("down")))
    assert status("owner") == {"enabled": True, "write": True, "finished": False}


def test_another_areas_login_and_a_stranger_do_not(db):
    assert status("singer")["enabled"] is False
    assert client("singer").get(f"/church/move-in?business_id={BIZ}").status_code == 403
    assert status("stranger")["enabled"] is False
    assert client("stranger").get(f"/church/move-in?business_id={BIZ}").status_code == 404


def test_a_viewer_reads_and_cant_hand_in(db):
    assert room("viewer")["me"] == {"write": False}
    assert save("viewer", "owner", {"name": "Ada"}).status_code == 403
    assert hand_in("viewer", "owner").status_code == 403
    assert upload("viewer", "giving_history", "gifts.csv", CSV).status_code == 403


def test_another_churchs_room_is_unreachable(db):
    assert save("owner", "owner", {"name": "Ada Hill"}).status_code == 200
    assert client("other_owner").get(f"/church/move-in?business_id={BIZ}").status_code == 404
    assert save("other_owner", "owner", {"name": "Not mine"}).status_code == 404
    assert item(room("other_owner", OTHER), "owner")["answers"] == {}


def test_it_is_for_churches(db):
    assert status("owner", SALON)["enabled"] is False


# ─── 3. the list ──────────────────────────────────────────────────────

def test_the_list_is_the_handouts_eleven_in_order(db):
    page = room()
    assert [i["key"] for i in page["items"]] == [
        "giving", "people", "owner", "tools", "monthly_givers", "giving_history", "logins", "safety", "sunday",
        "look", "room"]
    assert [i["key"] for i in page["items"] if i["urgent"]] == ["giving", "people", "owner"]
    assert page["progress"] == {"settled": 0, "total": 11}
    assert all(i["state"] == "todo" and i["state_words"] == "Not started" for i in page["items"])
    assert page["church"]["name"] == "Grace Hill Church"


def test_every_need_names_a_field_the_item_has():
    for it in mi.ITEMS:
        keys = {f["key"] for f in it.get("fields") or []}
        need = it.get("need")
        if isinstance(need, list):
            assert {n.partition(":")[0] for n in need} <= keys, it["key"]
        elif need == "files" or need == "people":
            assert it.get("files"), it["key"]
        elif need == "any":
            assert keys, it["key"]
        else:
            assert it.get("live") == "giving", it["key"]


# ─── 4. answers ───────────────────────────────────────────────────────

def test_only_the_items_own_fields_are_kept_trimmed(db):
    got = save("office", "owner", {"name": "  Ada   Hill ", "mobile": "555-0100", "email": "", "admin": True,
                                   "best_time": "x" * 500})
    assert got.status_code == 200, got.text
    mine = item(got.json(), "owner")
    assert mine["answers"] == {"name": "Ada Hill", "mobile": "555-0100", "best_time": "x" * 200}
    assert mine["state"] == "started" and mine["hand_in"] == {"ready": True, "missing": None}


def test_rows_drop_empty_lines_and_keep_only_their_columns(db):
    got = save("owner", "sunday", {"services": [{"day": "Sunday", "time": "10:00 AM", "name": "Morning", "x": "y"},
                                               {"day": " ", "time": ""}, "nonsense"],
                                   "kids_rooms": [{"room": "Nursery", "ages": "0 to 2"}]})
    assert item(got.json(), "sunday")["answers"] == {
        "services": [{"day": "Sunday", "time": "10:00 AM", "name": "Morning"}],
        "kids_rooms": [{"room": "Nursery", "ages": "0 to 2"}]}


def test_the_first_sunday_is_a_line_of_the_sunday_item_and_is_not_what_makes_it_ready(db):
    """The welcome briefing saves the date the church picked; the services are still
    what the item needs before it can be handed in."""
    got = save("owner", "sunday", {"first_sunday": "  Sunday, November 22, 2026 "})
    assert got.status_code == 200, got.text
    mine = item(got.json(), "sunday")
    assert mine["answers"] == {"first_sunday": "Sunday, November 22, 2026"}
    assert mine["hand_in"]["ready"] is False
    assert mine["fields"][0]["key"] == "first_sunday"


def test_a_number_that_isnt_one_and_too_many_rows_are_refused_by_name(db):
    got = save("owner", "monthly_givers", {"count": "about forty"})
    assert got.status_code == 400 and "People who give monthly" in got.json()["detail"]
    assert item(save("owner", "monthly_givers", {"count": "1,240"}).json(), "monthly_givers")["answers"] == {"count": 1240}
    got = save("owner", "safety", {"officers": [{"name": n} for n in ("A", "B", "C")]})
    assert got.status_code == 400 and "2 at most" in got.json()["detail"]


def test_an_item_with_nothing_to_type_and_one_not_on_the_list(db):
    assert save("owner", "giving_history", {"x": 1}).status_code == 400
    assert save("owner", "nope", {"x": 1}).status_code == 404


# ─── 5. hand-in ───────────────────────────────────────────────────────

def test_hand_in_waits_for_whats_needed_and_says_what(db):
    got = hand_in("owner", "owner")
    assert got.status_code == 400 and got.json()["detail"] == "Their name is still empty."
    save("owner", "safety", {"officers": [{"name": "Ada Hill", "contact": "ada@example.com"}]})
    assert hand_in("owner", "safety").json()["detail"] == "Safety officers: add 2."
    assert hand_in("owner", "giving_history").json()["detail"] == "Add at least one file first."
    assert hand_in("owner", "tools").json()["detail"] == "Fill in at least one line first."
    assert db.mail == []


def test_hand_in_emails_the_platform_owner_once(db):
    save("office", "owner", {"name": "Ada <Hill>", "mobile": "555-0100"})
    got = hand_in("office", "owner")
    assert got.status_code == 200, got.text
    mine = item(got.json(), "owner")
    assert mine["state"] == "handed_in" and mine["hand_in"]["ready"] is False and mine["handed_in_at"]
    assert got.json()["progress"] == {"settled": 1, "total": 11}
    assert len(db.mail) == 1
    mail = db.mail[0]
    assert mail["to_email"] == "kevin@solutionist.test"
    assert mail["subject"] == "Grace Hill Church handed in: Name the person who owns the move"
    assert "Their name: Ada &lt;Hill&gt;" in mail["body"] and "<Hill>" not in mail["body"]
    assert "Handed in by office@gracehill.org." in mail["body"] and "1 of 11 are in." in mail["body"]
    # A second press changes nothing and sends nothing.
    assert hand_in("office", "owner").status_code == 200
    assert len(db.mail) == 1


def test_a_failed_email_never_fails_the_hand_in(db, monkeypatch):
    async def boom(**kw):
        raise RuntimeError("resend is down")
    monkeypatch.setattr(email_sender, "send_via_resend", boom)
    save("owner", "owner", {"name": "Ada Hill"})
    got = hand_in("owner", "owner")
    assert got.status_code == 200 and item(got.json(), "owner")["state"] == "handed_in"


def test_no_owner_address_means_no_email(db, monkeypatch):
    monkeypatch.delenv("PLATFORM_OWNER_EMAIL")
    save("owner", "owner", {"name": "Ada Hill"})
    assert hand_in("owner", "owner").status_code == 200
    assert db.mail == []


def test_a_change_after_hand_in_takes_it_back(db):
    save("owner", "owner", {"name": "Ada Hill"})
    hand_in("owner", "owner")
    mine = item(save("owner", "owner", {"name": "Ada Hill", "mobile": "555-0100"}).json(), "owner")
    assert mine["state"] == "started" and mine["handed_in_at"] is None and mine["hand_in"]["ready"] is True


def test_people_can_be_handed_in_once_someone_is_on_file(db):
    assert hand_in("owner", "people").json()["detail"] == "Bring your people in first, or hand in the file."
    db.t["contacts"].append({"id": "c1", "business_id": BIZ, "name": "Ada Hill"})
    assert item(room(), "people")["live"] == {"on_file": 1}
    assert hand_in("owner", "people").status_code == 200
    assert "People on file: 1." in db.mail[0]["body"]


def test_a_count_that_couldnt_be_read_is_not_known_never_zero(db, monkeypatch):
    monkeypatch.setattr(sb_clients, "sb_count_as_service", lambda path: None)
    assert item(room(), "people")["live"] == {"on_file": None}


# ─── 6. files ─────────────────────────────────────────────────────────

def test_a_file_is_kept_in_the_churchs_own_folder_and_never_linked_for_the_church(db):
    got = upload("office", "giving_history", "2026 gifts.csv", CSV)
    assert got.status_code == 200, got.text
    files = item(got.json(), "giving_history")["files"]["list"]
    assert [f["name"] for f in files] == ["2026 gifts.csv"]
    assert "url" not in files[0] and "path" not in files[0] and files[0]["size_bytes"] == len(CSV)
    (path, (data, media)), = db.files.items()
    assert path.startswith(f"{BIZ}/move-in/") and mi.file_key(BIZ, path) and not mi.file_key(OTHER, path)
    assert data == CSV and media == "text/csv"
    assert hand_in("office", "giving_history").status_code == 200
    assert "Files (1): 2026 gifts.csv" in db.mail[0]["body"]


def test_files_are_judged_from_their_bytes(db):
    assert upload("owner", "giving_history", "gifts.xlsx", b"PK\x03\x04rest").status_code == 200
    assert upload("owner", "giving_history", "gifts.pdf", b"%PDF-1.7 rest").status_code == 200
    assert upload("owner", "giving_history", "gifts.xlsx", b"not a workbook").status_code == 400
    assert upload("owner", "giving_history", "run.exe", b"MZ\x00\x00").status_code == 400
    assert upload("owner", "giving_history", "gifts.csv", b"").status_code == 400
    assert upload("owner", "look", "logo.png", picture()).status_code == 200
    got = upload("owner", "look", "logo.png", b"<svg onload=alert(1)>")
    assert got.status_code == 400 and "JPG, PNG or WebP" in got.json()["detail"]
    assert upload("owner", "owner", "x.csv", CSV).status_code == 400      # no file slot


def test_too_large_is_a_413(db, monkeypatch):
    monkeypatch.setattr(mi, "MAX_FILE_BYTES", 10)
    assert upload("owner", "giving_history", "gifts.csv", CSV).status_code == 413
    assert db.files == {}


def test_an_item_holds_only_so_many(db):
    for n in range(3):
        assert upload("owner", "people", f"people-{n}.csv", CSV).status_code == 200
    got = upload("owner", "people", "people-3.csv", CSV)
    assert got.status_code == 400 and "most this one holds (3)" in got.json()["detail"]


def test_a_refused_upload_keeps_nothing(db, monkeypatch):
    monkeypatch.setattr(mi, "_storage_put", lambda path, data, media: (False, 500, "boom"))
    assert upload("owner", "giving_history", "gifts.csv", CSV).status_code == 503
    assert db.t["church_move_files"] == []


def test_removing_a_file_drops_it_and_takes_a_handed_in_item_back(db):
    upload("owner", "giving_history", "gifts.csv", CSV)
    hand_in("owner", "giving_history")
    fid = item(room(), "giving_history")["files"]["list"][0]["id"]
    assert client("other_owner").delete(f"/church/move-in/files/{fid}?business_id={OTHER}").status_code == 404
    got = client("owner").delete(f"/church/move-in/files/{fid}?business_id={BIZ}")
    assert got.status_code == 200, got.text
    mine = item(got.json(), "giving_history")
    assert mine["files"]["list"] == [] and mine["state"] == "todo"
    assert db.files == {} and len(db.dropped) == 1


def test_the_display_name_is_cleaned(db):
    upload("owner", "giving_history", '..\\..\\evil<name>.csv', CSV)
    name = item(room(), "giving_history")["files"]["list"][0]["name"]
    assert "\\" not in name and "<" not in name and name.endswith(".csv")


# ─── 7. giving follows Stripe ─────────────────────────────────────────

def test_giving_follows_stripe_and_cant_be_handed_in(db):
    assert item(room(), "giving")["state"] == "todo" and item(room(), "giving")["hand_in"] is None
    db.t["businesses"][0].update(stripe_account_id="acct_1", settings={"stripe": {"charges_enabled": False}})
    waiting = item(room(), "giving")
    assert waiting["state"] == "waiting" and waiting["state_words"] == "Waiting on Stripe"
    assert waiting["live"] == {"connected": True, "ready": False}
    db.t["businesses"][0]["settings"] = {"stripe": {"charges_enabled": True}}
    assert item(room(), "giving")["state"] == "done" and room()["progress"]["settled"] == 1
    assert hand_in("owner", "giving").status_code == 400


# ─── 8. the platform owner's side ─────────────────────────────────────

def test_only_the_platform_owner_reads_every_room(db):
    save("owner", "owner", {"name": "Ada Hill"})
    hand_in("owner", "owner")
    upload("owner", "giving_history", "gifts.csv", CSV)
    for name in ("owner", "admin", "stranger"):
        assert client(name).get("/platform/move-in").status_code == 403
        assert client(name).get(f"/platform/move-in/{BIZ}").status_code == 403
        assert client(name).post(f"/platform/move-in/{BIZ}/owner", json={"state": "checked"}).status_code == 403
    got = client("kevin").get("/platform/move-in").json()["churches"]
    assert [(c["name"], c["handed_in"], c["total"]) for c in got] == [("Grace Hill Church", 1, 11)]
    page = client("kevin").get(f"/platform/move-in/{BIZ}").json()
    f = item(page, "giving_history")["files"]["list"][0]
    assert f["url"].startswith(f"https://signed.test/{BIZ}/move-in/") and f["url"].endswith("?as=gifts.csv")
    assert item(page, "owner")["answers"] == {"name": "Ada Hill"}


def test_checked_and_a_change_with_a_note_the_church_then_sees(db):
    save("owner", "owner", {"name": "Ada Hill"})
    mark = lambda body, key="owner": client("kevin").post(f"/platform/move-in/{BIZ}/{key}", json=body)  # noqa: E731
    assert mark({"state": "checked"}).status_code == 409                    # not handed in yet
    hand_in("owner", "owner")
    assert mark({"state": "done"}).status_code == 400
    assert mark({"state": "needs"}).status_code == 400                      # a change needs words
    assert mark({"state": "checked"}, "giving").status_code == 400
    assert item(mark({"state": "checked"}).json(), "owner")["state"] == "checked"
    assert item(room(), "owner")["state_words"] == "Checked" and room()["progress"]["settled"] == 1
    got = mark({"state": "needs", "note": "We need a mobile number for Ada."})
    assert got.status_code == 200, got.text
    mine = item(room(), "owner")
    assert mine["state"] == "needs" and mine["note"] == "We need a mobile number for Ada."
    assert mine["hand_in"]["ready"] is True and room()["progress"]["settled"] == 0
    # The church fixes it and hands it in again: the note goes, the email goes out again.
    save("owner", "owner", {"name": "Ada Hill", "mobile": "555-0100"})
    assert item(room(), "owner")["state"] == "needs"
    again = item(hand_in("owner", "owner").json(), "owner")
    assert again["state"] == "handed_in" and again["note"] is None
    assert len(db.mail) == 2


def test_the_last_hand_in_opens_one_ticket_with_nothing_private_in_it(db):
    db.t["businesses"][0].update(stripe_account_id="acct_1", settings={"stripe": {"charges_enabled": True}})
    db.t["contacts"].append({"id": "c1", "business_id": BIZ, "name": "Ada Hill"})
    save("owner", "owner", {"name": "Ada Hill"})
    save("owner", "tools", {"giving": "Tithely, renews March 1"})
    save("owner", "monthly_givers", {"count": 40})
    upload("owner", "giving_history", "gifts.csv", CSV)
    save("owner", "logins", {"people": [{"name": "Ada Hill", "email": "ada@example.com", "looks_after": "Office"}]})
    save("owner", "safety", {"officers": [{"name": "Ada Hill"}, {"name": "Ben Hill"}]})
    save("owner", "sunday", {"services": [{"day": "Sunday", "time": "10:00 AM"}]})
    upload("owner", "look", "logo.png", picture())
    save("owner", "room", {"wifi": "Yes, it reaches the seats."})
    keys = [k for k in mi.ITEM if k != "giving"]
    for key in keys[:-1]:
        assert hand_in("owner", key).status_code == 200, key
    assert db.t["support_tickets"] == []
    got = hand_in("owner", keys[-1])
    assert got.json()["progress"] == {"settled": 11, "total": 11}
    ticket, = db.t["support_tickets"]
    assert ticket["subject"] == "MOVE-IN: Grace Hill Church has handed in everything"
    assert ticket["context"] == {"kind": "church_move_in"} and "Ada" not in ticket["message"]
    assert len(db.mail) == len(keys)
