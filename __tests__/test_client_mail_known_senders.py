"""
test_client_mail_known_senders.py — "did any client email me today?" can be answered yes (2026-09-26).

client_email_today_reply is the records answer to that one question when
the answer check is down or withholds the draft. It re-checked each sender
against known_sender_emails(ctx['contacts_lookup']), and contacts_lookup
has no email field: _gather_context keeps addresses out of it so they never
reach the prompt. The allowlist was always empty, so the answer was always
"I don't see client email dated today" — even with a client's message from
this morning sitting in the context. test_chief_client_email.py never saw it:
its fixture put `email` into contacts_lookup, which production never does.

The allowlist the gate used now rides in ctx as email_known_senders, and
it reaches neither the prompt nor the review evidence.
"""
from __future__ import annotations

import pathlib
import sys
from datetime import datetime, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import chief_of_staff as chief
import chief_truth as truth
import mailbox_policy
from __tests__.test_gather_context_wave2 import gather  # noqa: F401  (fixture)

QUESTION = "Did any client email me today?"
ADA = {"id": "c-ada", "name": "Ada", "email": "Ada@Example.com", "status": "active",
       "health_score": 70}
BO = {"id": "c-bo", "name": "Bo", "email": "bo.private@example.com", "status": "active",
      "health_score": 70}


def _mail(monkeypatch, *, contacts, messages):
    original = chief._sb

    async def rows(client, method, path, body=None):
        if path.startswith("/contacts?"):
            return contacts
        if path.startswith("/mailbox_messages?"):
            return messages
        if path.startswith("/email_replies?"):
            return []
        return await original(client, method, path, body)
    monkeypatch.setattr(chief, "_sb", rows)


def _from_ada_now():
    return [{"id": "m-1", "from_email": "ada@example.com", "from_name": "Ada",
             "subject": "Tomorrow", "body_text": "See you at 10.",
             "received_at": datetime.now(timezone.utc).isoformat(), "read": False}]


def test_a_client_who_emailed_today_is_a_yes(gather, monkeypatch):
    _mail(monkeypatch, contacts=[dict(ADA), dict(BO)], messages=_from_ada_now())
    _, ctx = gather(query_text=None)
    # The context is shaped as in production: no addresses in the lookup.
    assert all("email" not in c for c in ctx["contacts_lookup"])
    assert ctx["email_replies"] and ctx["email_known_senders"] == [
        "ada@example.com", "bo.private@example.com"]
    assert mailbox_policy.client_email_today_reply(QUESTION, ctx).startswith(
        "Yes. I found client email dated today")


def test_the_allowlist_reaches_neither_the_prompt_nor_the_review(gather, monkeypatch):
    _mail(monkeypatch, contacts=[dict(ADA), dict(BO)], messages=_from_ada_now())
    _, ctx = gather(query_text=None)
    # Bo never wrote: his address is only in the allowlist.
    assert "bo.private@example.com" not in chief._format_context_for_prompt(ctx)
    sources = truth.evidence_for_review(ctx, "", [])
    assert not any("bo.private@example.com" in s["text"] for s in sources.values())


def test_a_stranger_today_is_still_not_a_client(gather, monkeypatch):
    stranger = [{**_from_ada_now()[0], "from_email": "stranger@example.com", "from_name": "S"}]
    _mail(monkeypatch, contacts=[dict(ADA)], messages=stranger)
    _, ctx = gather(query_text=None)
    assert mailbox_policy.client_email_today_reply(QUESTION, ctx).startswith(
        "I don't see client email dated today")


def test_a_failed_contacts_read_is_not_a_no(gather, monkeypatch):
    _mail(monkeypatch, contacts=None, messages=_from_ada_now())
    _, ctx = gather(query_text=None)
    assert ctx["email_context_quality"]["contact_filter"] == "unavailable"
    reply = mailbox_policy.client_email_today_reply(QUESTION, ctx)
    assert "couldn't retrieve all the email sources" in reply and "don't see" not in reply
