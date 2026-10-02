# __tests__/test_kids_checkin.py
#
# Children's check-in and pickup (kids_checkin.py). Pins:
#   1. one four-character code per family per occasion, from the no-look-
#      alike alphabet; a sibling checked in later shares it; checking in
#      again is harmless; another family's or an inactive child is refused;
#      a child who already went home can't be checked in again
#   2. pickup: the code finds the children still in and who may take
#      them; a team member releases only to someone on that list, a
#      manager to anyone; releasing twice is refused (409)
#   3. custody: a member learns only THAT there is a note and can't
#      release; a manager reads it and can
#   4. the code text: straight to the carrier (never send_sms_core), STOP
#      honoured, an extension stripped, and the reply says what happened
#   5. seats: viewers and strangers get nothing; undo only before pickup

import importlib.util
import pathlib
import sys

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import kids_checkin as kc
import kids_router as kr
from auth_supabase import AuthedUser, require_user

_spec = importlib.util.spec_from_file_location("kids_store", HERE / "test_kids_router.py")
_base = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_base)
BIZ, OTHER, OWNER, MANAGER, MEMBER, VIEWER, STRANGER, PARENT = (
    _base.BIZ, _base.OTHER, _base.OWNER, _base.MANAGER, _base.MEMBER, _base.VIEWER, _base.STRANGER, _base.PARENT)
ENTRY = "eeeeeeee-0000-0000-0000-000000000001"
OTHER_ENTRY = "eeeeeeee-0000-0000-0000-000000000002"


class Store(_base.Store):
    def __init__(self):
        super().__init__()
        self.t["module_entries"] = [{"id": ENTRY, "business_id": BIZ, "data": {"title": "Sunday Service"}},
                                    {"id": OTHER_ENTRY, "business_id": OTHER, "data": {"title": "Theirs"}}]
        self.t["child_checkins"] = []
        self.t["businesses"][0]["name"] = "First Light"
        self.t["contacts"][0]["phone"] = "(555) 010-2030 x2"

    def _match(self, row, params):
        for k, v in params:
            if v == "is.null" and row.get(k) is not None:
                return False
        # PostgREST writes booleans lower-case.
        row = {k: (str(v).lower() if isinstance(v, bool) else v) for k, v in row.items()}
        return super()._match(row, [(k, v) for k, v in params if v != "is.null"])

    def post(self, path, body, prefer=None):
        if path.startswith("/children") and isinstance(body, dict):
            body = {"active": True, "room": "", **body}  # the table's defaults
        if path.startswith("/child_checkins") and isinstance(body, list):
            body = [{"checked_in_at": self._stamp(), "checked_out_at": None, "released_to": None, **b} for b in body]
        if isinstance(body, list):
            out = []
            for b in body:
                r = super().post(path, b, prefer)
                if r is None:
                    return None
                out += r
            return out
        return super().post(path, body, prefer)


@pytest.fixture
def store(monkeypatch):
    s = Store()
    for mod in (kr, kc):
        monkeypatch.setattr(mod.sb_clients, "sb_get_as_service", s.get)
        monkeypatch.setattr(mod.sb_clients, "sb_post_as_service", s.post)
        monkeypatch.setattr(mod.sb_clients, "sb_patch_as_service", s.patch)
        monkeypatch.setattr(mod.sb_clients, "sb_delete_as_service", s.delete)
    return s


@pytest.fixture
def texts(monkeypatch):
    """Records what would be texted; nothing leaves the test."""
    import sms_service
    import twilio_sms
    sent = {"to": [], "opted_out": set()}
    monkeypatch.setattr(sms_service, "_twilio_configured", lambda: True)

    async def opted_out(client, phone, business_id=None):
        return phone in sent["opted_out"]

    async def sender_for(client, business_id):
        return "+15550009999"
    monkeypatch.setattr(sms_service, "is_opted_out", opted_out)
    monkeypatch.setattr(sms_service, "sender_for", sender_for)
    monkeypatch.setattr(twilio_sms, "send_sms", lambda to, body, from_number=None: sent["to"].append((to, body)) or "SM1")

    async def never(*a, **k):
        raise AssertionError("pickup codes must never go through send_sms_core (text history)")
    monkeypatch.setattr(sms_service, "send_sms_core", never, raising=False)
    return sent


def client(user_id):
    app = FastAPI()
    app.include_router(kr.router)
    app.include_router(kc.router)
    app.dependency_overrides[require_user] = lambda: AuthedUser(id=user_id, email=None, role="authenticated")
    return TestClient(app)


def family(store, custody="", names=("Mia", "Leo"), inactive=()):
    c = client(OWNER)
    fid = c.post("/kids/families", json={"business_id": BIZ, "name": "The Rivers family",
                                          "adults": [{"contact_id": PARENT}]}).json()["family"]["id"]
    kids = []
    for n in names:
        body = {"business_id": BIZ, "household_id": fid, "first_name": n, "room": "Preschool",
                "allergies": "Peanuts" if n == "Mia" else ""}
        if custody and n == names[0]:
            body["custody"] = custody
        kid = c.post("/kids/children", json=body).json()["child"]
        if n in inactive:
            c.patch(f"/kids/children/{kid['id']}", json={"business_id": BIZ, "active": False})
        kids.append(kid["id"])
    c.post(f"/kids/families/{fid}/pickups", json={"business_id": BIZ, "name": "Grandma June", "relationship": "Grandmother"})
    return fid, kids


def check_in(as_user, fid, kids, **extra):
    return client(as_user).post("/kids/checkin", json={
        "business_id": BIZ, "entry_id": ENTRY, "household_id": fid,
        "children": [{"child_id": k} for k in kids], **extra})


# ── 1. check in ──────────────────────────────────────────────────────

def test_one_code_per_family_shared_by_a_sibling_checked_in_later(store):
    fid, (mia, leo) = family(store)
    first = check_in(MEMBER, fid, [mia])
    assert first.status_code == 200, first.text
    code = first.json()["code"]
    assert len(code) == 4 and set(code) <= set(kc.CODE_ALPHABET)
    kid = first.json()["checkins"][0]
    assert kid["first_name"] == "Mia" and kid["room"] == "Preschool" and kid["allergies"] == "Peanuts"
    later = check_in(MEMBER, fid, [leo])
    assert later.json()["code"] == code
    again = check_in(MEMBER, fid, [mia])  # harmless
    assert again.status_code == 200 and len(store.t["child_checkins"]) == 2


def test_other_family_and_inactive_children_are_refused(store):
    fid, (mia, leo) = family(store, inactive=("Leo",))
    assert check_in(MEMBER, fid, [leo]).status_code == 404
    other_fid = client(OWNER).post("/kids/families", json={"business_id": BIZ, "name": "Other"}).json()["family"]["id"]
    assert check_in(MEMBER, other_fid, [mia]).status_code == 404
    assert store.t["child_checkins"] == []


def test_another_churchs_occasion_is_refused(store):
    fid, (mia, _) = family(store)
    r = client(MEMBER).post("/kids/checkin", json={"business_id": BIZ, "entry_id": OTHER_ENTRY,
                                                    "household_id": fid, "children": [{"child_id": mia}]})
    assert r.status_code == 404


def test_codes_differ_between_families(store, monkeypatch):
    fid, (mia, _) = family(store)
    fid2, (zoe,) = family(store, names=("Zoe",))
    seq = iter("AAAA" + "AAAA" + "CCCC")
    monkeypatch.setattr(kc.secrets, "choice", lambda alphabet: next(seq))
    a = check_in(MEMBER, fid, [mia]).json()["code"]
    b = check_in(MEMBER, fid2, [zoe]).json()["code"]
    assert (a, b) == ("AAAA", "CCCC")


# ── 2. pick up ───────────────────────────────────────────────────────

def test_pickup_by_code_to_someone_on_the_list(store):
    fid, (mia, leo) = family(store)
    code = check_in(MEMBER, fid, [mia, leo]).json()["code"]
    c = client(MEMBER)
    look = c.post("/kids/checkout/lookup", json={"business_id": BIZ, "entry_id": ENTRY, "code": code.lower()})
    assert look.status_code == 200
    body = look.json()
    assert {k["first_name"] for k in body["children"]} == {"Mia", "Leo"}
    assert {a["name"] for a in body["allowed"]} == {"Ana Rivers", "Grandma June"}
    assert body["can_release"] is True and body["can_release_to_anyone"] is False
    ids = [k["id"] for k in body["children"]]
    stranger = c.post("/kids/checkout", json={"business_id": BIZ, "entry_id": ENTRY, "code": code,
                                               "checkin_ids": ids, "released_to": "R. Doe"})
    assert stranger.status_code == 403
    ok = c.post("/kids/checkout", json={"business_id": BIZ, "entry_id": ENTRY, "code": code,
                                         "checkin_ids": ids, "released_to": "grandma june"})
    assert ok.status_code == 200
    assert all(r["released_to"] == "grandma june" and r["checked_out_at"] for r in store.t["child_checkins"])
    twice = c.post("/kids/checkout", json={"business_id": BIZ, "entry_id": ENTRY, "code": code,
                                            "checkin_ids": ids, "released_to": "Ana Rivers"})
    assert twice.status_code == 409
    assert c.post("/kids/checkout/lookup", json={"business_id": BIZ, "entry_id": ENTRY, "code": code}).status_code == 404
    # …and a child who went home can't be checked back in to the same one.
    assert check_in(MEMBER, fid, [mia]).status_code == 409


def test_manager_may_release_to_someone_not_on_the_list(store):
    fid, (mia, _) = family(store)
    code = check_in(MEMBER, fid, [mia]).json()["code"]
    ids = [r["id"] for r in store.t["child_checkins"]]
    r = client(MANAGER).post("/kids/checkout", json={"business_id": BIZ, "entry_id": ENTRY, "code": code,
                                                      "checkin_ids": ids, "released_to": "Aunt Bea"})
    assert r.status_code == 200


def test_wrong_code_finds_nothing(store):
    fid, (mia, _) = family(store)
    check_in(MEMBER, fid, [mia])
    c = client(MEMBER)
    assert c.post("/kids/checkout/lookup", json={"business_id": BIZ, "entry_id": ENTRY, "code": "ZZ"}).status_code == 400
    r = c.post("/kids/checkout/lookup", json={"business_id": BIZ, "entry_id": ENTRY, "code": "QQQQ"})
    assert r.status_code == 404


# ── 3. custody ───────────────────────────────────────────────────────

def test_custody_note_means_a_manager_releases(store):
    fid, (mia, leo) = family(store, custody="Never release to R. Doe")
    code = check_in(MEMBER, fid, [mia, leo]).json()["code"]
    look = client(MEMBER).post("/kids/checkout/lookup", json={"business_id": BIZ, "entry_id": ENTRY, "code": code}).json()
    assert look["custody_alert"] is True and look["can_release"] is False
    assert "Doe" not in str(look)
    ids = [k["id"] for k in look["children"]]
    refused = client(MEMBER).post("/kids/checkout", json={"business_id": BIZ, "entry_id": ENTRY, "code": code,
                                                           "checkin_ids": ids, "released_to": "Ana Rivers"})
    assert refused.status_code == 403
    assert all(r["checked_out_at"] is None for r in store.t["child_checkins"])
    mlook = client(MANAGER).post("/kids/checkout/lookup", json={"business_id": BIZ, "entry_id": ENTRY, "code": code}).json()
    assert "Never release to R. Doe" in mlook["children"][0]["custody"]
    ok = client(MANAGER).post("/kids/checkout", json={"business_id": BIZ, "entry_id": ENTRY, "code": code,
                                                       "checkin_ids": ids, "released_to": "Ana Rivers"})
    assert ok.status_code == 200


def test_member_room_list_flags_custody_without_the_note(store):
    fid, (mia, _) = family(store, custody="Never release to R. Doe")
    check_in(MEMBER, fid, [mia])
    body = client(MEMBER).get(f"/kids/checkins?business_id={BIZ}&entry_id={ENTRY}").json()
    assert body["checkins"][0]["custody_alert"] is True
    assert "custody" not in body["checkins"][0]


# ── 4. the text ──────────────────────────────────────────────────────

def test_code_is_texted_straight_to_the_carrier(store, texts):
    fid, (mia, leo) = family(store)
    r = check_in(MEMBER, fid, [mia, leo], dropped_off_by=PARENT, text_code=True).json()
    assert r["texted"] == "sent" and r["texted_to"] == "•••• 2030"
    (to, body), = texts["to"]
    assert to == "+15550102030"  # the "x2" extension stripped
    assert r["code"] in body and "Mia and Leo are checked in" in body and "First Light" in body
    # The parent was here today.
    assert store.t["contacts"][0].get("last_interaction")


def test_stop_is_honoured_and_said(store, texts):
    texts["opted_out"].add("+15550102030")
    fid, (mia, _) = family(store)
    r = check_in(MEMBER, fid, [mia], dropped_off_by=PARENT, text_code=True).json()
    assert r["texted"] == "opted_out" and texts["to"] == []


def test_no_mobile_and_no_adult_are_said_not_faked(store, texts):
    store.t["contacts"][0]["phone"] = ""
    fid, (mia, leo) = family(store)
    assert check_in(MEMBER, fid, [mia], dropped_off_by=PARENT, text_code=True).json()["texted"] == "no_mobile"
    assert check_in(MEMBER, fid, [leo], text_code=True).json()["texted"] == "no_adult"
    assert texts["to"] == []


def test_a_stranger_cannot_be_the_drop_off_adult(store):
    fid, (mia, _) = family(store)
    r = check_in(MEMBER, fid, [mia], dropped_off_by=_base.OTHER_PARENT)
    assert r.status_code == 400 and store.t["child_checkins"] == []


# ── 5. seats and undo ────────────────────────────────────────────────

@pytest.mark.parametrize("who", [VIEWER, STRANGER])
def test_viewers_and_strangers_get_nothing(store, who):
    fid, (mia, _) = family(store)
    code = check_in(MEMBER, fid, [mia]).json()["code"]
    c = client(who)
    assert c.get(f"/kids/checkins?business_id={BIZ}&entry_id={ENTRY}").status_code == 403
    assert check_in(who, fid, [mia]).status_code == 403
    r = c.post("/kids/checkout/lookup", json={"business_id": BIZ, "entry_id": ENTRY, "code": code})
    assert r.status_code == 403 and "Mia" not in r.text


def test_undo_only_before_pickup(store):
    fid, (mia, leo) = family(store)
    code = check_in(MEMBER, fid, [mia, leo]).json()["code"]
    rows = {r["child_id"]: r["id"] for r in store.t["child_checkins"]}
    c = client(MEMBER)
    assert c.delete(f"/kids/checkins/{rows[leo]}?business_id={BIZ}").status_code == 200
    c.post("/kids/checkout", json={"business_id": BIZ, "entry_id": ENTRY, "code": code,
                                   "checkin_ids": [rows[mia]], "released_to": "Ana Rivers"})
    assert c.delete(f"/kids/checkins/{rows[mia]}?business_id={BIZ}").status_code == 409


def test_failed_read_is_unavailable(store):
    fid, (mia, _) = family(store)
    store.fail.add("child_checkins")
    assert check_in(MEMBER, fid, [mia]).status_code == 503


def test_mobile_normalising():
    assert kc.mobile("(555) 010-2030 x2") == "+15550102030"
    assert kc.mobile("555.010.2030 ext. 14") == "+15550102030"
    assert kc.mobile("") == "" and kc.mobile("12") == ""


def test_a_release_racing_another_volunteer_is_refused(store):
    """Two volunteers type the same code at once. The second one's save is
    conditional on the children still being in, so it can't record a
    second, different 'went home with'."""
    fid, (mia, leo) = family(store)
    code = check_in(MEMBER, fid, [mia, leo]).json()["code"]
    ids = [r["id"] for r in store.t["child_checkins"]]
    real_patch = store.patch

    def racing_patch(path, body):
        if path.startswith("/child_checkins"):
            # The other volunteer's release lands first, for Mia.
            store.t["child_checkins"][0].update(checked_out_at="2026-09-29T21:00:00+00:00", released_to="Ana Rivers")
        return real_patch(path, body)
    store.patch = racing_patch
    kc.sb_clients.sb_patch_as_service = racing_patch
    r = client(MEMBER).post("/kids/checkout", json={"business_id": BIZ, "entry_id": ENTRY, "code": code,
                                                     "checkin_ids": ids, "released_to": "Grandma June"})
    assert r.status_code == 409
    assert store.t["child_checkins"][0]["released_to"] == "Ana Rivers"
