"""Church email (church_mail.py, chief_church_mail.py, the first step of
email_sender.inbound_email).

Kevin, 2026-11-11: "I want to make sure chief knows how to get people there
email with the @domain name for each church"; "prayer would go to the leader
of prayer so assign that to that role"; "if a person is removed automatically
the emails etc is as well". 2026-11-13: "can we build what is needed so this
can go live right away?"

Pins:
  * mail to a church address is sorted by the church first: it never reaches
    another business's contact match or the Mission Control catch-all, and a
    read that fails is a 503 (Resend retries), never a misroute
  * who a box reaches is looked up each time: a login taken off the team, a
    leader out of every role, a role nobody holds all move the mail on
    (the office box, the role it answers to, the pastor) with nothing to clean
  * prayer@ joins the prayer list and is handed to the prayer leader; its
    words are never copied into an inbox; danger words stay with the pastor
  * a copy goes from the box's address, Reply-To the sender, with the
    attachments, no platform unsubscribe, marked so it can't loop
  * mail that fails its sender checks, or our own copy coming back, is kept
    and never copied
  * the same webhook twice writes one row and sends one copy
  * only the pastor or an Admin gives out or takes back an address; Chief's
    `to` names a login, a person, a role, the prayer list, the office or an
    outside address; a person is matched by name only when it's one person

The tables are faked in memory with the PostgREST filters the module uses."""
from __future__ import annotations

import asyncio
import os
import re
import sys
import uuid
from types import SimpleNamespace

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.dirname(os.path.abspath(__file__))
for p in (ROOT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import church_mail  # noqa: E402
import chief_church_mail  # noqa: E402
import email_sender  # noqa: E402
import messaging_router  # noqa: E402
import sb_clients  # noqa: E402
from test_church_follow_up import FakeDB as _Base, _cmp  # noqa: E402

BIZ = "009e9a2c-3e81-4bfc-a92a-205a8806aa99"
OTHER = "11111111-1111-4111-8111-111111111111"
OWNER = "22222222-2222-4222-8222-222222222222"
JESSICA, TIA, MANAGER = (f"44444444-4444-4444-8444-00000000000{i}" for i in range(1, 4))
KEVIN_C, MINNIE_C, ANDRE_C, JESS_C, STRANGER_C, NOBODY_C = (f"00000000-0000-4000-8000-00000000000{i}"
                                                            for i in range(1, 7))
EMAILS = {OWNER: "pastor@example.com", JESSICA: "jess@example.com", TIA: "tia@example.com",
          MANAGER: "manny@example.com"}
DOMAIN = "lovecityc.com"


def _path(row, col):
    parts = re.split(r"->>?", col)
    v = row.get(parts[0])
    for p in parts[1:]:
        v = v.get(p) if isinstance(v, dict) else None
    return v


class DB(_Base):
    """The follow-up tests' PostgREST, plus JSON paths, `not.`, and the
    church_mail unique index."""

    def _match(self, row, filters):
        for f in filters:
            if f[0] == "or":
                if not super()._match(row, [f]):
                    return False
                continue
            col, op, val = f
            probe = {col: _path(row, col)}
            if op == "not":
                op2, _, val2 = val.partition(".")
                if _cmp(probe, col, op2, val2):
                    return False
            elif not _cmp(probe, col, op, val):
                return False
        return True

    def post(self, path, body, prefer=None, **_):
        table = path.lstrip("/").split("?")[0]
        if table == "church_mail" and any(r["email_id"] == body["email_id"] and r["to_address"] == body["to_address"]
                                          for r in self.t.get(table, [])):
            return None
        return super().post(path, body, prefer)


def _def(i, key, title, job, up=None, handles=()):
    return {"id": i, "business_id": BIZ, "key": key, "title": title, "job": job, "reports_to": up,
            "handles": list(handles), "sees": [], "oversees_teams": [], "covers": "", "status": "active", "sort": 0,
            "created_at": "2026-10-01T00:00:00+00:00"}


def _holder(cid, key):
    return {"id": str(uuid.uuid4()), "business_id": BIZ, "contact_id": cid, "role": key, "scope": "",
            "status": "active", "invited_at": "2026-10-01T00:00:00+00:00", "answered_at": None}


def _seat(uid, name, role="manager", contact=None):
    return {"id": str(uuid.uuid4()), "business_id": BIZ, "user_id": uid, "role": role, "status": "active",
            "name": name, "contact_id": contact, "invited_email": EMAILS[uid]}


def _box(local, kind, **kw):
    return {"id": str(uuid.uuid4()), "business_id": BIZ, "domain": DOMAIN, "local": local, "kind": kind,
            "user_id": None, "contact_id": None, "role_key": None, "share_with": [], "forward_to": None,
            "catch_all": False, "status": "active", "told_at": None, "created_at": "2026-11-13T00:00:00+00:00", **kw}


SETTINGS = {"practitioner_name": "Kevin McCloud",
            "email_domain": {"status": "verified", "domain": DOMAIN, "from_local_part": "hello"}}


@pytest.fixture
def db(monkeypatch):
    fake = DB(
        businesses=[{"id": BIZ, "name": "Love City Church", "type": "ministry", "owner_id": OWNER, "settings": SETTINGS},
                    {"id": OTHER, "name": "Grace Chapel", "type": "ministry", "owner_id": str(uuid.uuid4()),
                     "settings": {}}],
        business_users=[_seat(JESSICA, "Jessica McCloud", contact=JESS_C), _seat(TIA, "Tia Brown"),
                        _seat(MANAGER, "Manny Cole")],
        contacts=[{"id": KEVIN_C, "business_id": BIZ, "name": "Kevin McCloud", "email": "kevin.c@example.com", "phone": ""},
                  {"id": MINNIE_C, "business_id": BIZ, "name": "Minnie Hart", "email": "minnie@example.com", "phone": ""},
                  {"id": ANDRE_C, "business_id": BIZ, "name": "Andre Wallace", "email": "andre@example.com", "phone": ""},
                  {"id": JESS_C, "business_id": BIZ, "name": "Jessica McCloud", "email": "jess@example.com", "phone": ""},
                  {"id": NOBODY_C, "business_id": BIZ, "name": "Nora Quiet", "email": "nora@example.com", "phone": ""},
                  {"id": STRANGER_C, "business_id": OTHER, "name": "Sam Sender", "email": "sam@sender.example", "phone": ""}],
        church_role_defs=[_def("d-senior", "pastor", "Senior Pastor", "senior"),
                          _def("d-prayer", "intercessor_leader", "Intercessor Leader", "prayer", "d-senior",
                               ["prayer_shared"]),
                          _def("d-youth", "youth_leader", "Youth Leader", "ministry", "d-senior")],
        church_leader_roles=[_holder(KEVIN_C, "pastor"), _holder(MINNIE_C, "intercessor_leader"),
                             _holder(ANDRE_C, "youth_leader")],
        church_mailboxes=[], church_mail=[], ministry_care_requests=[], audit_log=[],
    )
    for name in ("get", "post", "patch", "delete"):
        monkeypatch.setattr(sb_clients, f"sb_{name}_as_service", getattr(fake, name))
    monkeypatch.setattr(messaging_router, "owner_email_read", lambda uid: EMAILS.get(str(uid), ""))

    async def _not_suppressed(email):
        return None
    monkeypatch.setattr(email_sender, "is_suppressed", _not_suppressed)
    monkeypatch.setenv("INBOUND_EMAIL_DOMAIN", "mysolutionist.app")
    monkeypatch.setattr(church_mail, "receiving_live", lambda d: d == DOMAIN)
    monkeypatch.delenv("CHURCH_MAIL_SECRET", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    church_mail._DOMAIN_CACHE.clear()
    church_mail._LIVE_CACHE.clear()
    return fake


class Resend:
    """The mail service: received messages by id, and what we sent."""

    def __init__(self):
        self.msgs, self.sent = {}, []

    def add(self, email_id, *, to, frm="sam@sender.example", name="Sam Sender", subject="Thursday", text="See you",
            html="<p>See you</p>", auth=("pass", "pass", "pass"), headers=None, attachments=()):
        self.msgs[email_id] = {
            "id": email_id, "from": frm, "to": to, "subject": subject, "text": text, "html": html,
            "headers": {"from": f"{name} <{frm}>", **(headers or {})}, "message_id": f"<{email_id}@mail.example>",
            "authentication": dict(zip(("spf", "dkim", "dmarc"), auth)) if auth else None,
            "attachments": [{"id": a["id"]} for a in attachments], "_links": list(attachments)}
        return {"type": "email.received", "data": {"email_id": email_id, "from": frm, "to": to, "cc": [],
                                                    "bcc": [], "received_for": [], "subject": subject}}

    async def __call__(self, client, method, path, **kw):
        if method == "GET" and path.endswith("/attachments"):
            mid = path.split("/")[3]
            return {"data": self.msgs[mid]["_links"]}
        if method == "GET":
            return dict(self.msgs[path.rsplit("/", 1)[1]])
        self.sent.append(kw["json"])
        return {"id": f"sent-{len(self.sent)}"}


@pytest.fixture
def resend(monkeypatch):
    r = Resend()
    monkeypatch.setattr(church_mail, "_resend", r)
    return r


def _inbound(payload):
    return asyncio.run(church_mail.handle_inbound(None, payload))


def _rows(db, table):
    return db.t.get(table, [])


# ─── Sorting by church first ──────────────────────────────────────────

class _Req:
    def __init__(self, body):
        self._b = body
        self.headers = {}

    async def body(self):
        return self._b


def test_church_mail_never_reaches_another_church_or_mission_control(db, resend, monkeypatch):
    """Sam is Grace Chapel's contact. Today his mail to any non-platform
    domain matched Grace Chapel by sender, or fell into Mission Control."""
    import json
    db.t["church_mailboxes"].append(_box("jessica", "person", user_id=JESSICA))
    payload = resend.add("m1", to=["jessica@lovecityc.com"])
    monkeypatch.setattr(email_sender, "_verify_resend_signature", lambda raw, headers: True)

    async def _nope(*a, **k):
        raise AssertionError("church mail went to the platform's sorting")
    monkeypatch.setattr(email_sender, "_sb_get", _nope)
    monkeypatch.setattr(email_sender, "_sb_post", _nope)
    out = asyncio.run(email_sender.inbound_email(_Req(json.dumps(payload).encode())))
    assert out["status"] == "church_mail"
    assert [s["to"] for s in resend.sent] == [["Jessica McCloud <jess@example.com>"]]
    row = _rows(db, "church_mail")[0]
    assert row["business_id"] == BIZ and row["outcome"] == "copied" and row["to_address"] == "jessica@lovecityc.com"


def test_a_read_that_fails_is_a_503_so_resend_tries_again(db, resend, monkeypatch):
    import json
    payload = resend.add("m1", to=["jessica@lovecityc.com"])
    monkeypatch.setattr(email_sender, "_verify_resend_signature", lambda raw, headers: True)
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda path, **k: None)
    out = asyncio.run(email_sender.inbound_email(_Req(json.dumps(payload).encode())))
    assert out.status_code == 503 and not resend.sent


def test_platform_mail_is_untouched(db, resend):
    assert _inbound(resend.add("m1", to=["reply+abcd1234+ef567890@mysolutionist.app"])) is None
    assert _inbound(resend.add("m2", to=["someone@nowhere.example"])) is None


def test_a_church_only_named_on_mail_to_someone_here_isnt_ours_to_deliver(db, resend, monkeypatch):
    """Grace Chapel's address Cc'd on mail to kevin@mysolutionist.app: Grace's own mail service delivered it."""
    db.t["businesses"][1]["settings"] = {"email_domain": {"status": "verified", "domain": "gracechapel.org"}}
    out = _inbound(resend.add("m1", to=["kevin@mysolutionist.app", "pastor@gracechapel.org"]))
    assert out is None and not resend.sent and not _rows(db, "church_mail")


def test_a_bcc_or_forwarded_box_is_found_by_the_envelope(db, resend):
    db.t["church_mailboxes"].append(_box("tia", "person", user_id=TIA))
    payload = resend.add("m1", to=["list@other.example"])
    payload["data"]["received_for"] = ["tia@lovecityc.com"]
    out = _inbound(payload)
    assert out["church"] == ["tia@lovecityc.com"] and resend.sent[0]["to"] == ["Tia Brown <tia@example.com>"]


# ─── Who a box reaches, right now ─────────────────────────────────────

def test_a_login_taken_off_the_team_sends_its_mail_to_the_office_box(db, resend):
    db.t["church_mailboxes"] += [_box("jessica", "person", user_id=JESSICA),
                                 _box("office", "office", share_with=[TIA], catch_all=True)]
    _inbound(resend.add("m1", to=["jessica@lovecityc.com"]))
    next(s for s in db.t["business_users"] if s["user_id"] == JESSICA)["status"] = "revoked"
    _inbound(resend.add("m2", to=["jessica@lovecityc.com"]))
    assert [s["to"][0] for s in resend.sent] == ["Jessica McCloud <jess@example.com>", "Tia Brown <tia@example.com>"]
    assert "isn't on the team now" in _rows(db, "church_mail")[1]["why"]


def test_no_catch_all_means_the_pastor(db, resend):
    _inbound(resend.add("m1", to=["typo@lovecityc.com"]))
    assert resend.sent[0]["to"] == ["Kevin McCloud <pastor@example.com>"]


def test_a_role_box_follows_the_role_and_goes_up_the_chain_when_its_empty(db, resend):
    db.t["church_mailboxes"].append(_box("youth", "role", role_key="youth_leader"))
    _inbound(resend.add("m1", to=["youth@lovecityc.com"]))
    db.t["church_leader_roles"] = [r for r in db.t["church_leader_roles"] if r["contact_id"] != ANDRE_C]
    _inbound(resend.add("m2", to=["youth@lovecityc.com"]))
    assert [s["to"][0] for s in resend.sent] == ["Andre Wallace <andre@example.com>",
                                                 "Kevin McCloud <kevin.c@example.com>"]
    assert "nobody holds Youth Leader" in _rows(db, "church_mail")[1]["why"]


def test_a_leader_out_of_every_role_sends_their_mail_to_the_office(db, resend):
    db.t["church_mailboxes"].append(_box("andre", "person", contact_id=ANDRE_C))
    _inbound(resend.add("m1", to=["andre@lovecityc.com"]))
    db.t["church_leader_roles"] = [r for r in db.t["church_leader_roles"] if r["contact_id"] != ANDRE_C]
    _inbound(resend.add("m2", to=["andre@lovecityc.com"]))
    assert [s["to"][0] for s in resend.sent] == ["Andre Wallace <andre@example.com>",
                                                 "Kevin McCloud <pastor@example.com>"]


# ─── prayer@ ──────────────────────────────────────────────────────────

def test_prayer_mail_joins_the_prayer_list_and_is_never_copied(db, resend):
    db.t["church_mailboxes"].append(_box("prayer", "prayer"))
    _inbound(resend.add("m1", to=["prayer@lovecityc.com"], subject="My mother", text="Please pray for her surgery."))
    assert not resend.sent
    req = _rows(db, "ministry_care_requests")[0]
    assert req["prayer_team"] is True and req["needs_pastor"] is False
    assert req["leader_contact_id"] == MINNIE_C, "handed to the Intercessor Leader like any shared request"
    assert req["submission"]["source"] == "Email" and "surgery" in req["submission"]["prayer_request"]
    assert _rows(db, "church_mail")[0]["outcome"] == "prayer"


def test_prayer_mail_about_danger_stays_with_the_pastor(db, resend):
    db.t["church_mailboxes"].append(_box("prayer", "prayer"))
    _inbound(resend.add("m1", to=["prayer@lovecityc.com"], text="He hits me and I am scared."))
    req = _rows(db, "ministry_care_requests")[0]
    assert req["needs_pastor"] is True and req["prayer_team"] is False and not req.get("leader_contact_id")
    assert "pastor only" in _rows(db, "church_mail")[0]["why"] and not resend.sent


# ─── The copy ─────────────────────────────────────────────────────────

def test_the_copy_comes_from_the_box_replies_to_the_sender_and_carries_the_files(db, resend):
    db.t["church_mailboxes"].append(_box("tia", "person", user_id=TIA))
    atts = [{"id": "a1", "filename": "flyer.pdf", "size": 1000, "content_type": "application/pdf",
             "download_url": "https://inbound-cdn.example/a1", "content_disposition": "attachment"},
            {"id": "a2", "filename": "huge.mov", "size": 40 * 1024 * 1024, "content_type": "video/quicktime",
             "download_url": "https://inbound-cdn.example/a2"}]
    _inbound(resend.add("m1", to=["tia@lovecityc.com"], attachments=atts))
    sent = resend.sent[0]
    assert sent["from"] == "Sam Sender via Love City Church <tia@lovecityc.com>"
    assert sent["reply_to"] == ["sam@sender.example"]
    assert sent["headers"] == {church_mail.COPY_HEADER: "tia@lovecityc.com"}, "no platform unsubscribe on their own mail"
    assert sent["attachments"] == [{"filename": "flyer.pdf", "path": "https://inbound-cdn.example/a1",
                                    "content_type": "application/pdf"}]
    assert "1 attachment too large to copy is kept" in sent["text"]
    assert sent["html"].endswith("<p>See you</p>") and "Reply and it goes to Sam" in sent["text"]


@pytest.mark.parametrize("kw,why", [
    ({"auth": ("fail", "fail", "none")}, "couldn't be checked"),
    ({"auth": ("pass", "pass", "fail")}, "didn't send it"),
    ({"headers": {"x-ses-spam-verdict": "FAIL"}}, "spam"),
    ({"headers": {church_mail.COPY_HEADER: "tia@lovecityc.com"}}, "our own copies"),
])
def test_mail_that_fails_its_checks_or_loops_is_kept_never_copied(db, resend, kw, why):
    db.t["church_mailboxes"].append(_box("tia", "person", user_id=TIA))
    _inbound(resend.add("m1", to=["tia@lovecityc.com"], **kw))
    row = _rows(db, "church_mail")[0]
    assert row["outcome"] == "held" and why in row["why"] and not resend.sent


def test_the_same_webhook_twice_writes_once_and_sends_once(db, resend):
    db.t["church_mailboxes"].append(_box("tia", "person", user_id=TIA))
    payload = resend.add("m1", to=["tia@lovecityc.com"])
    _inbound(payload)
    second = _inbound(payload)
    assert second["results"] == [{"address": "tia@lovecityc.com", "outcome": "already"}]
    assert len(_rows(db, "church_mail")) == 1 and len(resend.sent) == 1


def test_a_copy_never_goes_back_to_a_church_address(db, resend):
    db.t["church_mailboxes"].append(_box("fwd", "forward", forward_to="kevin@lovecityc.com"))
    _inbound(resend.add("m1", to=["fwd@lovecityc.com"]))
    row = _rows(db, "church_mail")[0]
    assert row["outcome"] == "failed" and "church's own domain" in row["delivered"][0]["why"] and not resend.sent


# ─── Chief gives them out ─────────────────────────────────────────────

@pytest.fixture
def chief(db, resend, monkeypatch):
    import chief_of_staff
    live = {"on": False}
    monkeypatch.setattr(church_mail, "receiving_live", lambda d: live["on"])
    notes = []

    async def _send(**kw):
        notes.append(kw)
        return {"id": "n1"}
    monkeypatch.setattr(email_sender, "send_via_resend", _send)

    def run(handler, action, as_uid=OWNER):
        tok = chief_of_staff._TURN_USER_ID.set(as_uid)
        try:
            return asyncio.run(handler(None, db.t["businesses"][0], action))
        finally:
            chief_of_staff._TURN_USER_ID.reset(tok)
    return SimpleNamespace(run=run, live=live, notes=notes)


def test_only_the_pastor_or_an_admin_gives_out_an_address(chief, db):
    out = chief.run(chief_church_mail.handle_give_church_email, {"address": "tia", "to": f"login:{TIA}"}, as_uid=MANAGER)
    assert out["failed"] and "pastor or an Admin" in out["result"] and not db.t["church_mailboxes"]
    next(s for s in db.t["business_users"] if s["user_id"] == MANAGER)["role"] = "admin"
    out = chief.run(chief_church_mail.handle_give_church_email, {"address": "tia", "to": f"login:{TIA}"}, as_uid=MANAGER)
    assert not out.get("failed") and out["address"] == "tia@lovecityc.com"


def test_giving_by_name_and_the_note_waits_for_mail_to_reach_the_system(chief, db):
    out = chief.run(chief_church_mail.handle_give_church_email, {"address": "Tia", "to": "Tia Brown"})
    box = db.t["church_mailboxes"][0]
    assert box["kind"] == "person" and box["user_id"] == TIA and box["local"] == "tia"
    assert "Made tia@lovecityc.com: it goes to Tia Brown's own box" in out["result"]
    assert "doesn't reach the system yet" in out["result"] and not chief.notes
    chief.live["on"] = True
    out = chief.run(chief_church_mail.handle_give_church_email, {"address": "tia", "to": "Tia"})
    assert "already goes to" in out["result"] and "got a note" in out["result"]
    assert chief.notes[0]["to_email"] == "tia@example.com" and db.t["church_mailboxes"][0]["told_at"]
    chief.run(chief_church_mail.handle_give_church_email, {"address": "tia", "to": "Tia"})
    assert len(chief.notes) == 1, "the note goes once"


def test_a_role_address_and_the_prayer_list(chief, db):
    out = chief.run(chief_church_mail.handle_give_church_email, {"address": "youth", "to": "role:Youth Leader"})
    assert "follows whoever holds the role" in out["result"] and db.t["church_mailboxes"][0]["role_key"] == "youth_leader"
    out = chief.run(chief_church_mail.handle_give_church_email, {"address": "prayer", "to": "role:intercessor_leader"})
    assert db.t["church_mailboxes"][1]["kind"] == "prayer" and "joins the prayer list" in out["result"]


@pytest.mark.parametrize("action,why", [
    ({"address": "t ia", "to": "Tia"}, "letters, numbers"),
    ({"address": "tia@gmail.com", "to": "Tia"}, "are @lovecityc.com"),
    ({"address": "nora", "to": f"person:{NOBODY_C}"}, "leads nothing"),
    ({"address": "x", "to": "Morgan"}, "no office login or leader"),
    ({"address": "x", "to": "email:pastor@lovecityc.com"}, "loop"),
    ({"address": "x", "to": "Tia", "catch_all": True}, "only the office box"),
])
def test_what_a_give_refuses(chief, db, action, why):
    out = chief.run(chief_church_mail.handle_give_church_email, action)
    assert out["failed"] and why in out["result"] and not db.t["church_mailboxes"]


def test_two_people_with_one_first_name_are_never_guessed(chief, db):
    next(s for s in db.t["business_users"] if s["user_id"] == MANAGER)["name"] = "Tia Moss"
    out = chief.run(chief_church_mail.handle_give_church_email, {"address": "tia", "to": "Tia"})
    assert out["failed"] and "more than one person is called Tia" in out["result"]


def test_pointing_an_address_somewhere_new_says_where_it_went(chief, db):
    chief.run(chief_church_mail.handle_give_church_email, {"address": "info", "to": "Tia"})
    out = chief.run(chief_church_mail.handle_give_church_email,
                    {"address": "info", "to": "office", "share_with": [TIA, JESSICA], "catch_all": True})
    assert "now goes to the office: Tia Brown, Jessica McCloud (it went to Tia Brown's own box)" in out["result"]
    assert db.t["church_mailboxes"][0]["catch_all"] is True


def test_taking_back_an_address_keeps_its_mail(chief, db, resend):
    chief.run(chief_church_mail.handle_give_church_email, {"address": "jessica", "to": "Jessica"})
    chief.run(chief_church_mail.handle_give_church_email,
              {"address": "office", "to": "office", "share_with": [TIA], "catch_all": True})
    church_mail._LIVE_CACHE.clear()
    chief.live["on"] = True
    _inbound(resend.add("m1", to=["jessica@lovecityc.com"]))
    out = chief.run(chief_church_mail.handle_take_back_church_email, {"address": "jessica@lovecityc.com"})
    assert "jessica@lovecityc.com is off. Mail sent to it now goes to the office: Tia Brown" in out["result"]
    assert len(_rows(db, "church_mail")) == 1, "the history stays"
    church_mail._DOMAIN_CACHE.clear()
    _inbound(resend.add("m2", to=["jessica@lovecityc.com"]))
    assert resend.sent[-1]["to"] == ["Tia Brown <tia@example.com>"]


def test_the_directory_suggests_for_the_pastor_and_lists_for_everyone(chief, db):
    chief.run(chief_church_mail.handle_give_church_email, {"address": "tia", "to": "Tia"})
    out = chief.run(chief_church_mail.handle_church_email, {})
    text = out["result"]
    assert "tia@lovecityc.com (own box): Tia Brown's own box" in text
    assert f"jessica@lovecityc.com · to=login:{JESSICA}" in text
    assert f"minnie@lovecityc.com · to=person:{MINNIE_C}" in text, "a leader without a login"
    assert "prayer@lovecityc.com · to=prayer" in text and "office@lovecityc.com · to=office · catch_all:true" in text
    assert not any(s["to"] == f"person:{JESS_C}" for s in out["suggest"]), "a login's own record isn't a second person"
    mine = chief.run(chief_church_mail.handle_church_email, {}, as_uid=TIA)
    assert "tia@lovecityc.com" in mine["result"] and mine["suggest"] == [] and "to=" not in mine["result"]


def test_no_verified_domain_means_no_addresses_yet(chief, db):
    db.t["businesses"][0]["settings"] = {"email_domain": {"status": "pending", "domain": DOMAIN}}
    out = chief.run(chief_church_mail.handle_church_email, {})
    assert "no verified email domain yet" in out["result"]
    out = chief.run(chief_church_mail.handle_give_church_email, {"address": "tia", "to": "Tia"})
    assert out["failed"] and "isn't verified yet" in out["result"]


# ─── Switching the church's mail on ──────────────────────────────────

@pytest.fixture
def switch(chief, db, monkeypatch):
    import email_domain_dns
    import email_domains_router as edr
    db.t["businesses"][0]["settings"] = {**SETTINGS, "email_domain": {**SETTINGS["email_domain"],
                                                                      "resend_domain_id": "dom-1"}}
    calls = []
    record = {"status": "pending"}

    async def _resend(method, path, json_body=None):
        calls.append((method, path, json_body))
        if method == "GET":
            return {"id": "dom-1", "capabilities": {"sending": "enabled", "receiving": "enabled"}, "records": [
                {"record": "SPF", "name": "send", "type": "MX", "value": "feedback-smtp.us-east-1.amazonses.com",
                 "priority": 10, "status": "verified"},
                {"record": "Receiving", "name": "@", "type": "MX", "value": "inbound-smtp.us-east-1.amazonaws.com",
                 "priority": 10, "status": record["status"]}]}
        return {}

    async def _ns(domain):
        return ["dns1.registrar-servers.com", "dns2.registrar-servers.com"]
    monkeypatch.setattr(edr, "_resend", _resend)
    monkeypatch.setattr(email_domain_dns, "lookup_ns", _ns)
    monkeypatch.setattr(church_mail, "apex_mx", lambda d: [(10, "eforward1.registrar-servers.com"),
                                                           (15, "eforward4.registrar-servers.com")])
    monkeypatch.setattr(church_mail, "apex_cname", lambda d: "")
    return SimpleNamespace(calls=calls, record=record)


def test_switching_on_is_the_owners_alone(chief, switch, db):
    next(s for s in db.t["business_users"] if s["user_id"] == MANAGER)["role"] = "admin"
    out = chief.run(chief_church_mail.handle_switch_on_church_mail, {}, as_uid=MANAGER)
    assert out["failed"] and "only the church's owner" in out["result"] and not switch.calls


def test_switching_on_turns_on_receiving_and_names_the_one_record_left(chief, switch):
    out = chief.run(chief_church_mail.handle_switch_on_church_mail, {})
    assert switch.calls[0] == ("PATCH", "/dom-1", {"capabilities": {"receiving": "enabled"}})
    text = out["result"]
    assert out["live"] is False and "One record is left" in text
    assert "Today @lovecityc.com's mail goes to eforward1.registrar-servers.com (priority 10)" in text
    assert "In Namecheap" in text and "value inbound-smtp.us-east-1.amazonaws.com, priority 10" in text
    assert "every address people write to today should have a box here" in text


def test_once_the_record_is_in_it_asks_the_mail_service_to_check_it(chief, switch):
    chief.live["on"] = True
    out = chief.run(chief_church_mail.handle_switch_on_church_mail, {})
    assert ("POST", "/dom-1/verify", None) in switch.calls and out["live"] is True
    assert "now comes to the system" in out["result"] and "asked the mail service to check" in out["result"]
    switch.record["status"] = "verified"
    switch.calls.clear()
    out = chief.run(chief_church_mail.handle_switch_on_church_mail, {})
    assert not any(c[0] == "POST" for c in switch.calls) and "has checked the record" in out["result"]


def test_a_persons_own_out_of_office_reply_isnt_copied_back_to_them(db, resend):
    db.t["church_mailboxes"].append(_box("tia", "person", user_id=TIA))
    _inbound(resend.add("m1", to=["tia@lovecityc.com"], frm="tia@example.com", name="Tia Brown",
                        headers={"Auto-Submitted": "auto-replied"}))
    row = _rows(db, "church_mail")[0]
    assert row["outcome"] == "stored" and row["delivered"][0]["why"] == "their own automatic reply" and not resend.sent
    _inbound(resend.add("m2", to=["tia@lovecityc.com"], frm="vendor@shop.example", name="Shop",
                        headers={"Auto-Submitted": "auto-replied"}))
    assert len(resend.sent) == 1, "someone else's out-of-office still reaches her"



def test_a_website_connected_with_cname_at_the_root_is_told_to_make_it_an_alias(chief, switch, monkeypatch):
    """kmjcreate.com, 11-13: "CNAME @" to the website hid every mail record."""
    monkeypatch.setattr(church_mail, "apex_cname", lambda d: "saas-origin.mysolutionist.app")
    out = chief.run(chief_church_mail.handle_switch_on_church_mail, {})
    assert "First: @lovecityc.com itself is a CNAME (to saas-origin.mysolutionist.app)" in out["result"]
    assert "change the @ row's type from CNAME Record to ALIAS Record" in out["result"]
    assert out["apex_cname"] == "saas-origin.mysolutionist.app"


# ─── Replying as the box ─────────────────────────────────────────────

@pytest.fixture
def relay(db, resend, monkeypatch):
    monkeypatch.setenv("CHURCH_MAIL_SECRET", "test-secret")
    notes = []

    async def _send(**kw):
        notes.append(kw)
        return {"id": "n1"}
    monkeypatch.setattr(email_sender, "send_via_resend", _send)
    db.t["church_mailboxes"].append(_box("tia", "person", user_id=TIA))
    _inbound(resend.add("m1", to=["tia@lovecityc.com"], subject="Thursday"))
    copy = resend.sent[0]
    return SimpleNamespace(addr=copy["reply_to"][0], copy=copy, notes=notes)


def test_a_reply_to_a_copy_goes_to_the_sender_from_the_box(db, resend, relay):
    assert re.fullmatch(r"r[0-9a-f]{32}[a-z2-7]{16}@lovecityc\.com", relay.addr)
    assert "Reply and it goes to Sam from tia@lovecityc.com" in relay.copy["text"]
    _inbound(resend.add("m2", to=[relay.addr], frm="tia@example.com", name="Tia Brown", subject="Re: Thursday",
                        text="See you there!", html=""))
    sent = resend.sent[-1]
    assert sent["from"] == "Tia Brown <tia@lovecityc.com>" and sent["to"] == ["sam@sender.example"]
    assert sent["reply_to"] == ["tia@lovecityc.com"] and sent["subject"] == "Re: Thursday"
    assert sent["headers"] == {"In-Reply-To": "<m1@mail.example>", "References": "<m1@mail.example>"}
    assert sent["text"] == "See you there!" and church_mail.COPY_HEADER not in sent.get("headers", {})
    assert _rows(db, "church_mail")[-1]["why"] == "reply sent as tia@lovecityc.com"


def test_a_relay_address_only_works_for_the_person_it_was_made_for(db, resend, relay):
    _inbound(resend.add("m2", to=[relay.addr], frm="someone@else.example", text="send as the church"))
    assert len(resend.sent) == 1 and "didn't come from the person" in _rows(db, "church_mail")[-1]["why"]
    assert not relay.notes, "a stranger's try tells no one"


def test_a_tampered_relay_address_does_nothing(db, resend, relay):
    bad = relay.addr[:-len("@lovecityc.com") - 1] + ("a" if relay.addr[-len("@lovecityc.com") - 1] != "a" else "b")
    _inbound(resend.add("m2", to=[bad + "@lovecityc.com"], frm="tia@example.com"))
    assert len(resend.sent) == 1 and "matches nothing sent" in _rows(db, "church_mail")[-1]["why"]


def test_a_reply_that_cant_be_proven_is_held_and_the_person_told(db, resend, relay):
    _inbound(resend.add("m2", to=[relay.addr], frm="tia@example.com", auth=("pass", "pass", "none")))
    assert len(resend.sent) == 1 and "couldn't prove it was them" in _rows(db, "church_mail")[-1]["why"]
    assert relay.notes[0]["to_email"] == "tia@example.com" and "sam@sender.example" in relay.notes[0]["body"]


def test_an_out_of_office_answering_a_copy_isnt_sent_on(db, resend, relay):
    _inbound(resend.add("m2", to=[relay.addr], frm="tia@example.com", headers={"Auto-Submitted": "auto-replied"}))
    assert len(resend.sent) == 1 and "automatic reply" in _rows(db, "church_mail")[-1]["why"]
