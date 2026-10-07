# __tests__/test_kids_station.py
#
# Check-in stations (kids_station.py). Pins:
#   1. managers create and remove stations; a member can't; secrets never
#      come back in a listing
#   2. pairing: a one-time code works once, not after it expires, and a
#      removed or re-paired station's old token stops working at once
#   3. the PIN: wrong is refused, tries are capped, the unlock expires and
#      dies with the token; a staff station does nothing while locked
#   4. staff station: finds families (last four digits only, no medical
#      or custody), checks in stamped with the station, only for today's
#      services, and releases only to the list — never a custody family
#   5. self kiosk: a mobile number finds exactly one family and shows first
#      names only; unknown and shared numbers get the same answer; the code
#      is texted to that number; it can't search, list rooms or release

import importlib.util
import pathlib
import re
import sys
import time
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import kids_checkin as kc
import kids_router as kr
import kids_station as ks
import rate_limit
from auth_supabase import AuthedUser, require_user

_spec = importlib.util.spec_from_file_location("kids_checkin_tests", HERE / "test_kids_checkin.py")
_ck = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_ck)
BIZ, OWNER, MEMBER, MANAGER, PARENT, ENTRY = _ck.BIZ, _ck.OWNER, _ck.MEMBER, _ck.MANAGER, _ck.PARENT, _ck.ENTRY
LATER = "eeeeeeee-0000-0000-0000-000000000009"


class Store(_ck.Store):
    def __init__(self):
        super().__init__()
        self.t["checkin_stations"] = []
        self.t["module_entries"].append({"id": LATER, "business_id": BIZ, "data": {"title": "Next week"}})

    def post(self, path, body, prefer=None):
        if path.startswith("/checkin_stations") and isinstance(body, dict):
            body = {"token_hash": None, "pair_code_hash": None, "pair_expires_at": None, "revoked_at": None,
                    "last_seen_at": None, "paired_at": None, **body}
        return super().post(path, body, prefer)


@pytest.fixture
def store(monkeypatch):
    s = Store()
    for mod in (kr, kc, ks):
        monkeypatch.setattr(mod.sb_clients, "sb_get_as_service", s.get)
        monkeypatch.setattr(mod.sb_clients, "sb_post_as_service", s.post)
        monkeypatch.setattr(mod.sb_clients, "sb_patch_as_service", s.patch)
        monkeypatch.setattr(mod.sb_clients, "sb_delete_as_service", s.delete)
    monkeypatch.setenv("CUSTOMER_TOKEN_SECRET", "test-root-secret")
    # Only ENTRY is "today".
    monkeypatch.setattr(ks, "todays_occasions", lambda biz, today=None: [
        {"id": ENTRY, "title": "Sunday Service", "date": "2026-10-04", "when": "2026-10-04"}] if biz == BIZ else [])
    monkeypatch.setattr(rate_limit, "_shared_take", lambda bucket, key: None)
    rate_limit._buckets.clear()
    return s


@pytest.fixture
def texts(monkeypatch):
    return _ck.texts.__wrapped__(monkeypatch) if hasattr(_ck.texts, "__wrapped__") else _texts(monkeypatch)


def _texts(monkeypatch):
    import sms_service
    import twilio_sms
    sent = {"to": []}
    monkeypatch.setattr(sms_service, "_twilio_configured", lambda: True)

    async def opted_out(client, phone, business_id=None):
        return False

    async def sender_for(client, business_id):
        return "+15550009999"
    monkeypatch.setattr(sms_service, "is_opted_out", opted_out)
    monkeypatch.setattr(sms_service, "sender_for", sender_for)
    monkeypatch.setattr(twilio_sms, "send_sms", lambda to, body, from_number=None: sent["to"].append((to, body)) or "SM1")
    return sent


def app_client(user_id=None, token=None, unlock=None):
    app = FastAPI()
    for r in (kr.router, kc.router, ks.router):
        app.include_router(r)
    if user_id:
        app.dependency_overrides[require_user] = lambda: AuthedUser(id=user_id, email=None, role="authenticated")
    headers = {}
    if token:
        headers["X-Station-Token"] = token
    if unlock:
        headers["X-Station-Unlock"] = unlock
    return TestClient(app, headers=headers)


def make_station(mode="staff", pin="2468", as_user=MANAGER):
    r = app_client(as_user).post("/kids/stations", json={"business_id": BIZ, "name": "Welcome desk", "mode": mode, "pin": pin})
    assert r.status_code == 200, r.text
    return r.json()


def paired(mode="staff"):
    made = make_station(mode)
    r = app_client().post("/kids/station/pair", json={"code": made["pair_code"].lower()})
    assert r.status_code == 200, r.text
    return made["station"]["id"], r.json()["token"]


def unlocked(token, pin="2468"):
    r = app_client(token=token).post("/kids/station/unlock", json={"pin": pin})
    assert r.status_code == 200, r.text
    return r.json()["unlock"]


def _holds_pin(value, pin):
    """A stored value that IS the PIN, or human text that contains it. The
    row's ids and hashes are random hex, where the digits turn up by chance
    (a plain substring check over the whole row failed about 1 run in 250)."""
    if value == pin or value == int(pin):
        return True
    return isinstance(value, str) and pin in value and not re.fullmatch(r"[0-9a-fA-F:.\-+TZ]+", value)


def test_the_pin_check_reads_values_not_random_hex():
    assert _holds_pin("2468", "2468") and _holds_pin(2468, "2468") and _holds_pin("PIN 2468", "2468")
    assert not _holds_pin("9f02468ab1c3", "2468")                          # a hash
    assert not _holds_pin("5a2468e1-0c1d-4b3a-9f00-1234abcd5678", "2468")  # a uuid
    assert not _holds_pin("2026-10-07T12:00:00.246800+00:00", "2468")      # a timestamp
    # Readable text is always checked, hex-looking words included once spaced.
    assert _holds_pin("dead 2468", "2468") and _holds_pin("pin=2468", "2468")


# ── 1. managing stations ─────────────────────────────────────────────

def test_manager_creates_member_cannot_and_no_secrets_listed(store):
    made = make_station()
    assert len(made["pair_code"]) == 9 and made["pair_code"][4] == "-"
    assert app_client(MEMBER).post("/kids/stations", json={"business_id": BIZ, "name": "X", "pin": "1234"}).status_code == 403
    listed = app_client(MANAGER).get(f"/kids/stations?business_id={BIZ}").json()["stations"]
    assert listed[0]["name"] == "Welcome desk" and listed[0]["pairing"] is True
    assert not any(k in str(listed) for k in ("pin_hash", "token_hash", "pair_code_hash"))
    rows = store.t["checkin_stations"]
    assert rows and not any(_holds_pin(v, "2468") for row in rows for v in row.values())


def test_pin_must_be_digits(store):
    r = app_client(MANAGER).post("/kids/stations", json={"business_id": BIZ, "name": "X", "pin": "abcd"})
    assert r.status_code == 400


# ── 2. pairing ───────────────────────────────────────────────────────

def test_pair_code_works_once(store):
    made = make_station()
    first = app_client().post("/kids/station/pair", json={"code": made["pair_code"]})
    assert first.status_code == 200
    token = first.json()["token"]
    assert store.t["checkin_stations"][0]["token_hash"] == ks.token_hash(token)
    assert token not in str(store.t)
    again = app_client().post("/kids/station/pair", json={"code": made["pair_code"]})
    assert again.status_code == 404
    me = app_client(token=token).get("/kids/station/me").json()
    assert me["station"]["mode"] == "staff" and me["occasions"][0]["id"] == ENTRY


def test_expired_code_fails(store):
    made = make_station()
    store.t["checkin_stations"][0]["pair_expires_at"] = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    assert app_client().post("/kids/station/pair", json={"code": made["pair_code"]}).status_code == 404


def test_pairing_attempts_are_capped(store):
    for _ in range(10):
        app_client().post("/kids/station/pair", json={"code": "AAAA-AAAA"})
    assert app_client().post("/kids/station/pair", json={"code": "AAAA-AAAA"}).status_code == 429


def test_removed_or_repaired_station_token_stops_working(store):
    sid, token = paired()
    unlock = unlocked(token)
    new = app_client(MANAGER).post(f"/kids/stations/{sid}/pair", json={"business_id": BIZ}).json()
    token2 = app_client().post("/kids/station/pair", json={"code": new["pair_code"]}).json()["token"]
    assert app_client(token=token).get("/kids/station/me").status_code == 401
    # The old unlock died with the old token.
    assert app_client(token=token2, unlock=unlock).get("/kids/station/families?q=Rivers").status_code == 423
    assert app_client(MANAGER).delete(f"/kids/stations/{sid}?business_id={BIZ}").status_code == 200
    assert app_client(token=token2).get("/kids/station/me").status_code == 401


# ── 3. the PIN ───────────────────────────────────────────────────────

def test_pin_wrong_capped_and_needed(store):
    _, token = paired()
    c = app_client(token=token)
    assert c.post("/kids/station/unlock", json={"pin": "0000"}).status_code == 403
    assert app_client(token=token).get("/kids/station/families?q=Rivers").status_code == 423
    for _ in range(5):
        c.post("/kids/station/unlock", json={"pin": "0000"})
    assert c.post("/kids/station/unlock", json={"pin": "2468"}).status_code == 429


def test_unlock_expires(store, monkeypatch):
    _, token = paired()
    unlock = unlocked(token)
    assert app_client(token=token, unlock=unlock).get("/kids/station/families?q=Ri").status_code == 200
    real = time.time
    monkeypatch.setattr(ks.time, "time", lambda: real() + ks.UNLOCK_SECONDS + 5)
    assert app_client(token=token, unlock=unlock).get("/kids/station/families?q=Ri").status_code == 423


def test_manager_can_change_the_pin(store):
    sid, token = paired()
    app_client(MANAGER).patch(f"/kids/stations/{sid}", json={"business_id": BIZ, "pin": "13579"})
    assert app_client(token=token).post("/kids/station/unlock", json={"pin": "2468"}).status_code == 403
    assert app_client(token=token).post("/kids/station/unlock", json={"pin": "13579"}).status_code == 200


# ── 4. staff station ─────────────────────────────────────────────────

def test_staff_station_finds_checks_in_and_releases(store, texts):
    fid, (mia, leo) = _ck.family(store, custody="")
    _, token = paired()
    s = app_client(token=token, unlock=unlocked(token))
    found = s.get("/kids/station/families?q=2030").json()["families"]
    assert [f["name"] for f in found] == ["The Rivers family"]
    assert found[0]["adults"][0]["phone_last4"] == "2030"
    assert "phone" not in found[0]["adults"][0] and "medical" not in str(found) and "custody" not in str(found)
    r = s.post("/kids/station/checkin", json={"entry_id": ENTRY, "household_id": fid,
                                              "children": [{"child_id": mia}, {"child_id": leo}],
                                              "dropped_off_by": PARENT, "text_code": True})
    assert r.status_code == 200, r.text
    row = store.t["child_checkins"][0]
    assert row["method"] == "station" and row["station_id"] and row["checked_in_by"] is None
    assert texts["to"] and r.json()["code"] in texts["to"][0][1]
    code = r.json()["code"]
    look = s.post("/kids/station/checkout/lookup", json={"entry_id": ENTRY, "code": code}).json()
    assert look["can_release_to_anyone"] is False
    ids = [k["id"] for k in look["children"]]
    assert s.post("/kids/station/checkout", json={"entry_id": ENTRY, "code": code, "checkin_ids": ids,
                                                  "released_to": "Aunt Bea"}).status_code == 403
    assert s.post("/kids/station/checkout", json={"entry_id": ENTRY, "code": code, "checkin_ids": ids,
                                                  "released_to": "Grandma June"}).status_code == 200


def test_staff_station_never_releases_a_custody_family(store):
    fid, (mia, _) = _ck.family(store, custody="Never release to R. Doe")
    _, token = paired()
    s = app_client(token=token, unlock=unlocked(token))
    code = s.post("/kids/station/checkin", json={"entry_id": ENTRY, "household_id": fid,
                                                 "children": [{"child_id": mia}]}).json()["code"]
    look = s.post("/kids/station/checkout/lookup", json={"entry_id": ENTRY, "code": code}).json()
    assert look["custody_alert"] is True and look["can_release"] is False and "Doe" not in str(look)
    r = s.post("/kids/station/checkout", json={"entry_id": ENTRY, "code": code,
                                               "checkin_ids": [look["children"][0]["id"]], "released_to": "Ana Rivers"})
    assert r.status_code == 403


def test_station_only_reaches_todays_services(store):
    fid, (mia, _) = _ck.family(store)
    _, token = paired()
    s = app_client(token=token, unlock=unlocked(token))
    r = s.post("/kids/station/checkin", json={"entry_id": LATER, "household_id": fid, "children": [{"child_id": mia}]})
    assert r.status_code == 403 and store.t["child_checkins"] == []


# ── 5. self kiosk ────────────────────────────────────────────────────

def test_self_kiosk_by_mobile_number(store, texts):
    fid, (mia, leo) = _ck.family(store)
    _, token = paired("self")
    k = app_client(token=token)
    found = k.post("/kids/station/self/find", json={"phone": "555.010.2030"})
    assert found.status_code == 200, found.text
    body = found.json()
    assert {c["first_name"] for c in body["children"]} == {"Mia", "Leo"}
    assert "Rivers" not in str(body["children"]) and "allergies" not in str(body)
    r = k.post("/kids/station/self/checkin", json={"entry_id": ENTRY, "phone": "(555) 010-2030", "child_ids": [mia]})
    assert r.status_code == 200, r.text
    assert r.json()["texted"] == "sent" and texts["to"][0][0] == "+15550102030"
    assert r.json()["checkins"][0]["allergies"] == "Peanuts"  # for the name tag
    assert "dropped_off_by" not in r.json()["checkins"][0]
    row = store.t["child_checkins"][0]
    assert row["method"] == "self" and str(row["dropped_off_by"]) == PARENT


def test_self_kiosk_unknown_and_shared_numbers_look_the_same(store):
    _ck.family(store)
    _, token = paired("self")
    k = app_client(token=token)
    unknown = k.post("/kids/station/self/find", json={"phone": "555 010 9999"})
    # Two families sharing one number: nobody is shown.
    store.t["contacts"].append({"id": "cccccccc-0000-0000-0000-000000000009", "business_id": BIZ, "name": "Sam", "email": "",
                                "phone": "5550102030"})
    other = app_client(OWNER).post("/kids/families", json={"business_id": BIZ, "name": "Other",
                                                            "adults": [{"contact_id": "cccccccc-0000-0000-0000-000000000009"}]})
    assert other.status_code == 200
    shared = k.post("/kids/station/self/find", json={"phone": "5550102030"})
    assert unknown.status_code == shared.status_code == 404
    assert unknown.json() == shared.json()


def test_self_kiosk_cannot_check_in_another_familys_child(store):
    _, token = paired("self")
    fid, (mia, _) = _ck.family(store)
    fid2, (zoe,) = _ck.family(store, names=("Zoe",))
    store.t["household_adults"] = [a for a in store.t["household_adults"] if a["household_id"] != fid2]
    r = app_client(token=token).post("/kids/station/self/checkin", json={"entry_id": ENTRY, "phone": "5550102030",
                                                                        "child_ids": [zoe]})
    assert r.status_code == 404 and store.t["child_checkins"] == []


def test_self_kiosk_cannot_do_staff_things(store):
    _ck.family(store)
    _, token = paired("self")
    unlock = unlocked(token)
    k = app_client(token=token, unlock=unlock)
    assert k.get("/kids/station/families?q=Rivers").status_code == 403
    assert k.get(f"/kids/station/checkins?entry_id={ENTRY}").status_code == 403
    assert k.post("/kids/station/checkout/lookup", json={"entry_id": ENTRY, "code": "AAAA"}).status_code == 403


def test_staff_station_cannot_self_check_in(store):
    _, token = paired("staff")
    assert app_client(token=token).post("/kids/station/self/find", json={"phone": "5550102030"}).status_code == 403


def test_number_lookups_are_capped(store):
    _ck.family(store)
    _, token = paired("self")
    k = app_client(token=token)
    for _ in range(40):
        k.post("/kids/station/self/find", json={"phone": "5550109999"})
    assert k.post("/kids/station/self/find", json={"phone": "5550102030"}).status_code == 429


def test_no_token_no_station(store):
    assert app_client().get("/kids/station/me").status_code == 401
    assert app_client(token="x" * 40).get("/kids/station/me").status_code == 401


def test_a_station_marked_removed_is_refused_even_with_its_token_on_file(store):
    """Removing a station clears the token AND marks it removed; either
    alone must be enough (a direct database fix may set only the mark)."""
    _, token = paired()
    store.t["checkin_stations"][0]["revoked_at"] = "2026-09-30T00:00:00+00:00"
    assert app_client(token=token).get("/kids/station/me").status_code == 401
