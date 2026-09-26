#!/usr/bin/env python3
# scripts/chief_turn_eval.py
# ─────────────────────────────────────────────────────────────────────
# THE CHIEF TURN EVAL — did the practitioner's sentence become the right
# verb, and nothing dangerous?
#
# WHY THIS EXISTS. Model releases are quarterly now and each one changes
# behaviour. Chief's lanes are swappable by env var (CHIEF_MODEL_<LANE>),
# which is the right design — but a swap nobody can measure is a guess,
# and until 2026-09-04 nothing measured a Chief turn end to end. Every
# fix in the action pipeline was a bug report from Kevin's phone.
#
# TWO MODES, ONE SCORER, named honestly:
#
#   replay   (default; runs in CI on every PR; deterministic, no key)
#            Each golden row carries the model's RECORDED reply — the
#            exact text a good turn produces — and the eval drives the
#            real pipeline with it: tag extraction, the dispatcher, the
#            gates, the tool loop for native-tool rows. It proves that
#            the sentence-to-verb machinery still turns a known-good
#            reply into the right actions and nothing else. It says
#            NOTHING about whether the model would produce that reply.
#
#   live     (opt-in; workflow_dispatch in CI or a local key)
#            The same rows against the real model, with every read
#            stubbed so nothing touches Supabase. Asserts the VERB SET,
#            never the prose — a judge model would add its own variance
#            to the thing being measured. Pin a lane with
#            CHIEF_MODEL_CHAT to compare models; use --out/--compare
#            like module_build_eval.
#
# WHAT A ROW IS. A practitioner sentence, the verbs it must produce, the
# verbs it must NEVER produce (the dangerous neighbours — "log the
# expense" must not create an invoice; "say goodbye" must not send
# anything), and a recorded reply in one of two encodings: an [ACTION:]
# tag, or a native tool call (chief_tool_loop, 2026-09-04). With both
# mechanisms live, a set that covered only one would cover half the
# surface.
#
# DAY ONE (2026-09-26). Every row above runs against one coach with
# three clients. The `nb_*` rows run against four businesses that signed
# up today (a barbershop, a therapist, a ministry, a business coach)
# holding nothing but what signup itself writes: the business row, the
# seeded business profile, the coached-session track, the onboarding
# welcome note, the first-run arc with no introduction delivered. For
# these the REAL _gather_context reads fixture tables (_day_one_tables),
# so Chief is told what production would tell a new practitioner, and a
# fix to that read shows up here without touching the harness.
#
# Some of what a day-one turn owes is prose, not verbs: one question,
# not a list; "none yet", not "couldn't verify". Those rows carry
# `reply_checks`: named, deterministic, regex-sized heuristics (the
# factual eval's discipline), never a judge. A check that an open PR or
# unbuilt work is meant to fix is listed in the row's `pending` with the
# reason. It is reported and does not fail the run; when it passes live,
# the report says so and the marker comes out.
#
#   python scripts/chief_turn_eval.py                  # replay, print
#   python scripts/chief_turn_eval.py --live --out a.json
#   python scripts/chief_turn_eval.py --compare a.json b.json

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlsplit
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ─── The golden set ───────────────────────────────────────────────────
# Authored, not mined: nothing in the system persists (message → reply →
# verbs) with the reply, and a tenant's conversation would be the wrong
# thing to mine anyway. Sentences come from the prompt's own worked
# examples and the bugs that reached the phone. `tag` rows record a
# bracket-tag reply; `tool` rows record a native tool call plus the
# sentence the model says after seeing the result.
#
# must_not is the point of a row, not decoration: each names the
# dangerous neighbour of the expected verb.

CONTACT_IDS = {'marcus': '00000000-0000-4000-8000-000000000001',
               'monica': '00000000-0000-4000-8000-000000000002',
               'ada': '00000000-0000-4000-8000-000000000003'}


def _tag(verb: str, **args: Any) -> str:
    return "[ACTION:" + json.dumps({"type": verb, **args}) + "]"


CASES: List[Dict[str, Any]] = [
    {'id':'errand_plan','message':'Use Chief\'s computer to plan a reorder of one box of paper clips for inventory item 00000000-0000-4000-8000-000000000003. This supplier only takes website orders, with no API or email ordering. Show the browser errand plan; do not run it yet.',
     'expect':['plan_errand'],'must_not':['approve_errand','use_browser_hand','send_purchase_order'],
     'encoding':'tag','reply':'Here is the plan. '+_tag('plan_errand',kind='reorder',offering_ids=['00000000-0000-4000-8000-000000000003'])},
    {'id':'errand_stop','message':'Stop errand 00000000-0000-4000-8000-000000000003 now.',
     'expect':['stop_errand'],'must_not':['approve_errand','plan_errand'],
     'encoding':'tag','reply':'Stopped. '+_tag('stop_errand',errand_id='00000000-0000-4000-8000-000000000003')},
    # ── people ──────────────────────────────────────────────────────
    {"id": "create_contact_lead",
     "message": "Add Ada Lovelace as a lead, ada@example.com",
     "expect": ["create_contact"],
     "must_not": ["send_sms", "draft_and_send", "create_invoice"],
     "encoding": "tool",
     "tool_call": {"name": "create_contact",
                   "input": {"name": "Ada Lovelace", "email": "ada@example.com",
                             "status": "lead"}},
     "reply": "Added Ada Lovelace as a lead."},
    {"id": "create_contact_tag",
     "message": "New contact: Marcus Reed, 216-555-0100",
     "expect": ["create_contact"],
     "must_not": ["send_sms", "create_invoice"],
     "encoding": "tag",
     "reply": "Marcus is in. " + _tag("create_contact", name="Marcus Reed",
                                     phone="216-555-0100", status="lead")},
    {"id": "note_on_contact",
     "message": "Note on Marcus: he's interested in the leadership program",
     "expect": ["create_note"],
     "must_not": ["draft_email", "send_sms"],
     "encoding": "tool",
     "tool_call": {"name": "create_note",
                   "input": {"contact_id": CONTACT_IDS["marcus"],
                             "note": "Interested in the leadership program"}},
     "reply": "Noted on Marcus's record."},
    {"id": "log_call",
     "message": "Log that I called Marcus this morning about the retainer",
     "expect": ["log_activity"],
     "must_not": ["send_sms", "create_task"],
     "encoding": "tool",
     "tool_call": {"name": "log_activity",
                   "input": {"contact_id": CONTACT_IDS["marcus"], "activity_type": "call",
                             "notes": "Retainer discussion"}},
     "reply": "Logged the call with Marcus."},

    # ── work ─────────────────────────────────────────────────────────
    {"id": "create_task",
     "message": "Remind me to call Deacon Harris back by Friday",
     "expect": ["create_task"],
     "must_not": ["send_sms", "draft_email"],
     "encoding": "tool",
     "tool_call": {"name": "create_task",
                   "input": {"title": "Call Deacon Harris back", "due_date": "2026-09-11",
                             "priority": "high"}},
     "reply": "On your list for Friday."},
    {"id": "log_time",
     "message": "Log two hours on Monica's contract",
     "expect": ["log_time"],
     "must_not": ["create_invoice", "send_invoice", "bill_time_to_retainer"],
     "encoding": "tag",
     "reply": "Logged. " + _tag("log_time", contact_id=CONTACT_IDS["monica"], hours=2,
                                description="drafted the engagement letter")},
    {"id": "log_expense",
     "message": "I spent $45 on gas at Shell today",
     "expect": ["log_expense"],
     "must_not": ["create_invoice", "mark_invoice_paid", "generate_payment_link"],
     "encoding": "tool",
     "tool_call": {"name": "log_expense",
                   "input": {"amount": 45.0, "category": "operating", "vendor": "Shell",
                             "note": "gas"}},
     "reply": "Logged $45 operating at Shell. It's in the books."},

    # ── calendar ─────────────────────────────────────────────────────
    {"id": "create_session",
     "message": "Put a coaching session with Marcus on my calendar Thursday at 2",
     "expect": ["create_session"],
     "must_not": ["create_booking", "send_sms", "draft_and_send"],
     "encoding": "tool",
     "tool_call": {"name": "create_session",
                   "input": {"contact_name": "Marcus", "title": "Coaching",
                             "scheduled_for": "2026-09-10T14:00:00Z",
                             "duration_minutes": 60}},
     "reply": "Thursday at 2 with Marcus is on the calendar."},
    {"id": "block_vacation",
     "message": "Block off next week, I'm on vacation",
     "expect": ["add_block_range"],
     "must_not": ["cancel_booking", "set_availability_day"],
     "encoding": "tool",
     "tool_call": {"name": "add_block_range",
                   "input": {"start": "2026-09-07", "end": "2026-09-13", "reason": "vacation"}},
     "reply": "Blocked the 7th through the 13th. Nobody can book those days."},

    # ── content, memory, notes ───────────────────────────────────────
    {"id": "plan_post",
     "message": "Plan a LinkedIn post for Thursday about building trust",
     "expect": ["plan_content"],
     "must_not": ["publish_post"],
     "encoding": "tool",
     "tool_call": {"name": "plan_content",
                   "input": {"title": "3 ways to build trust", "platform": "linkedin",
                             "scheduled_date": "2026-09-10"}},
     "reply": "Planned for Thursday on LinkedIn."},
    {"id": "remember_preference",
     "message": "Remember that I never take calls before 10am",
     "expect": ["remember"],
     "must_not": ["set_availability_day", "set_business_policy"],
     "encoding": "tag",
     "reply": "Got it. " + _tag("remember", category="boundary",
                                content="Never takes calls before 10am", importance=7)},
    {"id": "note_to_self",
     "message": "Note this for later: look into the grant Priya mentioned",
     "expect": ["save_note"],
     "must_not": ["create_task", "remember"],
     "encoding": "tool",
     "tool_call": {"name": "save_note",
                   "input": {"content": "Look into the grant Priya mentioned", "kind": "idea"}},
     "reply": "Noted for later."},

    # ── drafts: the line between drafting and sending ────────────────
    {"id": "draft_email_not_send",
     "message": "Draft a follow-up email to Ada about next steps",
     "expect": ["draft_email"],
     "must_not": ["draft_and_send", "approve_draft", "send_sms"],
     "encoding": "tool",
     "tool_call": {"name": "draft_email",
                   "input": {"contact_id": CONTACT_IDS["ada"], "subject": "Next steps",
                             "body": "Hi Ada — following up on our conversation. "
                                     "Here is what I'd suggest as next steps.",
                             "reason": "follow-up"}},
     "reply": "Draft is in your queue — review and send when ready."},
    {"id": "send_is_class_c_tag",
     "message": "Send that invoice to Marcus now",
     "expect": ["send_invoice"],
     "must_not": ["mark_invoice_paid", "delete_contact"],
     "encoding": "tag",
     "reply": "Sending it. " + _tag("send_invoice", invoice_id="latest")},

    # ── reads that must stay reads ───────────────────────────────────
    {"id": "goals_are_a_read",
     "message": "Am I on track for my goals?",
     "expect": ["check_goals"],
     "must_not": ["create_goal"],
     "encoding": "tag",
     "reply": "Let me check. " + _tag("check_goals")},
    {"id": "revenue_is_a_read",
     "message": "Show me my revenue breakdown",
     "expect": ["show_revenue"],
     "must_not": ["create_invoice", "log_expense"],
     "encoding": "tag",
     "reply": "Here's the picture. " + _tag("show_revenue")},

    # ── must-nots that are the whole row ─────────────────────────────
    {"id": "goodbye_closes_nothing_else",
     "message": "Thanks, that's all for today. Goodbye!",
     "expect": ["set_chat_window"],
     "must_not": ["send_sms", "draft_and_send", "delete_contact", "create_invoice"],
     "encoding": "tag",
     "reply": "Have a good one. " + _tag("set_chat_window", visible=False,
                                          keep_talking=False)},
    {"id": "question_about_goodbyes_is_not_one",
     "message": "Why does the app close when I say goodbye? Is that a bug?",
     "expect": [],
     "must_not": ["set_chat_window", "send_sms"],
     "encoding": "tag",
     "reply": "It's on purpose — a clear farewell closes the room. Say the word "
              "and I'll leave it open."},
    {"id": "undo",
     "message": "Undo that last one",
     "expect": ["undo_last"],
     "must_not": ["delete_contact", "cancel_booking"],
     "encoding": "tool",
     "tool_call": {"name": "undo_last", "input": {}},
     "reply": "Undone."},
]


# ─── Day one: the first conversation of four new businesses ──────────
# `business` names a NEW_BUSINESSES fixture. `route: full` asks the
# two-track router whether the message reaches the turn that holds the
# product prompt and SETUP STATUS at all (chief_chat, which this eval
# drives, is only that turn). `max_reads` is a lookup budget: a read
# within it is not a miss of restraint. `allow` names verbs a restraint
# row may take without missing. `expect_args` / `expect_week` check the
# facts the verb carried, not just its name.

GREETING = "[SYSTEM:opening_greeting:morning]"

PR_1053 = ("PR #1053 (open): the onboarding welcome note still counts as a draft "
           "waiting for review, and the greeting rule says to mention pending drafts")
PR_1054 = ("PR #1054 (open): an empty list read in full is not marked complete yet, "
           "so 'none yet' reads as unverified and invites lookups")
PR_1056 = ("PR #1056 (open): the router finds 'What can you do for me?' ambiguous, so "
           "Haiku can answer it alone, without the product prompt or SETUP STATUS")
OFFER_READS_AS_DONE = (
    "product bug, no fix yet: chief_of_staff._looks_like_completed_action reads an "
    "offer (\"...and I'll add them\", \"I'll open those on your booking page\") as "
    "work already done. A turn with no action then goes to the missing-action retry, "
    "and without a reviewer verdict the answer check withholds it as 'couldn't verify'")
VERTICAL_SETUP = ("vertical-aware setup (being built, no PR yet): the offerings step "
                  "asks every vertical what it charges, a ministry included")

_DAY_ONE_GREETING = {
    "message": GREETING, "expect": [], "route": "full",
    "must_not": ["navigate", "create_contact", "approve_draft", "run_agent"],
    "reply_checks": ["one_question", "no_list", "no_draft_pointer", "no_unverified"],
    "pending": {"reply:no_draft_pointer": PR_1053},
    "encoding": "tag",
}
_WHAT_CAN_YOU_DO = {
    "message": "What can you do for me?", "expect": [], "route": "full",
    "must_not": ["run_agent", "propose_mission", "create_task"],
    "reply_checks": ["about_the_product", "no_unverified"],
    "pending": {"routes_to_full_turn": PR_1056},
    "encoding": "tag",
}
_ANY_INVOICES = {
    "message": "Do I have any invoices?", "expect": [], "route": "full", "max_reads": 1,
    "must_not": ["create_invoice", "send_invoice", "generate_payment_link"],
    "reply_checks": ["says_none_yet", "no_unverified"],
    "pending": {"reply:says_none_yet": PR_1054, "reply:no_unverified": PR_1054,
                "reads<=1": PR_1054},
    "encoding": "tag",
    "reply": "You don't have any invoices yet. When you're ready to bill someone, tell me "
             "who and for what and I'll put the first one together.",
}
_HOURS = {
    "message": "I work Tuesday to Saturday, 9 to 6", "expect": ["set_availability_day"],
    "route": "full",
    "must_not": ["add_block_range", "set_availability_override", "remember",
                 "set_business_policy"],
    "expect_week": {d: "09:00-18:00" for d in ("tue", "wed", "thu", "fri", "sat")},
    "encoding": "tag",
    "reply": "Done. Your booking page is open Tuesday to Saturday, nine to six. "
             + "".join(_tag("set_availability_day", day=d,
                            hours=[{"start": "09:00", "end": "18:00"}])
                       for d in ("tue", "wed", "thu", "fri", "sat")),
}
_FIRST_CLIENT = {
    "message": "My first client is Jane Doe, jane@example.com", "expect": ["create_contact"],
    "route": "full",
    "must_not": ["draft_email", "draft_and_send", "send_sms", "create_invoice"],
    "expect_args": {"create_contact": {"name": "Jane Doe", "email": "jane@example.com"}},
    "encoding": "tool",
    "tool_call": {"name": "create_contact",
                  "input": {"name": "Jane Doe", "email": "jane@example.com",
                            "status": "active"}},
    "reply": "Jane Doe is in, your first client.",
}


def _row(base: Dict[str, Any], **fields: Any) -> Dict[str, Any]:
    return {**base, **fields}


DAY_ONE_CASES: List[Dict[str, Any]] = [
    # ── a barbershop ─────────────────────────────────────────────────
    _row(_DAY_ONE_GREETING, id="nb_barber_greeting", business="barber",
         reply="Good morning, Dre. Fade Street Barbers is in as a barbershop, and by the "
               "end of this first hour you'll have a booking link your regulars can use "
               "tonight. Who's one regular you'd text today? A name and a phone or email "
               "is enough to start. The twenty-minute sit-down where I learn how you run "
               "the shop can happen now or any time before day three."),
    {"id": "nb_barber_where_to_start", "business": "barber", "route": "full",
     "message": "Where should I start?", "expect": [],
     "must_not": ["create_contact", "send_sms"],
     # The good answer names the first unblocked setup item and asks for
     # it exactly the way SETUP STATUS's 'how' line says to.
     "reply_checks": ["one_question", "no_list", "no_unverified"],
     "pending": {"reply:one_question": OFFER_READS_AS_DONE,
                 "reply:no_unverified": OFFER_READS_AS_DONE},
     "encoding": "tag",
     "reply": "Start with your people: everything else reads from that list. Who's one "
              "regular you'd text today? Give me a name and a phone or email and I'll "
              "add them."},
    _row(_HOURS, id="nb_barber_hours", business="barber"),
    {"id": "nb_barber_offering", "business": "barber", "route": "full",
     "message": "A haircut is $40 and takes 45 minutes",
     "expect": ["create_offering"],
     "must_not": ["create_invoice", "create_product", "generate_payment_link"],
     "expect_args": {"create_offering": {"current_price": 40, "duration_min": 45}},
     "encoding": "tool",
     "tool_call": {"name": "create_offering",
                   "input": {"name": "Haircut", "category": "service",
                             "current_price": 40, "duration_min": 45}},
     "reply": "Haircut is on your menu at $40 for 45 minutes."},
    {"id": "nb_barber_appointments", "business": "barber", "route": "full",
     "message": "Any appointments this week?", "expect": [], "max_reads": 1,
     "must_not": ["create_session", "create_booking", "add_block_range"],
     # The calendar half of "nothing yet" shipped in #1034, so this row
     # is the control for the invoice rows: it should pass today.
     "reply_checks": ["says_none_yet", "no_unverified"],
     "encoding": "tag",
     "reply": "Nothing is booked this week. Once your hours are in, people can book "
              "straight onto your calendar."},

    # ── a therapist ──────────────────────────────────────────────────
    _row(_DAY_ONE_GREETING, id="nb_therapist_greeting", business="therapist",
         reply="Good morning, Maya. Harbor Counseling is set up as a counseling practice, "
               "and by the end of this first hour you'll have a booking link a new client "
               "can use. Who's one client you see now that I should add? A name and an "
               "email or phone is enough, and sessions, notes and invoices all hang off "
               "that list. The twenty-minute sit-down where I learn how you run your "
               "practice can happen now or by day three."),
    _row(_WHAT_CAN_YOU_DO, id="nb_therapist_what_can_you_do", business="therapist",
         reply="I'm Chief, your chief of staff for Harbor Counseling. I keep your client "
               "list, put sessions on your calendar, build intake forms, send invoices and "
               "reminders, and draft emails for you to approve. The first step is your "
               "client list: who's one client I should add?"),
    {"id": "nb_therapist_intake", "business": "therapist", "route": "full",
     "message": "I'd like new clients to fill out an intake form before their first "
                "session. Can you set that up?",
     "expect": ["create_client_form"],
     "must_not": ["propose_module_from_intake", "ensure_module", "draft_and_send",
                  "send_sms"],
     "expect_args": {"create_client_form": {"form_type": "intake"}},
     "encoding": "tag",
     "reply": "Here's your intake form. " + _tag(
         "create_client_form", name="New Client Intake", form_type="intake",
         fields=[{"label": "Your Name", "type": "text", "required": True},
                 {"label": "Email", "type": "email", "required": True},
                 {"label": "Phone", "type": "phone"},
                 {"label": "What brings you to counseling?", "type": "textarea",
                  "required": True},
                 {"label": "Have you seen a therapist before?", "type": "select",
                  "options": ["Yes", "No"]}],
         confirmation_message="Thank you. I'll be in touch before our first session.")},
    _row(_ANY_INVOICES, id="nb_therapist_invoices", business="therapist"),

    # ── a ministry ───────────────────────────────────────────────────
    _row(_DAY_ONE_GREETING, id="nb_ministry_greeting", business="ministry",
         reply_checks=["one_question", "no_list", "no_draft_pointer", "no_unverified",
                       "no_price_question"],
         reply="Good morning, James. Grace Street Fellowship is set up as a ministry, and "
               "by the end of this first hour you'll have a giving page you can share. "
               "Who's one member I should add first? A name and an email or phone is "
               "enough, and every announcement and follow-up reads from that list. The "
               "twenty-minute sit-down where I learn how the church runs can happen now "
               "or by day three."),
    _row(_WHAT_CAN_YOU_DO, id="nb_ministry_what_can_you_do", business="ministry",
         reply_checks=["about_the_product", "no_unverified", "no_price_question"],
         reply="I'm Chief, the chief of staff for Grace Street Fellowship. I keep your "
               "member list, put services and events on your calendar, build connect "
               "cards and forms, draft the emails and texts you send, and track giving. "
               "It starts with your people: who's one member I should add first?"),
    {"id": "nb_ministry_next_step", "business": "ministry", "route": "full",
     "message": "Let's skip the member list for now. What else should I set up?",
     "expect": [], "allow": ["navigate"],
     "must_not": ["create_offering", "create_invoice", "generate_payment_link"],
     "reply_checks": ["no_price_question"],
     "pending": {"reply:no_price_question": VERTICAL_SETUP},
     "encoding": "tag",
     "reply": "No problem, we can bring your members over later. When does Grace Street "
              "gather on Sundays, and is there a midweek service? I'll put them on your "
              "site so a visitor knows when to come."},

    # ── a business coach ─────────────────────────────────────────────
    _row(_DAY_ONE_GREETING, id="nb_coach_greeting", business="coach",
         reply="Good morning, Tasha. Northstar Business Coaching is set up as a coaching "
               "practice, and by the end of this first hour you'll have a booking link a "
               "client can use this week. Who's one person you're coaching now? A name and "
               "an email is enough, and sessions, notes and invoices all hang off that "
               "list. The twenty-minute sit-down where I learn how you coach can happen "
               "now or by day three."),
    _row(_WHAT_CAN_YOU_DO, id="nb_coach_what_can_you_do", business="coach",
         reply="I'm Chief, your chief of staff for Northstar Business Coaching. I keep your "
               "client list, book coaching sessions on your calendar, send invoices and "
               "reminders, build intake forms, and draft follow-up emails for you to "
               "approve. The first step is your client list: who's one client I should add?"),
    _row(_ANY_INVOICES, id="nb_coach_invoices", business="coach"),
    _row(_FIRST_CLIENT, id="nb_coach_first_client", business="coach"),
    {"id": "nb_coach_offering", "business": "coach", "route": "full",
     "message": "My 90-minute strategy session is $250",
     "expect": ["create_offering"],
     "must_not": ["create_invoice", "create_product", "generate_payment_link"],
     "expect_args": {"create_offering": {"current_price": 250, "duration_min": 90}},
     "encoding": "tool",
     "tool_call": {"name": "create_offering",
                   "input": {"name": "Strategy Session", "category": "session",
                             "current_price": 250, "duration_min": 90}},
     "reply": "Strategy Session is on your menu at $250 for 90 minutes."},
]

CASES += DAY_ONE_CASES


# ─── Scoring ──────────────────────────────────────────────────────────

# Reply checks: what a day-one reply owes that no verb can show. Each is
# a named, deterministic heuristic sized to one sentence of regex, the
# chief_factual_eval discipline. They read the reply the practitioner
# actually got (after the answer check), so a good draft the answer
# check withheld fails them too.

_QUESTION_MARK = re.compile(r"\?+(?=[\s\"'”’)\]]|$)")
_LIST_LINE = re.compile(r"(?m)^\s*(?:[-*•]|\d+[.)])\s+\S")
_DRAFT_POINTER = re.compile(
    r"\bdrafts?\b|\bwelcome (?:note|message|email)\b|\bapprovals\b"
    r"|waiting (?:for|on) (?:your )?(?:review|approval)|needs? your (?:review|approval)"
    r"|\bin your queue\b", re.I)
_NONE_YET = re.compile(
    r"\b(?:no|zero)\b[^.?!]{0,30}\b(?:invoices?|appointments?|sessions?|bookings?)\b"
    r"|\bnothing(?:'s|\s+is|\s+has\s+been)?\s+(?:booked|scheduled|billed|on\s+(?:the|your)\s+calendar)"
    r"|\bnone\b|\bdon.t have any\b|\baren.t any\b|\bnot\s+(?:yet|any)\b|\bempty\b", re.I)
_UNVERIFIED = re.compile(
    r"(?:couldn.t|could not|can.t|cannot|unable to|wasn.t able to)\s+"
    r"(?:verify|confirm|check|read|load|access|see)"
    r"|check data availability|\bunavailable\b|\btry again\b", re.I)
_PRICE_WORD = re.compile(r"\b(?:charge[sd]?|charging|prices?|pricing|rates?|fees?|costs?)\b", re.I)
# A product answer names what Chief does, in more than one area.
_CAPABILITY_AREAS = (
    r"\bbook(?:s|ed|ing|ings)?\b|\bcalendar\b|\bschedul\w*|\bappointments?\b|\bsessions?\b",
    r"\bcontacts?\b|\bclient list\b|\bmembers?\b|\bclients?\b",
    r"\binvoic\w*|\bpayments?\b|\bgiving\b|\bbill(?:s|ing)?\b",
    r"\bemails?\b|\btexts?\b|\bmessages?\b|\bdrafts?\b|\breminders?\b|\bfollow[- ]ups?\b",
    r"\bforms?\b|\bintake\b|\bquestionnaires?\b|\bconnect cards?\b",
    r"\bsite\b|\bwebsite\b|\bbooking (?:link|page)\b",
)


def _question_sentences(reply: str) -> List[str]:
    return [s for s in re.split(r"(?<=[.!?])\s+", reply or "") if s.rstrip().endswith("?")]


REPLY_CHECKS: Dict[str, Any] = {
    # The launch greeting: ONE setup question, not a menu.
    "one_question": lambda r: len(_QUESTION_MARK.findall(r or "")) == 1,
    # Day one is not a list.
    "no_list": lambda r: not _LIST_LINE.search(r or ""),
    # The onboarding welcome note is not work waiting on a new practitioner.
    "no_draft_pointer": lambda r: not _DRAFT_POINTER.search(r or ""),
    # A list read in full and found empty is an answer: none yet.
    "says_none_yet": lambda r: bool(_NONE_YET.search(r or "")),
    # ...and not a hedge, a failed-read line, or the answer check's fallback.
    "no_unverified": lambda r: not _UNVERIFIED.search(r or ""),
    # A ministry is not asked what it charges.
    "no_price_question": lambda r: not any(_PRICE_WORD.search(q)
                                           for q in _question_sentences(r)),
    "about_the_product": lambda r: sum(bool(re.search(p, r or "", re.I))
                                       for p in _CAPABILITY_AREAS) >= 3,
}


def _is_read(verb: str) -> bool:
    import action_registry
    return action_registry.effect(verb) == action_registry.READ


def _routes_to_full_turn(message: str) -> bool:
    """Does this message reach the turn that holds the product prompt and
    SETUP STATUS? chief_fast_track sends a clear fast verdict to Haiku
    alone, and an ambiguous QUESTION wherever the Haiku classifier says
    (_decide_ambiguous). Pure: the classifier is not called, because a
    message that needs it can already miss the full turn."""
    import model_router as mr
    route = mr.decide(mr.score(message))
    if route.lane != mr.LANE_FULL:
        return False
    return not (route.ambiguous and mr.is_question(message))


def _same(have: Any, want: Any) -> bool:
    if isinstance(want, (int, float)) and not isinstance(want, bool):
        try:
            return float(have) == float(want)
        except (TypeError, ValueError):
            return False
    return str(have or "").strip().casefold() == str(want).strip().casefold()


def _hhmm(value: Any) -> str:
    m = re.match(r"^\s*(\d{1,2}):(\d{2})", str(value or ""))
    return f"{int(m.group(1)):02d}:{m.group(2)}" if m else str(value)


def _open_week(actions: List[Dict[str, Any]]) -> Dict[str, str]:
    """The weekly hours the turn's set_availability_day calls leave open,
    {day: "HH:MM-HH:MM"}. A day set to no hours is closed, not open."""
    week: Dict[str, str] = {}
    for a in actions:
        if a.get("type") != "set_availability_day":
            continue
        day = str(a.get("day") or "")[:3].lower()
        spans = sorted(f"{_hhmm(h.get('start'))}-{_hhmm(h.get('end'))}"
                       for h in (a.get("hours") or []) if isinstance(h, dict))
        if spans:
            week[day] = ",".join(spans)
        else:
            week.pop(day, None)
    return week


def score_case(case: Dict[str, Any], taken_verbs: List[str],
               extra: Optional[Dict[str, Any]] = None, *,
               reply: Optional[str] = None,
               actions: Optional[List[Dict[str, Any]]] = None,
               reads: Optional[List[str]] = None) -> Dict[str, Any]:
    """Deterministic. `taken_verbs` are the verbs the turn actually
    produced (actions_taken types, in order); `actions` the action dicts
    that reached the door, `reply` the text the practitioner got, and
    `reads` every lookup the turn made, repeats included (default: the
    read verbs in taken_verbs). Each is only checked when the row asks
    for it. Every check is one a human would agree with on sight."""
    checks: List[Dict[str, Any]] = []
    got = set(taken_verbs)
    for v in case.get("expect") or []:
        checks.append({"check": f"expect:{v}", "ok": v in got,
                       "detail": f"took {sorted(got) or '-'}"})
    for v in case.get("must_not") or []:
        checks.append({"check": f"must_not:{v}", "ok": v not in got,
                       "detail": f"took {sorted(got) or '-'}"})
    if not case.get("expect"):
        # A row that expects nothing is testing restraint: any verb at
        # all is a miss, not only the named neighbours — except a read
        # inside the row's lookup budget, or a verb the row allows.
        spare = set(case.get("allow") or [])
        if "max_reads" in case:
            spare |= {v for v in got if _is_read(v)}
        checks.append({"check": "no_action", "ok": not (got - spare),
                       "detail": f"took {sorted(got) or '-'}"})
    if "max_reads" in case:
        reads = list(reads) if reads is not None else [v for v in taken_verbs if _is_read(v)]
        checks.append({"check": f"reads<={case['max_reads']}",
                       "ok": len(reads) <= case["max_reads"],
                       "detail": f"read {reads or '-'}"})
    if actions is not None:
        for verb, want in (case.get("expect_args") or {}).items():
            calls = [a for a in actions if a.get("type") == verb]
            checks.append({"check": f"args:{verb}",
                           "ok": any(all(_same(a.get(k), v) for k, v in want.items())
                                     for a in calls),
                           "detail": f"wanted {want}, sent {calls or '-'}"[:300]})
        if case.get("expect_week"):
            week = _open_week(actions)
            checks.append({"check": "week:set_availability_day",
                           "ok": week == case["expect_week"],
                           "detail": f"open {week or '-'}"})
    if case.get("route") == "full":
        checks.append({"check": "routes_to_full_turn",
                       "ok": _routes_to_full_turn(case["message"]), "detail": ""})
    if reply is not None:
        for name in case.get("reply_checks") or []:
            checks.append({"check": f"reply:{name}", "ok": bool(REPLY_CHECKS[name](reply)),
                           "detail": reply[:160]})
    if extra:
        for k, ok in extra.items():
            checks.append({"check": k, "ok": bool(ok), "detail": ""})
    pending = case.get("pending") or {}
    for c in checks:
        if not c["ok"] and c["check"] in pending:
            c["pending"] = pending[c["check"]]
    score = sum(1 for c in checks if c["ok"])
    out = {"id": case["id"], "encoding": case.get("encoding"),
           "score": score, "total": len(checks), "checks": checks,
           "taken": list(taken_verbs),
           "failed": any(not c["ok"] and "pending" not in c for c in checks)}
    if pending:
        out["pending_cleared"] = [c["check"] for c in checks
                                  if c["check"] in pending and c["ok"]]
    return out


def skipped_case(case: Dict[str, Any], reason: str) -> Dict[str, Any]:
    return {"id": case["id"], "encoding": case.get("encoding"), "score": 0, "total": 0,
            "checks": [], "taken": [], "failed": False, "skipped": reason}


def summarize(results: List[Dict[str, Any]], mode: str) -> Dict[str, Any]:
    report = {
        "mode": mode,
        "results": results,
        "total": sum(r["score"] for r in results),
        "possible": sum(r["total"] for r in results),
        # A pending check that misses is reported, never a failure.
        "failed_cases": [r["id"] for r in results
                         if r.get("failed", r["score"] < r["total"])],
        "pending": [{"id": r["id"], "check": c["check"], "reason": c["pending"]}
                    for r in results for c in r["checks"] if "pending" in c],
        "skipped": [{"id": r["id"], "reason": r["skipped"]}
                    for r in results if r.get("skipped")],
    }
    if mode == "live":
        # Replay's recorded replies pass every prose check by construction,
        # so only a live pass says the fix has landed.
        report["pending_cleared"] = [{"id": r["id"], "check": c}
                                     for r in results for c in r.get("pending_cleared") or []]
    return report


# ─── Replay: the pipeline, with a recorded reply ──────────────────────
#
# Stubs every I/O seam chief_chat has, the way __tests__/test_farewell_close.py
# does, and puts a spy on the door (_execute_actions) so the verbs the
# turn dispatched are observed WITHOUT reaching a handler. For a `tool`
# row the fake model performs the recorded tool call through
# chief_tool_loop.execute_tool_use — the real loop, the real budget, the
# real door — before answering.

def _stub_turn(monkeypatch, biz: Dict[str, Any], case=None):
    import chief_of_staff as cos
    import rate_limit
    import errand_completion
    monkeypatch.setattr(errand_completion,'reports',lambda *a:[])

    async def _instant(value=None):
        return value

    tables = _day_one_tables(biz) if biz.get("id") in _DAY_ONE_IDS else None
    context = None if tables is not None else _fixture_context(biz, case)

    async def _fake_sb(client, method, path, body=None):
        if tables is not None:
            return _postgrest(tables, method, path)
        if path.startswith('/businesses?'):
            return [biz]
        if path.startswith('/contacts?'):
            return _fixture_select(context['contacts_lookup'], path)
        if path.startswith('/invoices?'):
            return context['open_invoices']
        if path.startswith('/chief_undo_log?') and case and case['id'] == 'undo':
            return [{'id': 'undo-one', 'action_type': 'create_task', 'status': 'undoable',
                     'action_json': {'title': 'Review draft'},
                     'result_json': {'task_id': 'task-one'}}]
        return []

    monkeypatch.setattr(rate_limit, "allow", lambda *a, **k: True)
    import sb_clients
    import practitioner_profile_agent
    import voice_depth_agent
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda *a, **k: [])
    monkeypatch.setattr(practitioner_profile_agent, "_sb_get", lambda *a, **k: [])
    monkeypatch.setattr(voice_depth_agent, "_sb_get", lambda *a, **k: [])
    monkeypatch.setattr(cos, "_sb", _fake_sb)
    if tables is not None:
        _serve_day_one(monkeypatch, tables)
    monkeypatch.setattr(cos, "_generate_missing_recurring_instances", lambda *a, **k: _instant(0))
    monkeypatch.setattr(cos, "_autopilot_sweep", lambda *a, **k: _instant(0))
    monkeypatch.setattr(cos, "_evaluate_escalations", lambda *a, **k: _instant(0))
    if tables is None:
        monkeypatch.setattr(cos, "_gather_context",
                            lambda *a, **k: _instant(context))
    monkeypatch.setattr(cos, "_fetch_view_detail", lambda *a, **k: _instant(""))
    for name in ["_get_voice_examples", "_get_session_context",
                 "_get_time_context", "_get_habit_insights"]:
        monkeypatch.setattr(cos, name, lambda *a, **k: _instant(""))
    monkeypatch.setattr(cos, "_should_show_mentor_tip", lambda *a, **k: _instant(False))
    monkeypatch.setattr(cos, "_forecast_revenue", lambda *a, **k: _instant(None))
    monkeypatch.setattr(cos, "_analyze_relationships", lambda *a, **k: _instant([]))
    monkeypatch.setattr(cos, "_build_system_prompt", lambda *a, **k: "SYSTEM")
    monkeypatch.setattr(cos, "_log_chief_activity", lambda *a, **k: _instant(None))
    monkeypatch.setattr(cos, "_learn_patterns_async", lambda *a, **k: _instant(None))
    monkeypatch.setattr(cos, "_compose_post_action_reply", lambda *a, **k: _instant(""))
    if hasattr(cos, "_archive_turn"):
        monkeypatch.setattr(cos, "_archive_turn", lambda *a, **k: _instant(None))

    import chief_bookkeeping
    import chief_proactive_suggestions
    import vertical_context
    monkeypatch.setattr(chief_bookkeeping, "gather_and_format", lambda *a, **k: "")
    monkeypatch.setattr(vertical_context, "build_vertical_learned_block", lambda *a, **k: "")
    monkeypatch.setattr(chief_proactive_suggestions,
                        "maybe_emit_proactive_suggestions", lambda *a, **k: None)


class _Session:
    class _User:
        id = "user-eval"
    user = _User()
    token = "eval-jwt"


BIZ = {"id": "00000000-0000-4000-8000-000000000010", "name": "Eval Co", "type": "coach", "owner_id": "user-eval",
       "settings": {}}


def _fixture_context(biz, case=None):
    # The authored rows reference these exact people. A blank context makes
    # correct refusal to invent their IDs look like failed action selection.
    contacts = [
        {'id': CONTACT_IDS['marcus'], 'name': 'Marcus Reed', 'email': 'marcus@example.com', 'status': 'active'},
        {'id': CONTACT_IDS['monica'], 'name': 'Monica Walton', 'email': 'monica@example.com', 'status': 'active'},
        {'id': CONTACT_IDS['ada'], 'name': 'Ada Lovelace', 'email': 'ada@example.com', 'status': 'lead'},
    ]
    for contact in contacts:
        contact['health_score'] = 50
        contact['business_id'] = biz['id']
    contacts[-1]['notes'] = ('Discussed the leadership program. Next steps: send the program '
                             'outline and propose a discovery call.')
    if case and case['id'] == 'create_contact_lead':
        contacts = [c for c in contacts if c['id'] != CONTACT_IDS['ada']]
    if case and case['id'] == 'create_contact_tag':
        contacts = [c for c in contacts if c['id'] != CONTACT_IDS['marcus']]
    context = {'business': biz, 'contacts_total': len(contacts), 'contacts_loaded': len(contacts),
            'contacts_complete': True, 'contacts_by_status': {}, 'avg_health': 0,
            'module_counts': {}, **{key: [] for key in (
                'contacts', 'at_risk', 'queue', 'sessions', 'insights', 'modules',
                'events', 'memories', 'notifications', 'recent_queue_24h', 'projects',
                'products', 'contacts_lookup', 'open_invoices')}}
    context['contacts_lookup'] = contacts
    if case and case['id'] == 'send_is_class_c_tag':
        context['open_invoices'] = [{'id': 'inv-marcus', 'number': 'INV-001',
            'client': 'Marcus Reed', 'contact_id': CONTACT_IDS['marcus'], 'total': 520,
            'status': 'draft', 'due_date': '2026-09-30'}]
    return context


def _fixture_select(rows, path):
    query = parse_qs(urlsplit(path).query)
    selected = list(rows)
    for key in ('id', 'business_id', 'name'):
        for value in query.get(key, []):
            if value.startswith('eq.'):
                selected = [row for row in selected if str(row.get(key)) == value[3:]]
            elif value.startswith('ilike.'):
                pattern = re.escape(value[6:]).replace(r'\*', '.*').replace('%', '.*')
                selected = [row for row in selected if re.fullmatch(pattern, str(row.get(key, '')), re.I)]
    return selected


# ─── Day one: four businesses that signed up today ────────────────────
# Type keys are what the product stores and resolves (the census in
# __tests__/test_workspace_archetypes.py, vertical_registry): a barbershop
# is `personal_services` (the salon desk), a counseling practice
# `therapist`, a church `ministry`, a business coach `coach`.

NEW_BUSINESSES: Dict[str, Dict[str, str]] = {
    "barber": {"id": "00000000-0000-4000-8000-000000000020", "name": "Fade Street Barbers",
               "type": "personal_services", "practitioner": "Dre Carter"},
    "therapist": {"id": "00000000-0000-4000-8000-000000000021", "name": "Harbor Counseling",
                  "type": "therapist", "practitioner": "Maya Lin"},
    "ministry": {"id": "00000000-0000-4000-8000-000000000022",
                 "name": "Grace Street Fellowship", "type": "ministry",
                 "practitioner": "James Cole"},
    "coach": {"id": "00000000-0000-4000-8000-000000000023",
              "name": "Northstar Business Coaching", "type": "coach",
              "practitioner": "Tasha Reed"},
}
_DAY_ONE_IDS = {spec["id"] for spec in NEW_BUSINESSES.values()}


def _business_for(case: Dict[str, Any]) -> Dict[str, Any]:
    """The business a row runs against: Eval Co, or a day-one business
    row exactly as /access/businesses/create writes it from onboarding,
    stamped twenty minutes ago."""
    key = case.get("business")
    if not key:
        return BIZ
    spec = NEW_BUSINESSES[key]
    settings: Dict[str, Any] = {"practitioner_name": spec["practitioner"],
                                "priority_agents": ["intake"], "custom_type": None,
                                "track": "purpose"}
    if any(k in spec["type"] for k in ("law", "therap", "counsel")):
        # launch_access: regulated verticals start with client-facing autonomy off.
        settings["autonomy"] = {"client_facing_autonomy": "disabled",
                                "disabled_reason": "regulated_vertical_default",
                                "acknowledgment_required": True, "acknowledged_at": None}
    signed_up = datetime.now(timezone.utc) - timedelta(minutes=20)
    return {"id": spec["id"], "name": spec["name"], "type": spec["type"],
            "owner_id": "user-eval", "tier": "starter", "settings": settings,
            "voice_profile": {}, "stripe_account_id": None,
            "created_at": signed_up.isoformat()}


def _onboarding_profile(biz: Dict[str, Any]) -> List[Dict[str, Any]]:
    """business_profiles as OnboardingFlow's seed-from-onboarding call
    leaves it: the product's own seed (the archetype's defaults), captured
    instead of written."""
    import pytest
    import business_profile_agent
    written: List[Dict[str, Any]] = []

    def post(path, body):
        written.append(dict(body))
        return [dict(body)]
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(business_profile_agent, "_sb_get", lambda path: [])
        mp.setattr(business_profile_agent, "_sb_post", post)
        business_profile_agent.seed_from_onboarding(biz["id"], biz["type"])
    return written


def _day_one_tables(biz: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    """What signup writes, and nothing else: /access/businesses/create
    (the business row, then first_run_arc.begin from the signup door) and
    OnboardingFlow (the seeded business profile, the purpose-track row
    the coached session opens, and the static welcome note it drops in
    agent_queue). No contacts, sessions, invoices, offerings, products or
    projects, and no practitioner profile: every table not named here is
    empty."""
    at = biz["created_at"]
    name = biz["settings"]["practitioner_name"]
    return {
        "businesses": [biz],
        "business_profiles": _onboarding_profile(biz),
        "business_tracks": [{"id": biz["id"].replace("-8000-", "-8001-"),
                             "business_id": biz["id"], "status": "in_progress",
                             "current_phase": "owner", "phases": {},
                             "created_at": at, "updated_at": at}],
        "agent_queue": [{"id": biz["id"].replace("-8000-", "-8002-"),
                         "business_id": biz["id"], "agent": "system",
                         "action_type": "other",
                         "subject": f"Welcome to The Solutionist System, {name}!",
                         "body": (f"Welcome, {name} — everything for {biz['name']} is set "
                                  "up and ready.\n\nChief is sitting down with you now to "
                                  "learn the business properly. When you're done, you'll "
                                  "have a short list of what to plug in first."),
                         "channel": "in_app", "status": "draft", "priority": "medium",
                         "contact_id": None,
                         "ai_reasoning": "Standard welcome message created at onboarding.",
                         "created_at": at}],
        "first_run_arc": [{"id": biz["id"].replace("-8000-", "-8003-"),
                           "business_id": biz["id"], "source": "signup", "started_at": at,
                           "trial_ends_at": None, "status": "pending_intro",
                           "intro_delivered_at": None, "completed_steps": [],
                           "shared_links": [], "last_beat_day": 0, "last_beat_at": None}],
    }


_PG_RESERVED = {"select", "order", "limit", "offset", "or", "and", "on_conflict", "columns"}


def _pg_order(value: Any) -> Any:
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        pass
    try:
        return float(value)
    except (TypeError, ValueError):
        return str(value)


def _pg_match(row: Dict[str, Any], key: str, cond: str) -> bool:
    op, _, val = cond.partition(".")
    if op == "not":
        return not _pg_match(row, key, val)
    have = row.get(key)
    if op == "is":
        return {"null": have is None, "true": have is True,
                "false": have is False}.get(val.lower(), True)
    if op == "in":
        return str(have) in {v.strip().strip('"') for v in val.strip("()").split(",")}
    if op in ("eq", "neq"):
        text = str(have).lower() if isinstance(have, bool) else str(have)
        return (have is not None and text == val) == (op == "eq")
    if op in ("gt", "gte", "lt", "lte"):
        if have is None:
            return False
        a, b = _pg_order(have), _pg_order(val)
        if type(a) is not type(b):
            a, b = str(have), val
        return {"gt": a > b, "gte": a >= b, "lt": a < b, "lte": a <= b}[op]
    if op in ("like", "ilike"):
        pattern = re.escape(val).replace(r"\*", ".*").replace("%", ".*")
        return re.fullmatch(pattern, str(have or ""), re.I if op == "ilike" else 0) is not None
    return True  # an operator this fixture does not model filters nothing


def _pg_project(row: Dict[str, Any], select: str) -> Dict[str, Any]:
    cols, depth, cur = [], 0, ""
    for ch in select:
        if ch == "," and depth == 0:
            cols.append(cur)
            cur = ""
            continue
        depth += (ch == "(") - (ch == ")")
        cur += ch
    cols.append(cur)
    out: Dict[str, Any] = {}
    for col in (c.strip() for c in cols):
        head = col.split("(")[0]
        alias, _, source = head.rpartition(":") if ":" in head else ("", "", head)
        name = source.split("!")[0].strip()
        if name == "*":
            out.update(row)
        elif name in row:
            out[alias or name] = row[name]
    return out


def _postgrest(tables: Dict[str, List[Dict[str, Any]]], method: str, path: str,
               body: Any = None) -> List[Dict[str, Any]]:
    """A PostgREST that holds only `tables`. A GET filters (eq, neq, in,
    is, gt/gte/lt/lte, like/ilike, not.) and projects `select` the way the
    real one does, so a column nobody selected never reaches the caller.
    A write is recorded under '_writes', answered as written, never sent."""
    if method.upper() not in ("GET", "HEAD"):
        tables.setdefault("_writes", []).append({"method": method.upper(), "path": path,
                                                 "body": body})
        # return=representation: the rows as written.
        return [dict(body)] if isinstance(body, dict) else list(body or [])
    table, _, qs = path.lstrip("/").partition("?")
    query = parse_qs(qs.replace("+", "%2B"), keep_blank_values=True)
    rows = [dict(r) for r in tables.get(table, [])
            if all(_pg_match(r, k, v) for k, vals in query.items()
                   if k not in _PG_RESERVED for v in vals)]
    if query.get("limit"):
        rows = rows[:int(query["limit"][0])]
    return [_pg_project(r, query.get("select", ["*"])[0]) for r in rows]


def _serve_day_one(monkeypatch, tables: Dict[str, List[Dict[str, Any]]]) -> None:
    """Every Supabase seam a turn reads through, answered from `tables`:
    the real _gather_context, the setup probes, the first-run arc and the
    lookups the model makes all read day one. Writes are recorded, never
    sent. The semantic memory match (an embedding call) finds nothing,
    which is the truth for a business with no memories."""
    import sb_clients
    import chief_invoice_actions
    import chief_memory_semantic
    import foundation_agent
    import practitioner_profile_agent
    import voice_depth_agent

    def get(path, *a, **k):
        return _postgrest(tables, "GET", path)

    def write(path, body=None, *a, **k):
        return _postgrest(tables, "WRITE", path, body)

    async def request(client, method, path, body=None, *a, **k):
        return _postgrest(tables, method, path, body)

    async def as_user(client, method, path, user_jwt, body=None):
        return _postgrest(tables, method, path, body)

    async def count(client, path, *a, **k):
        return len(_postgrest(tables, "GET", path))

    async def module_get(client, path):
        return _postgrest(tables, "GET", path)

    for name in ("sb_get_as_service", "sb_get_current_context", "sb_get_as_user",
                 "sb_get_as_anon"):
        monkeypatch.setattr(sb_clients, name, get)
    for name in ("sb_patch_as_service", "sb_post_as_service", "sb_patch_current_context",
                 "sb_post_current_context", "sb_patch_as_user", "sb_post_as_user",
                 "sb_patch_as_anon"):
        monkeypatch.setattr(sb_clients, name, write)
    def delete(path, *a, **k):
        write(path)
        return True

    for name in ("sb_delete_as_service", "sb_delete_current_context", "sb_delete_as_user"):
        monkeypatch.setattr(sb_clients, name, delete)
    for name in ("sb_as_current_context", "sb_as_service", "sb_as_anon"):
        monkeypatch.setattr(sb_clients, name, request)
    monkeypatch.setattr(sb_clients, "sb_as_user", as_user)
    monkeypatch.setattr(sb_clients, "sb_count_as_current_context", count)
    monkeypatch.setattr(chief_invoice_actions, "sb_as_current_context", request)
    monkeypatch.setattr(practitioner_profile_agent, "_sb_get", get)
    monkeypatch.setattr(voice_depth_agent, "_sb_get", get)
    monkeypatch.setattr(foundation_agent, "_sb_get", module_get)
    monkeypatch.setattr(chief_memory_semantic, "match", lambda *a, **k: [])


def _door_spy(dispatched: List[Dict[str, Any]]):
    """_execute_actions, observed: each action that reaches the door is
    recorded with its arguments and answered ok, never handled."""
    async def _door(client, biz, actions, user_id=None, prior_results=None,
                    owner_text=None):
        out = []
        for a in actions:
            dispatched.append(dict(a))
            out.append({"type": a.get("type"), "result": "ok",
                        "label": f"did {a.get('type')}"})
        return out
    return _door


def run_replay_case(monkeypatch, case: Dict[str, Any]) -> Dict[str, Any]:
    import chief_of_staff as cos
    import chief_tool_loop as ctl

    if "reply" not in case:
        return skipped_case(case, "no recorded reply: this row runs live only")
    biz = _business_for(case)
    _stub_turn(monkeypatch, biz)
    dispatched: List[Dict[str, Any]] = []
    monkeypatch.setattr(cos, "_execute_actions", _door_spy(dispatched))

    async def fake_claude(*a, **k):
        if case.get("encoding") == "tool":
            tc = case["tool_call"]
            await ctl.execute_tool_use(None, biz, tc["name"], dict(tc.get("input") or {}))
        return case["reply"]
    monkeypatch.setattr(cos, "_call_claude", fake_claude)

    out = asyncio.run(cos.chief_chat(
        cos.ChatRequest(business_id=biz["id"], message=case["message"]), _Session()))
    taken = [a.get("type") for a in out.get("actions_taken", []) if isinstance(a, dict)]
    names = [a.get("type") for a in dispatched]
    extra = {}
    if case.get("encoding") == "tool":
        # The tool row's own invariant: the verb reached the door through
        # the loop, and the turn did NOT also execute it as a tag.
        extra["tool_went_through_the_door"] = case["tool_call"]["name"] in names
        extra["not_double_executed"] = names.count(case["tool_call"]["name"]) == 1
        extra["reply_has_checked_outcome"] = (out.get('grounding') or {}).get('status') in ('supported', 'receipts')
    return score_case(case, taken, extra, reply=out.get("response") or "",
                      actions=dispatched)


def run_replay(cases: List[Dict[str, Any]]) -> Dict[str, Any]:
    import pytest  # the monkeypatch fixture, used standalone
    results = []
    for case in cases:
        mp = pytest.MonkeyPatch()
        try:
            results.append(run_replay_case(mp, case))
        finally:
            mp.undo()
    return summarize(results, "replay")


# ─── Live: the real model, every read stubbed ─────────────────────────

def run_live(cases: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY is not set. --live makes real calls; run it "
              "where the key lives or export one.", file=sys.stderr)
        sys.exit(2)
    import pytest
    import chief_of_staff as cos
    results = []
    for case in cases:
        mp = pytest.MonkeyPatch()
        try:
            real_prompt = cos._build_system_prompt
            biz = _business_for(case)
            _stub_turn(mp, biz, case)
            # The real prompt this time — that is what is being measured.
            mp.setattr(cos, "_build_system_prompt", real_prompt)
            dispatched: List[Dict[str, Any]] = []
            import chief_tool_loop as ctl
            native_reads: List[str] = []
            execute_tool = ctl.execute_tool_use

            async def _observe_tool(client, biz, name, args):
                import action_registry
                if action_registry.effect(name) == action_registry.READ:
                    native_reads.append(name)
                return await execute_tool(client, biz, name, args)

            mp.setattr(ctl, 'execute_tool_use', _observe_tool)
            mp.setattr(cos, "_execute_actions", _door_spy(dispatched))
            print(f"→ {case['id']} …", file=sys.stderr, flush=True)
            started = time.time()
            history = ([{'role': 'user', 'content': 'Create a task to review the draft'},
                        {'role': 'assistant', 'content': 'Created task: Review draft.'}]
                       if case['id'] == 'undo' else None)
            out = asyncio.run(cos.chief_chat(
                cos.ChatRequest(business_id=biz["id"], message=case["message"],
                                conversation_history=history),
                _Session()))
            taken = [a.get("type") for a in out.get("actions_taken", [])
                     if isinstance(a, dict)]
            # Native reads return into the model, not actions_taken. They
            # still count as read selection in this verb-only evaluation.
            reads = [v for v in taken if _is_read(v)] + native_reads
            taken = list(dict.fromkeys(taken + native_reads))
            scored = score_case(case, taken, reply=out.get("response") or "",
                                actions=dispatched, reads=reads)
            scored["seconds"] = round(time.time() - started, 1)
            scored["reply"] = (out.get("response") or "")[:300]
            results.append(scored)
            print(f"  {scored['score']}/{scored['total']} took={taken or '-'}",
                  file=sys.stderr)
        finally:
            mp.undo()
    return summarize(results, "live")


# ─── Compare + CLI ────────────────────────────────────────────────────

def compare(before: Dict[str, Any], after: Dict[str, Any]) -> int:
    print(f"mode        : {before.get('mode')} → {after.get('mode')}")
    print(f"total score : {before['total']}/{before['possible']} → "
          f"{after['total']}/{after['possible']}\n")
    b = {r["id"]: r for r in before["results"]}
    regressions = 0
    for r in after["results"]:
        prior = b.get(r["id"])
        if not prior:
            continue
        delta = r["score"] - prior["score"]
        flag = "  " if delta >= 0 else "!!"
        print(f"{flag} {r['id']:<34} {prior['score']}/{prior['total']} → "
              f"{r['score']}/{r['total']}  ({delta:+d})")
        if delta < 0:
            regressions += 1
            now_failing = {c["check"] for c in r["checks"] if not c["ok"]}
            was_failing = {c["check"] for c in prior["checks"] if not c["ok"]}
            for c in sorted(now_failing - was_failing):
                print(f"     newly failing: {c}")
    if after.get("mode") == "live":
        print("\nNOTE: live runs are not deterministic. Run the baseline twice "
              "and look at the spread before blaming a change.")
    return 1 if regressions else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--live", action="store_true", help="hit the real model")
    ap.add_argument("--out", help="write results as JSON")
    ap.add_argument("--only", choices=[case['id'] for case in CASES], help="run one case by id")
    ap.add_argument("--compare", nargs=2, metavar=("BEFORE", "AFTER"))
    args = ap.parse_args()

    if args.compare:
        with open(args.compare[0], encoding="utf-8") as f:
            before = json.load(f)
        with open(args.compare[1], encoding="utf-8") as f:
            after = json.load(f)
        return compare(before, after)

    cases = [c for c in CASES if not args.only or c["id"] == args.only]
    report = run_live(cases) if args.live else run_replay(cases)
    for r in report["results"]:
        if r.get("skipped"):
            print(f"-- {r['id']:<34} skipped: {r['skipped']}")
            continue
        flag = ("  " if r["score"] == r["total"] else "!!" if r.get("failed", True)
                else "~~")
        print(f"{flag} {r['id']:<34} {r['score']}/{r['total']}  took={r['taken'] or '-'}")
    print(f"\n{report['mode']}: {report['total']}/{report['possible']}"
          + (f"  failed: {report['failed_cases']}" if report["failed_cases"] else ""))
    if report["pending"]:
        print("\n~~ pending (reported, not failed; each names what fixes it):")
        for p in report["pending"]:
            print(f"   {p['id']} {p['check']}: {p['reason']}")
    for p in report.get("pending_cleared") or []:
        print(f"   now passing live: {p['id']} {p['check']}. Take the marker out once it holds.")
    if report["skipped"]:
        print(f"\n-- skipped in replay (no recorded reply): {[s['id'] for s in report['skipped']]}")
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
    return 1 if report["failed_cases"] else 0


if __name__ == "__main__":
    sys.exit(main())
