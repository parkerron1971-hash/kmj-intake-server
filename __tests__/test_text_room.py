"""The Text room's people pieces (text_room.py, Kevin 2026-10-30).

A guest saved from Text is named, not duplicated (the keyword already made
a contact named with the number), and at a church gets a welcome follow-up
that never carries what they texted. A text put on the prayer list stays
with the pastors unless the office shares it, and words about danger stay
with the pastors whatever is chosen. Saved replies are trimmed and capped.
"""
from __future__ import annotations

import inspect
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import text_room

BIZ = "7c0de000-0000-4000-8000-000000000001"
MSG = "11111111-1111-4111-8111-111111111111"
USER = SimpleNamespace(id="seat-1")


class FakeDb:
    """Every service-role call, answered from tables and recorded."""

    def __init__(self, tables=None, church=True):
        self.tables = tables or {}
        self.calls = []
        self.church = church

    def get(self, path):
        self.calls.append(("GET", path, None))
        table = path.split("?")[0].strip("/")
        if table == "businesses":
            return [{"id": BIZ, "name": "Grace Grove", "type": "ministry" if self.church else "coaching",
                     "settings": self.tables.get("settings", {"news": {"celebrate": "all"}})}]
        return [dict(r) for r in self.tables.get(table, [])]

    def post(self, path, body, *a, **k):
        self.calls.append(("POST", path, body))
        return [{"id": "new-1", **body}]

    def patch(self, path, body):
        self.calls.append(("PATCH", path, body))
        return [{}]


@pytest.fixture
def db(monkeypatch):
    import business_access
    import church_follow_up
    import sb_clients
    fake = FakeDb()
    gate = []
    started = []
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda p, **k: fake.get(p))
    monkeypatch.setattr(sb_clients, "sb_post_as_service", fake.post)
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", fake.patch)
    monkeypatch.setattr(business_access, "assert_access", lambda b, u, r: gate.append(r))
    monkeypatch.setattr(church_follow_up, "is_church", lambda b: b.get("type") == "ministry")

    def start(biz, cid, **kw):
        started.append(kw)
        return {"id": "fu-1", "leader_contact_id": None}

    monkeypatch.setattr(church_follow_up, "start", start)
    fake.gate, fake.started = gate, started
    return fake


GUARDED = [
    ("save_guest", "member"), ("add_prayer", "member"), ("put_replies", "member"),
    ("prayer_marks", "viewer"), ("get_replies", "viewer"),
]


@pytest.mark.parametrize("fn,role", GUARDED)
def test_every_handler_checks_whose_business_first(fn, role):
    src = inspect.getsource(getattr(text_room, fn))
    assert f'assert_access(biz, user, "{role}")' in src
    gate = src.index("assert_access")
    for marker in ("sb_clients.sb_", "_business(", "_contact_by_phone("):
        at = src.find(marker)
        if at != -1:
            assert gate < at, f"{fn}: the check runs after {marker}"


# ─── a guest ─────────────────────────────────────────────────────────

def test_the_keywords_contact_is_named_not_duplicated(db):
    db.tables["contacts"] = [{"id": "c-9", "name": "+12165550199", "phone": "+12165550199", "tags": None}]
    out = text_room.save_guest(text_room.GuestIn(business_id=BIZ, name=" Jordan  Miles ", phone="(216) 555-0199"), USER)
    assert out["contact_id"] == "c-9" and out["created"] is False
    patches = [(p, b) for m, p, b in db.calls if m == "PATCH" and p.startswith("/contacts")]
    assert patches == [(f"/contacts?id=eq.c-9&business_id=eq.{BIZ}",
                        {"name": "Jordan Miles", "tags": ["first-time guest"]})]
    assert not [c for c in db.calls if c[0] == "POST" and c[1] == "/contacts"]


def test_a_new_number_becomes_a_guest_and_its_texts_follow(db):
    out = text_room.save_guest(text_room.GuestIn(business_id=BIZ, name="Jordan", phone="+12165550199"), USER)
    assert out["created"] is True and out["contact_id"] == "new-1"
    [made] = [b for m, p, b in db.calls if m == "POST" and p == "/contacts"]
    assert made["status"] == "lead" and made["tags"] == ["first-time guest"] and made["phone"] == "+12165550199"
    linked = [p for m, p, b in db.calls if m == "PATCH" and p.startswith("/sms_messages")]
    assert linked and "phone_number=eq.%2B12165550199" in linked[0] and "contact_id=is.null" in linked[0]


def test_someone_already_named_keeps_their_name(db):
    db.tables["contacts"] = [{"id": "c-2", "name": "Dana Johnson", "phone": "+12165550142"}]
    out = text_room.save_guest(text_room.GuestIn(business_id=BIZ, name="Somebody Else", phone="+12165550142"), USER)
    assert out["contact_id"] == "c-2"
    assert not [c for c in db.calls if c[0] == "PATCH" and c[1].startswith("/contacts")]


def test_the_welcome_follow_up_never_carries_their_words(db):
    out = text_room.save_guest(text_room.GuestIn(business_id=BIZ, name="Jordan", phone="+12165550199"), USER)
    [kw] = db.started
    assert kw["kind"] == "connect" and kw["route_answers"] == []
    said = " ".join(a["a"] for a in kw["answers"])
    assert "conversation is in Text" in said
    assert out["follow_up"] is True


def test_outside_a_church_there_is_no_follow_up_or_guest_tag(db):
    db.church = False
    out = text_room.save_guest(text_room.GuestIn(business_id=BIZ, name="Jordan", phone="+12165550199"), USER)
    assert not db.started and out["follow_up"] is False
    [made] = [b for m, p, b in db.calls if m == "POST" and p == "/contacts"]
    assert "tags" not in made


@pytest.mark.parametrize("name,phone", [("  ", "+12165550199"), ("+1 216 555 0199", "+12165550199"), ("Jordan", "12")])
def test_a_name_and_a_number_are_required(db, name, phone):
    with pytest.raises(HTTPException) as e:
        text_room.save_guest(text_room.GuestIn(business_id=BIZ, name=name, phone=phone), USER)
    assert e.value.status_code == 400


# ─── the prayer list ─────────────────────────────────────────────────

def _msg(text="Please pray for my mom's surgery Thursday."):
    return [{"id": MSG, "contact_id": "c-1", "phone_number": "+12165550142", "message": text}]


def test_a_text_on_the_prayer_list_stays_with_the_pastors(db, monkeypatch):
    import church_prayer
    handed = []
    monkeypatch.setattr(church_prayer, "on_new", lambda b, row: handed.append(row))
    db.tables.update(sms_messages=_msg(), contacts=[{"name": "Dana Johnson", "email": "dana@example.com"}])
    out = text_room.add_prayer(text_room.PrayerIn(business_id=BIZ, message_id=MSG), USER)
    [row] = [b for m, p, b in db.calls if m == "POST" and p == "/ministry_care_requests"]
    assert row["prayer_team"] is False and row["submission"]["confidential"] == "yes"
    assert row["submission"]["source"] == "Text" and row["submission"]["sms_message_id"] == MSG
    assert row["contact_id"] == "c-1" and handed
    assert out["shared"] is False


def test_shared_only_when_the_office_says_so_and_never_with_danger(db, monkeypatch):
    import church_prayer
    monkeypatch.setattr(church_prayer, "on_new", lambda b, row: None)
    db.tables["sms_messages"] = _msg()
    text_room.add_prayer(text_room.PrayerIn(business_id=BIZ, message_id=MSG, share=True), USER)
    db.tables["sms_messages"] = _msg("My husband beat me last night, please pray.")
    text_room.add_prayer(text_room.PrayerIn(business_id=BIZ, message_id=MSG, share=True), USER)
    rows = [b for m, p, b in db.calls if m == "POST" and p == "/ministry_care_requests"]
    assert rows[0]["prayer_team"] is True
    assert rows[1]["prayer_team"] is False and rows[1]["needs_pastor"] is True


def test_a_text_goes_on_the_list_once(db):
    db.tables.update(sms_messages=_msg(), ministry_care_requests=[{"id": "r1", "prayer_team": False, "needs_pastor": False}])
    out = text_room.add_prayer(text_room.PrayerIn(business_id=BIZ, message_id=MSG), USER)
    assert out["already"] is True
    assert not [c for c in db.calls if c[0] == "POST"]


def test_the_prayer_list_is_a_churchs(db):
    db.church = False
    with pytest.raises(HTTPException) as e:
        text_room.add_prayer(text_room.PrayerIn(business_id=BIZ, message_id=MSG), USER)
    assert e.value.status_code == 400


def test_which_texts_are_on_the_list(db):
    db.tables["ministry_care_requests"] = [{"submission": {"sms_message_id": MSG}, "prayer_team": True}]
    out = text_room.prayer_marks(business_id=BIZ, ids=f"{MSG},", user=USER)
    assert out == {"on_list": {MSG: {"shared": True}}}
    [(_, path, _)] = [c for c in db.calls if c[1].startswith("/ministry_care_requests")]
    assert f"submission->>sms_message_id=in.({MSG})" in path


# ─── saved replies ───────────────────────────────────────────────────

def test_replies_are_trimmed_one_per_label_and_capped():
    raw = [{"label": " Service  times ", "text": " Sunday 10 AM "}, {"label": "service times", "text": "dup"},
           {"label": "", "text": "no label"}, {"label": "Empty", "text": "  "}]
    raw += [{"label": f"R{i}", "text": "x"} for i in range(20)]
    out = text_room.clean_replies(raw)
    assert out[0] == {"label": "Service times", "text": "Sunday 10 AM"}
    assert len(out) == text_room.MAX_REPLIES
    assert all(r["label"] != "Empty" for r in out)


def test_saving_replies_keeps_the_rest_of_the_settings(db):
    body = text_room.RepliesIn(business_id=BIZ, replies=[{"label": "Giving", "text": "gracegrove.org/give"}])
    text_room.put_replies(body, USER)
    [(_, path, patch)] = [c for c in db.calls if c[0] == "PATCH"]
    assert path == f"/businesses?id=eq.{BIZ}"
    assert patch["settings"]["news"] == {"celebrate": "all"}
    assert patch["settings"]["sms_replies"] == [{"label": "Giving", "text": "gracegrove.org/give"}]
