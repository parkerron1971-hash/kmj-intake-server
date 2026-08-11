"""The Hub's label and the prompt gate must give the same answer.

The bug this locks down: the Email Hub labelled every message "Chief can
read" / "Not shown to Chief" from the contact_id stored at ingest, while
the gate matches the sender's address against the CURRENT contact list on
every turn.

Those agree until someone emails you and then becomes a contact. From
that moment the gate lets their earlier mail through and the label still
says it is hidden — a label whose whole job is explaining the rule,
contradicting it.

A stored proxy for a live rule is a bug with a delay on it. These tests
assert the two answers agree, including in that drift window.

Run via:
  python -m __tests__.test_mailbox_label_matches_the_gate
"""
from __future__ import annotations

import unittest

import chief_of_staff as cos
import mailbox_policy


def _mailbox_row(**kw):
    row = {
        "id": kw.pop("id", "m1"),
        "from_email": kw.pop("from_email", "someone@example.com"),
        "from_name": kw.pop("from_name", "Someone"),
        "subject": kw.pop("subject", "hi"),
        "body_text": kw.pop("body_text", "body"),
        "received_at": kw.pop("received_at", "2026-08-11T10:00:00Z"),
        "read": kw.pop("read", False),
        "contact_id": kw.pop("contact_id", None),
    }
    row.update(kw)
    return row


def _label(row, contacts):
    """What the endpoint computes for the Hub."""
    known = mailbox_policy.known_sender_emails(contacts)
    return mailbox_policy.is_prompt_eligible(
        {**row, "metadata": {"source": "mailbox"}}, known)


def _gate_sees(row, contacts):
    """What the prompt gate actually admits."""
    merged = cos._merge_inbound_mail([], [row])
    out = cos._split_email_replies_for_prompt(merged, contacts)
    return any(r.get("id") == row["id"] for r in out["email_replies"])


class TestLabelMatchesGate(unittest.TestCase):
    def test_the_drift_case_stored_contact_id_is_stale(self):
        """THE REGRESSION. Mail ingested before the sender was a contact
        keeps contact_id = NULL forever. Once they become a contact the
        gate admits it, so the label must too — the old code read the
        stale column and said the opposite."""
        row = _mailbox_row(from_email="marcus@client.com", contact_id=None)
        contacts = [{"id": "c1", "email": "marcus@client.com"}]

        self.assertTrue(_gate_sees(row, contacts),
                        "gate should admit mail from a current contact")
        self.assertTrue(_label(row, contacts),
                        "label must agree with the gate, not with contact_id")

    def test_stranger_is_hidden_by_both(self):
        row = _mailbox_row(from_email="nobody@spam.com")
        contacts = [{"id": "c1", "email": "marcus@client.com"}]
        self.assertFalse(_gate_sees(row, contacts))
        self.assertFalse(_label(row, contacts))

    def test_stale_contact_id_does_not_grant_access(self):
        """The mirror image: a stored contact_id from a contact who has
        since been deleted must not keep letting mail through."""
        row = _mailbox_row(from_email="gone@former.com", contact_id="c-deleted")
        self.assertFalse(_gate_sees(row, []))
        self.assertFalse(_label(row, []))

    def test_case_and_whitespace_agree_on_both_sides(self):
        row = _mailbox_row(from_email="  MARCUS@Client.COM ")
        contacts = [{"id": "c1", "email": "marcus@client.com"}]
        self.assertTrue(_gate_sees(row, contacts))
        self.assertTrue(_label(row, contacts))

    def test_no_contacts_closes_the_gate_for_both(self):
        row = _mailbox_row(from_email="anyone@anywhere.com")
        self.assertFalse(_gate_sees(row, []))
        self.assertFalse(_label(row, []))

    def test_agreement_holds_across_a_mixed_batch(self):
        contacts = [{"id": "c1", "email": "a@known.com"},
                    {"id": "c2", "email": "b@known.com"}]
        rows = [
            _mailbox_row(id="m1", from_email="a@known.com", contact_id=None),
            _mailbox_row(id="m2", from_email="spam@bulk.com", contact_id=None),
            _mailbox_row(id="m3", from_email="B@Known.com", contact_id="c2"),
            _mailbox_row(id="m4", from_email="", contact_id=None),
        ]
        for row in rows:
            self.assertEqual(
                _label(row, contacts), _gate_sees(row, contacts),
                f"label and gate disagree for {row['id']}")


class TestOneDefinition(unittest.TestCase):
    def test_chief_delegates_rather_than_reimplementing(self):
        """If someone re-inlines the rule in chief_of_staff, these stop
        being the same object and the drift can come back silently."""
        self.assertIs(cos._reply_source, mailbox_policy.reply_source)
        self.assertIs(cos._known_sender_emails, mailbox_policy.known_sender_emails)
        self.assertIs(cos._split_email_replies_for_prompt,
                      mailbox_policy.split_for_prompt)


if __name__ == "__main__":
    unittest.main(verbosity=2)
