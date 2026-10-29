# __tests__/test_group_care.py
#
# Chief's note to each person who's been missing, sent by the leader
# (group_care; the approved canvas "Church Groups, Together", board Lead).
# Pins:
#   1. Chief writes one note per person from first names; when it can't, a
#      plain note to start from, said so
#   2. only a group's leader, only with messaging on, only when someone has
#      missed the last three gatherings, a few times an hour
#   3. Send opens the leader's own chat with the note written in; a teen gets
#      no Send (an adult can't message a teen privately)
#   4. the My group page offers it only with messaging on

import pathlib
import sys

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import group_care as gc
import member_portal_lead as mpl
from test_group_lead import _meeting, _page, lead  # noqa: F401
from test_group_gatherings import meet  # noqa: F401
from test_member_portal_group_space import BIZ, BUSINESS, G, MONIQUE, TASHA, TEEN, _me, fake  # noqa: F401
import test_member_messaging as tmm
from test_member_messaging import env  # noqa: F401

REAL_DRAFT = gc.draft


@pytest.fixture
def care(lead, monkeypatch):
    import member_portal_messaging as mpm
    import rate_limit
    monkeypatch.setattr(mpm, "turned_on", lambda biz: True)
    monkeypatch.setattr(rate_limit, "allow_strict", lambda b, k, **kw: True)
    for i, day in enumerate(["2026-10-15", "2026-10-08", "2026-10-01"]):
        _meeting(lead, f"mmmmmmmm-0000-0000-0000-00000000000{i}", day, [TASHA])      # Monique and Kayla missed all three
    lead.drafts = []

    def draft(business_id, group, leader_first, next_text, people):
        lead.drafts.append((group, leader_first, next_text, [p["first"] for p in people]))
        return {p["id"]: f"Hi {p['first']}, we miss you!" for p in people}, True
    monkeypatch.setattr(gc, "draft", draft)
    return lead


def _client(monkeypatch, who):
    import member_portal_church as mpc

    async def signed_in(request):
        return {"business": BUSINESS, "site": None}, _me(who, "Tasha Williams" if who == TASHA else "Monique Brown"), False
    monkeypatch.setattr(mpc, "_signed_in", signed_in)
    app = FastAPI()
    app.include_router(mpl.router)
    return TestClient(app, follow_redirects=False)


# ── 1. the drafts ────────────────────────────────────────────────────

def test_a_plain_note_when_chief_cant(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    notes, by_chief = gc.draft(BIZ, "Sisters in the City", "Tasha", "on Thursday, October 22",
                               [{"id": "a", "first": "Monique"}])
    assert not by_chief and notes["a"].startswith("Hi Monique, we’ve missed you at Sisters in the City.")
    assert "Thursday, October 22" in notes["a"]


class _Resp:
    def __init__(self, text, stop="end_turn", status=200):
        self.status_code, self._body = status, {"content": [{"type": "text", "text": text}], "stop_reason": stop}

    def json(self):
        return self._body


@pytest.fixture
def model(monkeypatch):
    import llm_call
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    m = type("M", (), {"calls": [], "reply": _Resp("{}")})()

    def post_with(client, payload, **kw):
        m.calls.append((payload, kw))
        return m.reply
    monkeypatch.setattr(llm_call, "post_with", post_with)
    return m


def test_chief_writes_from_first_names_and_is_never_billed(model):
    model.reply = _Resp('{"a": "Hi Monique, we miss you. How are you doing?"}')
    notes, by_chief = gc.draft(BIZ, "Sisters in the City", "Tasha", "", [{"id": "a", "first": "Monique"}])
    assert by_chief and notes == {"a": "Hi Monique, we miss you. How are you doing?"}
    payload, kw = model.calls[0]
    assert kw["units"] == 0 and kw["business_id"] == BIZ and payload["model"] == gc.MODEL
    assert '"first_name": "Monique"' in payload["messages"][0]["content"]


@pytest.mark.parametrize("reply", [_Resp("I can't help with that"), _Resp('{"a": "x"}', stop="refusal"), _Resp("", status=529)])
def test_when_chief_cant_a_plain_note(model, reply):
    model.reply = reply
    notes, by_chief = gc.draft(BIZ, "Sisters in the City", "Tasha", "", [{"id": "a", "first": "Monique"}])
    assert not by_chief and notes["a"].startswith("Hi Monique, we’ve missed you")


def test_no_key_no_call(model, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    gc.draft(BIZ, "Sisters in the City", "Tasha", "", [{"id": "a", "first": "Monique"}])
    assert model.calls == []


def test_chiefs_answer_or_nothing():
    assert gc.parse('Sure: {"a": "Hi Monique!", "b": "Hi Kayla!"}', ["a", "b"]) == {"a": "Hi Monique!", "b": "Hi Kayla!"}
    assert gc.parse('{"a": "Hi Monique!"}', ["a", "b"]) is None            # one missing: not a full set
    assert gc.parse("I can't", ["a"]) is None


# ── 2. who gets them ─────────────────────────────────────────────────

def test_a_leader_gets_a_note_for_each(care, monkeypatch):
    r = _client(monkeypatch, TASHA).post("/my/lead/groups/notes", data={"group_id": G})
    assert r.status_code == 200
    assert care.drafts == [("Sisters in the City", "Tasha", "on Thursday, October 22 · 7:00 PM", ["Monique"])]
    assert "Hi Monique, we miss you!" in r.text and "Chief drafted these from you." in r.text
    assert f'href="/my/messages/to/{MONIQUE}?say=Hi%20Monique%2C%20we%20miss%20you%21"' in r.text


def test_a_teen_gets_no_private_note(care, monkeypatch):
    r = _client(monkeypatch, TASHA).post("/my/lead/groups/notes", data={"group_id": G})
    assert "is a teen, so private messages" in r.text and f"/my/messages/to/{TEEN}" not in r.text
    assert all("Kayla" not in names for *_, names in care.drafts)            # a teen's name never goes to the model


def test_the_page_says_when_its_a_plain_note(care, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(gc, "draft", REAL_DRAFT)
    r = _client(monkeypatch, TASHA).post("/my/lead/groups/notes", data={"group_id": G})
    assert "Here’s a note to start from." in r.text and "Chief drafted" not in r.text
    assert "Hi Monique, we’ve missed you at Sisters in the City." in r.text


def test_only_the_group_they_lead(care, monkeypatch):
    other = "99999999-0000-0000-0000-000000000001"
    r = _client(monkeypatch, TASHA).post("/my/lead/groups/notes", data={"group_id": other})
    assert r.headers["location"] == "/my/lead" and care.drafts == []


def test_not_a_leader(care, monkeypatch):
    r = _client(monkeypatch, MONIQUE).post("/my/lead/groups/notes", data={"group_id": G})
    assert r.headers["location"] == "/my/lead" and care.drafts == []


def test_only_with_messaging_on(care, monkeypatch):
    import member_portal_messaging as mpm
    monkeypatch.setattr(mpm, "turned_on", lambda biz: False)
    r = _client(monkeypatch, TASHA).post("/my/lead/groups/notes", data={"group_id": G})
    assert r.headers["location"] == f"/my/lead/groups/{G}?err=notes_off" and care.drafts == []


def test_only_when_someone_has_missed(care, monkeypatch):
    care.t["group_meeting_attendance"] = [dict(a, contact_id=c) for a in care.t["group_meeting_attendance"]
                                          for c in (TASHA, MONIQUE, TEEN)]
    r = _client(monkeypatch, TASHA).post("/my/lead/groups/notes", data={"group_id": G})
    assert r.headers["location"] == f"/my/lead/groups/{G}?err=notes_none"


def test_only_teens_missing_no_drafts(care, monkeypatch):
    for a in care.t["group_meeting_attendance"]:
        a["contact_id"] = MONIQUE                    # Monique came; only Kayla, a teen, missed
    care.t["group_meeting_attendance"] += [dict(a, contact_id=TASHA) for a in care.t["group_meeting_attendance"]]
    html, _ = _page(TASHA)
    assert "Haven’t been in a while" in html and 'action="/my/lead/groups/notes"' not in html
    r = _client(monkeypatch, TASHA).post("/my/lead/groups/notes", data={"group_id": G})
    assert r.headers["location"] == f"/my/lead/groups/{G}?err=notes_none" and care.drafts == []


def test_a_few_an_hour(care, monkeypatch):
    import rate_limit
    monkeypatch.setattr(rate_limit, "allow_strict", lambda b, k, **kw: b != "care_notes")
    r = _client(monkeypatch, TASHA).post("/my/lead/groups/notes", data={"group_id": G})
    assert r.headers["location"] == f"/my/lead/groups/{G}?err=slow" and care.drafts == []


# ── 3. the chat opens with the note written in ───────────────────────

def test_the_chat_opens_with_the_note(env):
    c = tmm._member(env, tmm.ANA)
    r = c.get(f"/my/messages/to/{tmm.BEN}?say=Hi%20Ben%2C%20we%20miss%20you%21", follow_redirects=False)
    assert r.headers["location"].endswith("?say=Hi%20Ben%2C%20we%20miss%20you%21")
    page = c.get(r.headers["location"]).text
    assert 'value="Hi Ben, we miss you!"' in page
    assert 'value=""' in c.get(tmm._start(env, tmm.ANA, tmm.BEN)).text        # no note: an empty box


def test_a_note_is_escaped_into_the_box(env):
    c = tmm._member(env, tmm.ANA)
    loc = c.get(f"/my/messages/to/{tmm.BEN}?say=%22%3E%3Cb%3Ehi", follow_redirects=False).headers["location"]
    page = c.get(loc).text
    assert 'value="&quot;&gt;&lt;b&gt;hi"' in page and '"><b>hi' not in page


# ── 4. the My group page ─────────────────────────────────────────────

def test_offered_on_my_group_only_with_messaging_on(care, monkeypatch):
    html, _ = _page(TASHA)
    assert 'action="/my/lead/groups/notes"' in html and "Draft a note to them" in html          # one adult to write to
    assert f'/my/messages/to/{MONIQUE}"' in html and f"/my/messages/to/{TEEN}" not in html      # no dead-end Message for a teen
    import member_portal_messaging as mpm
    monkeypatch.setattr(mpm, "turned_on", lambda biz: False)
    html, _ = _page(TASHA)
    assert 'action="/my/lead/groups/notes"' not in html


def test_words():
    import member_portal_church as mpc
    assert {"notes_off", "notes_none"} <= set(mpc.ERRORS)
