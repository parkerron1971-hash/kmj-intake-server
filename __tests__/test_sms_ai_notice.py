"""The person being texted finds out they are texting an AI.

THE ASYMMETRY THIS CLOSES. The practitioner gets an interrupting modal
explaining how AI works here, and has to click through it. Their
customer — who never signed up for anything, and may be replying to a
salon at 9pm — was being texted by that same AI with no notice at all.
The client-facing disclosure existed, versioned and hashed, since BE
#490. Nothing ever sent it.

TWO DECISIONS WORTH THE WORDS.

Gated on AUTHORSHIP, not on the caller. A practitioner typing a message
by hand and pressing send is not an AI talking, and stapling "replies
here are AI-generated" onto their text would be its own kind of lie.
authorship.current_model() is set inside a Chief turn and unset
otherwise, so the notice follows who wrote the words.

Fails OPEN, unlike the opt-out tail beside it. If the "have we already
told them" read fails, the notice IS included. A duplicated opt-out
line is noise; a missing AI disclosure is the whole harm.
"""
from __future__ import annotations

import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

import ai_disclosure
import sms_service


# ── GSM-7: the alphabet an SMS can hold 160 of ────────────────────────
GSM7 = set(
    "@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞÆæßÉ !\"#¤%&'()*+,-./0123456789:;<=>?"
    "¡ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§¿abcdefghijklmnopqrstuvwxyzäöñüà"
) | set("^{}\\[~]|€")


class TestTheNoticeFitsInAText:
    def test_every_character_is_GSM7(self):
        """THE EXPENSIVE ONE. A single character outside GSM-7 — an em
        dash, a curly apostrophe, an ellipsis — forces the whole message
        into UCS-2, where a segment holds 70 characters instead of 160.

        The first draft of this line used an em dash. It would have more
        than doubled the segment count, and the cost, of every message
        the notice rides on — and nothing would have failed, the bills
        would just have been bigger.
        """
        text = ai_disclosure.current("client_sms")["text"]
        bad = sorted({c for c in text if c not in GSM7})
        assert not bad, f"non-GSM-7 characters force UCS-2 encoding: {bad!r}"

    def test_the_opt_out_tail_is_also_GSM7(self):
        """It rides on the same message; one bad character anywhere
        costs the same."""
        bad = sorted({c for c in sms_service.OPTOUT_TAIL if c not in GSM7})
        assert not bad, f"opt-out tail forces UCS-2: {bad!r}"

    def test_it_leaves_room_for_an_actual_message(self):
        """Notice plus opt-out plus a business name prefix all land on
        the same first text. If the overhead alone approached a segment
        there would be nothing left to say."""
        notice = ai_disclosure.current("client_sms")["text"]
        overhead = len(notice) + len(sms_service.OPTOUT_TAIL) + 1
        assert overhead < 110, f"overhead {overhead} leaves too little of 160"

    def test_it_says_the_two_things_that_matter(self):
        """That it is not a person, and that a person is available.
        Everything else was cut to fit; these are why it exists."""
        low = ai_disclosure.current("client_sms")["text"].lower()
        assert "ai" in low
        assert "human" in low or "person" in low


class TestItIsAProperVersionedDocument:
    def test_it_is_hashed_like_the_others(self):
        doc = ai_disclosure.current("client_sms")
        assert doc["hash"] == ai_disclosure.text_hash(doc["text"])

    def test_it_is_its_own_audience_not_a_slice_of_the_web_one(self):
        """A record of what somebody was told has to hash the words they
        actually saw. Deriving the SMS line from CLIENT_V1 at send time
        would mean the stored hash described text nobody read."""
        assert "client_sms" in ai_disclosure.audiences()
        assert (ai_disclosure.current("client_sms")["text"]
                != ai_disclosure.current("client")["text"])

    def test_the_sms_module_does_not_keep_a_second_copy(self):
        """Two copies of a disclosure drift, and then the record of what
        somebody was told stops matching what they were told."""
        src = pathlib.Path(sms_service.__file__).read_text(encoding="utf-8")
        assert ai_disclosure.CLIENT_SMS_V1 not in src
        assert sms_service._ai_notice_text() == ai_disclosure.CLIENT_SMS_V1


class TestComposition:
    NAME = "Craft & Co"

    def test_the_notice_is_added_when_asked(self):
        out = sms_service.compose_outbound_body(
            self.NAME, "You're booked for 2pm.", include_ai_notice=True)
        assert "AI-generated" in out

    def test_and_absent_when_not(self):
        out = sms_service.compose_outbound_body(
            self.NAME, "You're booked for 2pm.")
        assert "AI-generated" not in out

    def test_the_opt_out_stays_last(self):
        """People look for STOP at the end of the message. The notice
        goes ahead of it rather than after."""
        out = sms_service.compose_outbound_body(
            self.NAME, "You're booked for 2pm.",
            include_optout=True, include_ai_notice=True)
        assert out.index("AI-generated") < out.index("STOP")
        assert out.rstrip().endswith("opt out.")

    def test_it_does_not_repeat_what_chief_already_said(self):
        """Chief writes its own words and sometimes discloses unprompted.
        Appending a canned second copy reads as a machine not listening
        to itself."""
        out = sms_service.compose_outbound_body(
            self.NAME, "Quick note: this reply is AI-generated. You're booked.",
            include_ai_notice=True)
        assert out.lower().count("ai-generated") == 1

    def test_it_works_with_no_business_name(self):
        """The nameless branch is a separate return path and had to be
        taught the same thing — the earlier version appended only the
        opt-out there."""
        out = sms_service.compose_outbound_body(
            "", "You're booked for 2pm.",
            include_optout=True, include_ai_notice=True)
        assert "AI-generated" in out and "STOP" in out

    def test_an_empty_message_stays_empty(self):
        assert sms_service.compose_outbound_body(
            self.NAME, "  ", include_ai_notice=True) == ""

    def test_the_business_name_still_leads(self):
        """Everything above must not have disturbed what this function
        was already for."""
        out = sms_service.compose_outbound_body(
            self.NAME, "You're booked.", include_ai_notice=True)
        assert out.startswith("Craft & Co: ")


class TestWhoGetsToldAndWhen:
    """The history check, exercised rather than read."""

    class _Client:
        def __init__(self, rows=None, boom=False):
            self.rows, self.boom, self.asked = rows or [], boom, []

    @staticmethod
    def _patch(monkeypatch, rows=None, boom=False):
        async def _get(client, path):
            client.asked.append(path)
            if boom:
                raise RuntimeError("supabase unreachable")
            return rows or []
        monkeypatch.setattr(sms_service, "_sb_get", _get)

    def test_a_number_already_told_is_not_told_again(self, monkeypatch):
        self._patch(monkeypatch, rows=[{"id": "x"}])
        c = self._Client()
        assert asyncio.run(
            sms_service._ai_notice_already_sent(c, "b1", "+15551234567")) is True

    def test_a_number_never_told_gets_the_notice(self, monkeypatch):
        self._patch(monkeypatch, rows=[])
        c = self._Client()
        assert asyncio.run(
            sms_service._ai_notice_already_sent(c, "b1", "+15551234567")) is False

    def test_a_READ_FAILURE_discloses_rather_than_stays_quiet(self, monkeypatch):
        """The opposite of _is_first_outbound beside it, on purpose: a
        duplicated opt-out is noise, a missing disclosure is the harm."""
        self._patch(monkeypatch, boom=True)
        c = self._Client()
        assert asyncio.run(
            sms_service._ai_notice_already_sent(c, "b1", "+15551234567")) is False

    def test_the_opt_out_check_still_fails_the_OTHER_way(self, monkeypatch):
        """Guarding the contrast, so nobody later 'makes them
        consistent' and silently changes both behaviours."""
        self._patch(monkeypatch, boom=True)
        c = self._Client()
        assert asyncio.run(
            sms_service._is_first_outbound(c, "b1", "+15551234567")) is False

    def test_it_asks_only_about_OUTBOUND_messages(self, monkeypatch):
        """An inbound text from the customer saying the words would
        otherwise count as us having disclosed."""
        self._patch(monkeypatch, rows=[])
        c = self._Client()
        asyncio.run(sms_service._ai_notice_already_sent(c, "b1", "+15551234567"))
        assert "direction=eq.outbound" in c.asked[0]
        assert "business_id=eq.b1" in c.asked[0]


class TestTheGateIsAuthorshipNotTheCaller:
    SRC = pathlib.Path(sms_service.__file__).read_text(encoding="utf-8")

    def test_the_send_path_consults_authorship(self):
        assert "authorship.current_model()" in self.SRC

    def test_a_human_typed_message_gets_no_notice(self):
        """include_ai is only computed when a model authored the turn —
        so the practitioner's own words are never labelled as an AI's."""
        i = self.SRC.index("include_ai = False")
        window = self.SRC[i:i + 260]
        assert "if ai_model:" in window

    def test_authorship_failing_never_blocks_a_send(self):
        """A text that does not go out is a worse outcome than one
        without a notice."""
        i = self.SRC.index("import authorship")
        assert "except Exception" in self.SRC[i:i + 300]
