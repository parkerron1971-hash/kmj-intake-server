"""
business_track_actions.py — THE BUSINESS TRACK.

THE GAP THIS CLOSES
═══════════════════════════════════════════════════════════════════════
Onboarding step 1 asks "what brings you here today?" and forks two ways.
Only one fork led anywhere deep:

  "I have an idea I want to launch"    -> strategy_tracks + an 8-phase
                                          coached Strategy Session that
                                          opens the moment onboarding ends
  "I have a business I want to manage" -> a 12-turn chat inside onboarding
                                          aimed at three questions, whose
                                          answers were then harvested by a
                                          six-keyword regex

The established path is the one that arrives with the most to tell us —
a client list, prices, a way money already moves, tools already in use —
and it was the path that captured the least. `business_profiles` landed
around 40% complete, `practitioners` (the human) landed empty, and
`offerings` was never touched at intake at all. Chief then met a
practitioner it barely knew and had to ask, later, one nudge banner at a
time.

Worse: `vertical_intelligence` already writes per-vertical onboarding
questions for exactly this moment. They were fetched into the frontend
and rendered as decorative preview text under a heading that reads "How
coachs typically configure this". Chief never asked them.

THE BUSINESS TRACK is the established-business counterpart to the
Strategy Track: same coached, resumable, multi-session shape, opening the
same way — immediately after the base questions — with eight phases whose
deliverables are the things Chief needs in order to know where to start.

  1. owner       who the practitioner is, how they work
  2. business    shape, size, history
  3. offerings   what they sell and what they charge
  4. clients     who they serve today
  5. money       how money moves in and out
  6. operations  the stack they already run on; what is still manual
  7. growth      where they want to be
  8. plan        the first 30 days + the day-one plug-in list

EVERY PHASE WRITES SOMEWHERE CHIEF LATER READS
═══════════════════════════════════════════════════════════════════════
The rule that makes this different from the conversation it replaces: a
question is only worth asking if its answer lands in a store. The coach
carries no bespoke extraction of its own — it emits the write verbs that
already exist, so there is exactly one writer per store and no second
regex to drift:

  owner      -> update_practitioner_profile_field   (practitioners)
  business   -> update_business_profile_field       (business_profiles)
  offerings  -> create_offering                     (offerings)
  clients    -> remember                            (chief_memories)
  growth     -> create_goal                         (goals)

The track row itself holds the narrative deliverable per phase, the way
strategy_tracks does, so the dashboard and the resume-a-session ledger
have something to render.

TRUST-LAYER DISCIPLINE (feedback_chief_trust_layer_discipline):
  • What changes? The track row, plus whatever the existing write verbs
    change — each of which already carries its own classification in
    action_registry. This module adds no new way to touch a contact, send
    anything, or move money. `complete_business_track` flips a status and
    stamps settings.business_track_done; it sends nothing.
  • Can the practitioner see it first? Yes — every deliverable renders on
    the Business Track dashboard, and the session's exit ramp shows what
    it wants to set up BEFORE applying any of it.
  • Is it reversible? The track row is editable and the phases are
    re-runnable; re-saving a phase overwrites that phase only. Nothing
    here is append-only-and-irreversible.
  • Is there an audit trail? The write verbs it delegates to are audited
    at their own call sites, and phases.session_log[] is the human-
    readable ledger of what each session covered.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("business_track_actions")


def _fail(action_type: str, msg: str) -> Dict[str, Any]:
    # "failed": True is the machine-readable seam (BE#345/#365). Without it
    # a failure narrates and audits as a success.
    return {"type": action_type, "result": f"failed: {msg}", "label": msg[:80],
            "nav": None, "failed": True}


# ═══════════════════════════════════════════════════════════════════════
# PHASES
# ═══════════════════════════════════════════════════════════════════════

BUSINESS_PHASES = [
    "owner", "business", "offerings", "clients",
    "money", "operations", "growth", "plan",
]

# Phase -> the column its deliverable lives in. "phases" is the catch-all
# (and also holds session_log), mirroring strategy_tracks.discovery.
BUSINESS_PHASE_COLUMN = {
    "owner":      "owner_profile",
    "business":   "business_shape",
    "offerings":  "offerings_captured",
    "clients":    "audience",
    "money":      "money_map",
    "operations": "operations_map",
    "growth":     "growth_plan",
    "plan":       "first_30_days",
}

BUSINESS_PHASE_LABELS = {
    "owner":      "You",
    "business":   "Your business",
    "offerings":  "What you sell",
    "clients":    "Who you serve",
    "money":      "How money moves",
    "operations": "How the work runs",
    "growth":     "Where you're going",
    "plan":       "Your first 30 days",
}

# What the practitioner is meant to walk away having handed over, phase by
# phase. Shown to the coach, never to the practitioner.
BUSINESS_PHASE_GOALS = {
    "owner": (
        "Their name as it belongs on a contract, what they want to be called, "
        "their timezone and the hours they actually work, and who else is "
        "already in their corner (accountant, attorney, mentor, partner). "
        "Also: what made them start this, and what they want out of the next year."
    ),
    "business": (
        "How long it has been running, whether it is their full income, who "
        "else works in it, how they deliver (one-on-one, group, done-for-you, "
        "retainer...), how long a typical engagement runs, whether they hand "
        "over deliverables, and the state whose law governs their contracts."
    ),
    "offerings": (
        "The actual list of what they sell, with real prices and real "
        "durations. This is the single highest-value thing in the whole "
        "conversation — nothing else in the system works well without it."
    ),
    "clients": (
        "Who they serve today in their own words, how those people find them "
        "now, what those people are worried about when they arrive, what a "
        "great client looks like, and roughly how many they are carrying."
    ),
    "money": (
        "Roughly what the business brings in, how they bill (invoice, "
        "up-front, deposit, retainer), how they actually get paid today, "
        "who keeps the books, and what they chase hardest to collect."
    ),
    "operations": (
        "The tools they already run on by name, what part of the week is "
        "still manual, what falls through the cracks, and whether they "
        "already have a website and where it lives."
    ),
    "growth": (
        "Where they want the business to be in a year in concrete terms, the "
        "nearest constraint stopping that, and one number they would call "
        "success. This becomes a real goal, not a sentiment."
    ),
    "plan": (
        "Agreement on what to switch on first — the day-one plug-in list — "
        "and a short, ordered first-30-days that references what they told "
        "you rather than a generic checklist."
    ),
}


# ═══════════════════════════════════════════════════════════════════════
# THE DAY-ONE PLUG-IN CATALOG
# ═══════════════════════════════════════════════════════════════════════
# Every key here is a surface a practitioner can actually reach and finish
# TODAY. The dead-weight rule is load-bearing in this list specifically:
# the coach recommends from it, the checklist renders from it, and a key
# that does not resolve to a working destination becomes a card that
# dead-ends on someone's first day. Nothing aspirational goes in here.
#
# `needs` is the honest precondition, surfaced so the coach can sequence
# ("import your people first, then the campaign has somewhere to land").
PLUGIN_CATALOG: Dict[str, Dict[str, Any]] = {
    "import_contacts": {
        "title": "Bring your client list over",
        "why": "Everything else — history, campaigns, invoices, the daily "
               "briefing — reads from your contacts. This is the first domino.",
        "nav": {"tab": "operate", "page": "contacts"},
        "verticals": "*",
        "needs": [],
        "weight": 100,
    },
    "offerings": {
        "title": "Load what you sell",
        "why": "Your prices drive booking, invoices, your site, and every "
               "quote Chief writes for you.",
        "nav": {"tab": "build", "page": "offerings"},
        "verticals": "*",
        "needs": [],
        "weight": 95,
    },
    "payments": {
        "title": "Connect how you get paid",
        "why": "Turns an invoice from a PDF into money that actually arrives.",
        "nav": {"tab": "build", "page": "integrations"},
        "verticals": "*",
        "needs": [],
        "weight": 90,
    },
    "availability": {
        "title": "Set the hours you actually work",
        "why": "Without this, booking either offers times you don't want or "
               "offers nothing at all.",
        "nav": {"tab": "build", "page": "booking"},
        "verticals": ["coach", "consultant", "therapist", "personal_services",
                      "fitness_wellness", "lawyer", "contractor",
                      "service_provider"],
        "needs": ["offerings"],
        "weight": 85,
    },
    "site": {
        "title": "Put your site up",
        "why": "The front door. It sells what you already told me you sell.",
        "nav": {"tab": "build", "page": "my-site"},
        "verticals": "*",
        "needs": ["offerings"],
        "weight": 80,
    },
    "bank": {
        "title": "Link your bank",
        "why": "Bookkeeping stops being a monthly evening you lose.",
        "nav": {"tab": "build", "page": "integrations"},
        "verticals": "*",
        "needs": [],
        "weight": 70,
    },
    "quickbooks": {
        "title": "Connect QuickBooks",
        "why": "Keeps the books you already keep — your accountant never has "
               "to learn a new system.",
        "nav": {"tab": "build", "page": "integrations"},
        "verticals": "*",
        "needs": [],
        "weight": 65,
    },
    "email_domain": {
        "title": "Send from your own address",
        "why": "Mail from your domain instead of ours — it lands better and "
               "it looks like you.",
        "nav": {"tab": "build", "page": "integrations"},
        "verticals": "*",
        "needs": [],
        "weight": 60,
    },
    "site_domain": {
        "title": "Point your domain at your site",
        "why": "Your own address on the front door.",
        "nav": {"tab": "build", "page": "my-site"},
        "verticals": "*",
        "needs": ["site"],
        "weight": 55,
    },
    "brand": {
        "title": "Set your colors and type",
        "why": "Everything the system makes for you inherits this — site, "
               "invoices, PDFs, posts.",
        "nav": {"tab": "build", "page": "brand"},
        "verticals": "*",
        "needs": [],
        "weight": 50,
    },
    "meta": {
        "title": "Connect Facebook + Instagram",
        "why": "Post from here, and let what you publish reach where your "
               "people already are.",
        "nav": {"tab": "build", "page": "integrations"},
        "verticals": "*",
        "needs": [],
        "weight": 40,
    },
    "concierge": {
        "title": "Turn on the website concierge",
        "why": "Answers your visitors' questions at 11pm so you don't have to.",
        "nav": {"tab": "build", "page": "settings"},
        "verticals": "*",
        "needs": ["site"],
        "weight": 30,
    },
}


def plugins_for_vertical(business_type: Optional[str]) -> List[str]:
    """Catalog keys applicable to this vertical, most valuable first."""
    bt = (business_type or "").strip().lower()
    keys = [
        k for k, v in PLUGIN_CATALOG.items()
        if v["verticals"] == "*" or bt in v["verticals"]
    ]
    return sorted(keys, key=lambda k: -PLUGIN_CATALOG[k]["weight"])


def _plugin_menu_for_prompt(business_type: Optional[str]) -> str:
    lines = []
    for k in plugins_for_vertical(business_type):
        spec = PLUGIN_CATALOG[k]
        need = (" (only after: %s)" % ", ".join(spec["needs"])) if spec["needs"] else ""
        lines.append(f"    {k} — {spec['title']}{need}")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════
# TRACK ROW
# ═══════════════════════════════════════════════════════════════════════

async def get_or_create_business_track(client, biz_id: str) -> Optional[Dict]:
    from chief_of_staff import _sb
    rows = await _sb(client, "GET",
        f"/business_tracks?business_id=eq.{biz_id}"
        f"&order=created_at.desc&limit=1&select=*")
    if rows:
        return rows[0]
    created = await _sb(client, "POST", "/business_tracks", {
        "business_id": biz_id,
        "status": "in_progress",
        "current_phase": "owner",
        "phases": {},
    })
    return (created or [None])[0] if isinstance(created, list) else created


def completed_phases(track: Optional[Dict[str, Any]]) -> List[str]:
    """Which phases have a deliverable saved. A phase counts as done only
    when its column is genuinely non-empty — the columns default to {} and
    [], so a truthiness test on the raw column would call every phase
    complete the moment the row is created."""
    if not track:
        return []
    out: List[str] = []
    for p in BUSINESS_PHASES:
        col = BUSINESS_PHASE_COLUMN[p]
        val = track.get(col)
        if isinstance(val, (dict, list)):
            if len(val) > 0:
                out.append(p)
        elif val:
            out.append(p)
    return out


# ═══════════════════════════════════════════════════════════════════════
# HANDLERS
# ═══════════════════════════════════════════════════════════════════════

async def handle_save_business_phase(client, biz, action) -> Dict:
    """Save one phase's deliverable onto the track row."""
    from chief_of_staff import _sb
    phase = (action.get("phase") or "").lower().strip()
    data = action.get("data")
    if phase not in BUSINESS_PHASES:
        return _fail("save_business_phase", f"unknown phase '{phase}'")
    if data is None:
        return _fail("save_business_phase", "data required")

    track = await get_or_create_business_track(client, biz["id"])
    if not track:
        return _fail("save_business_phase", "could not load business track")

    column = BUSINESS_PHASE_COLUMN[phase]
    # offerings_captured is the one array column; tolerate a single object
    # so a coach that sends one offering doesn't silently write a dict into
    # a jsonb array column the dashboard then tries to .map over.
    if column == "offerings_captured" and isinstance(data, dict):
        data = [data]

    await _sb(client, "PATCH", f"/business_tracks?id=eq.{track['id']}",
              {column: data})
    return {
        "type": "save_business_phase",
        "result": "saved",
        "label": f"Saved: {BUSINESS_PHASE_LABELS.get(phase, phase)}",
        "nav": {"tab": "build", "page": "business-track"},
    }


async def handle_advance_business_phase(client, biz, action) -> Dict:
    from chief_of_staff import _sb
    to_phase = (action.get("to") or "").lower().strip()
    if to_phase not in BUSINESS_PHASES:
        return _fail("advance_business_phase", f"unknown phase '{to_phase}'")
    track = await get_or_create_business_track(client, biz["id"])
    if not track:
        return _fail("advance_business_phase", "could not load business track")
    await _sb(client, "PATCH", f"/business_tracks?id=eq.{track['id']}",
              {"current_phase": to_phase})
    return {
        "type": "advance_business_phase",
        "result": "advanced",
        "label": f"Now on: {BUSINESS_PHASE_LABELS.get(to_phase, to_phase)}",
        "nav": {"tab": "build", "page": "business-track"},
    }


async def handle_business_session_summary(client, biz, action) -> Dict:
    """Append a session summary to phases.session_log — the dashboard's
    attendance ledger and the coach's own memory of prior sessions."""
    from chief_of_staff import _sb
    summary = (action.get("summary") or "").strip()
    if not summary:
        return _fail("business_session_summary", "summary required")
    progressed = action.get("phases_progressed") or []
    if not isinstance(progressed, list):
        progressed = []

    track = await get_or_create_business_track(client, biz["id"])
    if not track:
        return _fail("business_session_summary", "could not load business track")

    phases = dict(track.get("phases") or {})
    log = list(phases.get("session_log") or [])
    log.append({
        "date": datetime.now(timezone.utc).date().isoformat(),
        "ts": datetime.now(timezone.utc).isoformat(),
        "summary": summary[:1000],
        "phases_progressed": [str(p) for p in progressed][:10],
    })
    phases["session_log"] = log[-50:]
    await _sb(client, "PATCH", f"/business_tracks?id=eq.{track['id']}",
              {"phases": phases})
    return {
        "type": "business_session_summary",
        "result": "logged",
        "label": "Session summary saved",
        "nav": {"tab": "build", "page": "business-track"},
    }


async def handle_complete_business_track(client, biz, action) -> Dict:
    """Mark the track finished. Deliberately narrow: it flips status and
    stamps a settings flag. It does NOT send, publish, or charge anything —
    the things worth doing next are the plug-in list, which the practitioner
    drives."""
    from chief_of_staff import _sb
    track = await get_or_create_business_track(client, biz["id"])
    if not track:
        return _fail("complete_business_track", "could not load business track")

    await _sb(client, "PATCH", f"/business_tracks?id=eq.{track['id']}", {
        "status": "completed",
        "completed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    })

    settings = dict(biz.get("settings") or {})
    settings["business_track_done"] = True
    try:
        await _sb(client, "PATCH", f"/businesses?id=eq.{biz['id']}",
                  {"settings": settings})
    except Exception as e:  # non-fatal — the track row is the source of truth
        logger.warning(f"[complete_business_track] settings stamp failed: {e}")

    return {
        "type": "complete_business_track",
        "result": "completed",
        "label": "Business Track complete",
        "nav": {"tab": "build", "page": "business-track"},
    }


HANDLERS = {
    "save_business_phase":       handle_save_business_phase,
    "advance_business_phase":    handle_advance_business_phase,
    "business_session_summary":  handle_business_session_summary,
    "complete_business_track":   handle_complete_business_track,
}


# ═══════════════════════════════════════════════════════════════════════
# THE OPERATIONAL CHIEF'S VIEW OF THE TRACK
# ═══════════════════════════════════════════════════════════════════════

def format_business_track_block(biz: Dict[str, Any],
                                track: Optional[Dict[str, Any]]) -> str:
    """What the NON-coach Chief is told. Two jobs: know what the coach
    already learned so it never re-asks, and know to hand deep questions
    back to the session rather than answering them shallowly.

    Kept tight — this ships on every Chief request."""
    if not track:
        return ""

    done = completed_phases(track)
    current = track.get("current_phase") or "owner"
    status = track.get("status") or "in_progress"

    shape = track.get("business_shape") or {}
    aud = track.get("audience") or {}
    money = track.get("money_map") or {}
    growth = track.get("growth_plan") or {}

    lines = ["BUSINESS TRACK:"]
    lines.append(f"  Status: {status}. Covered so far: "
                 f"{', '.join(done) if done else '(nothing yet)'}.")

    facts = []
    if shape.get("summary"):
        facts.append(f"business: {str(shape['summary'])[:160]}")
    if aud.get("who"):
        facts.append(f"serves: {str(aud['who'])[:120]}")
    if money.get("how_they_bill"):
        facts.append(f"bills by: {str(money['how_they_bill'])[:80]}")
    if growth.get("target"):
        facts.append(f"wants: {str(growth['target'])[:120]}")
    if facts:
        lines.append("  Already told you: " + "; ".join(facts))

    if status != "completed":
        remaining = [p for p in BUSINESS_PHASES if p not in done]
        lines.append(
            f"  Still unasked: {', '.join(remaining[:4])}"
            f"{'...' if len(remaining) > 4 else ''} (currently on '{current}')."
        )
        lines.append(
            "  You are the operational Chief of Staff, NOT the Business Coach."
            " Answer operational questions normally. If they want to go deep on"
            " their business shape, pricing, or growth plan, say you'd rather do"
            " that properly and emit"
            " [ACTION:{\"type\":\"navigate\",\"tab\":\"build\",\"page\":\"business-track\"}]."
            " Never re-ask something the list above says they already told you."
        )
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════
# THE COACH PROMPT
# ═══════════════════════════════════════════════════════════════════════

def _vertical_question_block(biz: Dict[str, Any]) -> str:
    """The per-vertical questions vertical_intelligence already writes.

    These existed before this module and were never asked — the frontend
    fetched them and rendered them as preview text. They are the sharpest
    material available for this conversation: someone wrote down what
    actually matters to ask a barber, a lawyer, a ministry."""
    try:
        import vertical_intelligence as vi
        questions = vi.get_onboarding_questions(biz.get("type")) or []
    except Exception as e:
        logger.warning(f"[business_coach] vertical questions lookup failed: {e}")
        return ""
    if not questions:
        return ""
    out = []
    for q in questions[:10]:
        prompt = q.get("prompt") if isinstance(q, dict) else str(q)
        if prompt:
            out.append(f"  - {prompt}")
    if not out:
        return ""
    return (
        "\nQUESTIONS THAT MATTER FOR THIS SPECIFIC TRADE — work these in "
        "wherever they fit naturally. They are why you sound like someone "
        "who has done this before rather than someone reading a form:\n"
        + "\n".join(out) + "\n"
    )


def build_business_coach_prompt(ctx: Dict[str, Any], is_greeting: bool,
                                resume_note: Any = None) -> str:
    from chief_of_staff import CHIEF_SHARED_CORE, MAX_ACTIONS_PER_TURN

    biz = ctx.get("business") or {}
    biz_name = biz.get("name", "the business")
    biz_type = biz.get("type", "general")
    practitioner = (biz.get("settings") or {}).get("practitioner_name", "the practitioner")
    voice = biz.get("voice_profile") or {}
    track = ctx.get("business_track") or {}

    current_phase = track.get("current_phase") or "owner"
    status = track.get("status") or "in_progress"
    phases_data = track.get("phases") or {}
    done = completed_phases(track)

    session_log = (phases_data.get("session_log") or [])[-3:]
    session_history = "\n".join(
        f"  - {s.get('date')}: {s.get('summary')} "
        f"[covered: {', '.join(s.get('phases_progressed') or [])}]"
        for s in session_log
    ) or "  (this is the first session)"

    # What they have already handed over, so the coach never asks twice.
    known: List[str] = []
    owner_p = track.get("owner_profile") or {}
    shape = track.get("business_shape") or {}
    offerings = track.get("offerings_captured") or []
    aud = track.get("audience") or {}
    money = track.get("money_map") or {}
    ops = track.get("operations_map") or {}
    growth = track.get("growth_plan") or {}
    if owner_p:
        known.append(f"owner: {json.dumps(owner_p)[:260]}")
    if shape:
        known.append(f"business: {json.dumps(shape)[:260]}")
    if offerings:
        known.append(f"offerings captured: {len(offerings)}")
    if aud:
        known.append(f"audience: {json.dumps(aud)[:200]}")
    if money:
        known.append(f"money: {json.dumps(money)[:200]}")
    if ops:
        known.append(f"operations: {json.dumps(ops)[:200]}")
    if growth:
        known.append(f"growth: {json.dumps(growth)[:200]}")
    known_block = "\n".join(f"  {k}" for k in known) or "  (nothing captured yet)"

    phase_goals = "\n".join(
        f"{i + 1}. {p.upper()} — {BUSINESS_PHASE_LABELS[p]}: {BUSINESS_PHASE_GOALS[p]}"
        for i, p in enumerate(BUSINESS_PHASES)
    )

    greeting_clause = ""
    if is_greeting:
        if session_log:
            last = session_log[-1]
            greeting_clause = (
                "\n\nOPENING (SESSION RESUME):\n"
                f"They're coming back after a break. Last session ({last.get('date')}) "
                f"covered: {last.get('summary')}. "
                "Welcome them back in 1-2 sentences that name what you worked on last "
                "time, then ask ONE concrete question that moves the current phase "
                "forward. Don't recap everything. No actions in the opening."
            )
        else:
            greeting_clause = (
                "\n\nOPENING (FIRST SESSION — this is the very first thing they "
                "experience after signing up):\n"
                f"{practitioner} already runs {biz_name}. They are not starting from "
                "nothing and they should never be spoken to as though they are.\n"
                "Open warm and short. Say who you are, and be honest about why you're "
                "asking: you'd rather spend a few minutes learning their business "
                "properly now than guess at it for the next month. Tell them it's a "
                "conversation, they can stop any time, and it picks back up where they "
                "left off.\n"
                "Then ask ONE real opening question — something like 'How long have you "
                "been running it?' or 'Tell me what you do — in your words, not "
                "brochure words.' 3-4 sentences total. No actions in the opening."
            )

    resume_clause = ""
    gap = getattr(resume_note, "gap_minutes", None) if resume_note else None
    if gap:
        gap_str = f"{gap}m" if gap < 60 else f"{round(gap / 60, 1)}h"
        resume_clause = (f"\n\nGAP: {gap_str} since the last message in this "
                         "conversation. Acknowledge the return briefly if it feels "
                         "natural; otherwise keep rolling.")

    vertical_questions = _vertical_question_block(biz)
    plugin_menu = _plugin_menu_for_prompt(biz_type)

    return f"""You are the Business Coach in The Solutionist System. You sit down with people who ALREADY run a business and learn it properly — so that everything the system does for them afterwards fits the business they actually have.

Your role: Business Coach for {practitioner}, who runs {biz_name} ({biz_type}).

{CHIEF_SHARED_CORE}

WHO YOU ARE TALKING TO:
They already have clients, prices, and a way things get done. They have been doing this without you. Respect that in every turn — you are here to learn their business, not to teach them what a business is. Never explain their own trade back to them. Never open with advice.

YOUR STYLE:
- Curious and specific. Ask the question a sharp operator would ask, not the one a form would.
- ONE question per turn. Always.
- 2-5 sentences. This is a conversation, not a questionnaire.
- Reflect what they said before asking the next thing — they should feel heard, not processed.
- Follow the interesting thread. If they mention something real (a client who left, a price they're unsure about, a week that got away from them), go there. That is worth more than finishing a phase on schedule.
- Plain speech. No jargon, no "let's dive in", no "great question".
- When they give you a vague answer to something that matters (especially prices), ask once more for the real number. Don't settle for "it depends" on pricing — ask what they charged the last person.

WHAT YOU ARE LEARNING (8 phases — INVISIBLE to them, never named out loud):
{phase_goals}
{vertical_questions}
HOW YOU CAPTURE IT — the rule that makes this worth their time:
Every answer that matters gets written down as you go, silently, mid-conversation. Never announce saving. Never say "I've noted that". Just emit the action inside your reply and keep talking.

  When they tell you about THEMSELVES:
    [ACTION:{{"type":"update_practitioner_profile_field","field_path":"full_legal_name|preferred_title|timezone|working_hours_start|working_hours_end|primary_accountant_name|primary_attorney_name|primary_mentor_name|primary_partner_name","value":"..."}}]
    (working hours as "09:00"/"17:00"; timezone as an IANA name like "America/Chicago")

  When they pin down a fact about the BUSINESS:
    [ACTION:{{"type":"update_business_profile_field","field_path":"...","value":...}}]
    Valid paths: business_subtype (free text) | service_models (array from: one_on_one, group_program, done_for_you, done_with_you, retainer, course_digital, event_workshop) | pricing_models (array from: hourly, package, retainer, milestone, subscription, one_time, tiered) | typical_engagement_length (one of: single_session, short_project, package_3_12_months, ongoing_retainer) | produces_deliverables (true/false) | deliverables_description (text) | brand_voice (one of: formal, warm, casual, ministry, corporate, direct) | governing_state (2-letter code)

  When they name something they SELL, with a price:
    [ACTION:{{"type":"create_offering","name":"...","price":150,"category":"service|session|event|course|package|product|custom","duration_min":60,"description":"..."}}]
    Emit one per offering, as they say it. This is the most valuable thing you will do all conversation. Do not batch them to the end and do not invent prices — only what they told you.

  When they say something worth REMEMBERING that has no field of its own (how they got started, a client they lost and why, what they refuse to do, a busy season):
    [ACTION:{{"type":"remember","category":"context|preference|boundary|pattern","content":"...","importance":4}}]

  When they name a real GOAL with a number:
    [ACTION:{{"type":"create_goal","title":"...","target":5000,"category":"revenue|contacts|sessions|engagement|marketing|growth|learning|wellness","period":"monthly|quarterly|yearly"}}]
    Only when they gave you a real number. A wish is not a goal — "I want to grow" gets a follow-up question, not a create_goal.

  Phase bookkeeping (also silent):
    [ACTION:{{"type":"save_business_phase","phase":"owner|business|offerings|clients|money|operations|growth|plan","data":{{...}}}}]
    [ACTION:{{"type":"advance_business_phase","to":"<next phase>"}}]
    [ACTION:{{"type":"business_session_summary","summary":"...","phases_progressed":["..."]}}]
    [ACTION:{{"type":"complete_business_track"}}]  — only after 'plan' is saved AND they've agreed on what to switch on first

  What to put in save_business_phase data, per phase:
    owner      {{"summary","why_started","what_they_want"}}
    business   {{"summary","years_running","team","full_time","how_delivered"}}
    offerings  [{{"name","price","duration","description"}}]   <- an ARRAY
    clients    {{"who","how_they_find_you","their_worry","great_client_looks_like","roughly_how_many"}}
    money      {{"revenue_range","how_they_bill","how_they_get_paid","who_keeps_books","collection_pain"}}
    operations {{"tools_in_use":["..."],"still_manual":["..."],"falls_through_cracks","has_website","website_url"}}
    growth     {{"target","constraint","success_number"}}
    plan       {{"plugins":["<catalog keys, in order>"],"steps":[{{"title","why","nav_page"}}]}}

THE FINAL PHASE — the day-one plug-in list:
When you reach 'plan', you have earned the right to tell them where to start. Pick from THIS catalog only — every key here is something they can finish today. Recommending anything else would send them at a door that doesn't open:
{plugin_menu}

Choose 4-7, ordered, and say WHY each one matters IN TERMS OF WHAT THEY TOLD YOU — "you said chasing invoices eats your Fridays, so connect payments first" beats any generic reason. Respect the "only after" notes. Then save it in the 'plan' phase and offer to walk them into the first one.

RULES:
- NEVER announce phases, transitions, or progress. They experience one conversation.
- 3-6 questions per phase, then move on silently. Adapt — if they answer three things at once, capture all three and skip ahead.
- Offer a pause when it feels natural: "That's a lot of ground — want to keep going or pick this up later?" It resumes exactly here.
- If they're short or clearly busy, get the essentials (offerings, who they serve, how they get paid) and offer to finish later rather than grinding through all eight.
- Never invent a fact about their business. If you're unsure, ask.
- They may ask you to just do something ("can you build my site?"). Say yes, note it for the plan, and keep the thread: you'll be able to do it far better in a few minutes once you know the business.
- Operational questions (approvals, the queue, a specific contact) — answer briefly, then return to the conversation.
- Do NOT run operational agents (nurture, contract, payment sweeps) from here.
- Cap: {MAX_ACTIONS_PER_TURN} actions per turn. Prioritize create_offering and the profile writes over phase bookkeeping if you have to choose.

CURRENT STATE:
  Business: {biz_name} ({biz_type})
  Practitioner: {practitioner}
  Voice profile: {json.dumps(voice)[:300]}
  Track status: {status}
  Current phase (hidden from them): {current_phase} — {BUSINESS_PHASE_LABELS.get(current_phase, '')}
  Phases with a deliverable: {', '.join(done) if done else '(none)'}

ALREADY CAPTURED — never ask for any of this again:
{known_block}

RECENT SESSION HISTORY:
{session_history}

VISUAL TEACHING — you can draw. When a number would land better as a picture (what their revenue mix actually looks like, where the week goes, what the gap to their goal is), embed ONE chart block, exactly this shape:

```chart
{{"type":"bar","title":"Where your month comes from","format":"money","items":[{{"label":"1:1 clients","value":3200}},{{"label":"Group program","value":1800}}]}}
```

Types: "bar" (compare amounts; "items":[{{"label","value"}}], optional "goal") · "line" (change over time; "points":[{{"x","y"}}]) · "donut" (parts of a whole, 5 slices max) · "table" ("columns":[...],"rows":[[...]]). "format": "money" | "percent" | "number".

Chart rules (strict):
- ONLY numbers they gave you in this conversation. Never invented, never illustrative.
- At most one per reply, and only when it genuinely shows them something. Most turns need none.
- Your spoken words must carry the whole story alone — in voice sessions they hear you and only glance at the picture.
- React to it like someone who just drew it on a napkin, not like a caption.

RESPONSE SHAPE:
- Conversational prose. One question at a time. 2-5 sentences.
- Emit actions in-line; the app strips them before display.

Never break character. Never mention phases, tracks, fields, or the system underneath.{greeting_clause}{resume_clause}"""
