"""
vertical_autopilot.py — the one overnight job each vertical would miss.

THE GAP THIS CLOSES
  chief_scheduler can already run ANY Chief verb on a recurrence. The engine
  was never the problem. What was missing is that a brand-new business got
  nothing scheduled: the practitioner had to know the feature existed, know
  which verb was worth repeating, and ask for it by name.

  The vertical readiness audit scored S12 (Autopilot) PARTIAL for five of
  seven verticals for exactly that reason, and the audit question is the
  right one — "what's the one overnight job this vertical would miss if it
  stopped?" A barber's answer is the rebooking cadence. A lawyer's is the
  deadline sweep. Neither shipped.

WHAT A DEFAULT JOB IS ALLOWED TO BE
  Every job here runs UNATTENDED and on a schedule the practitioner did not
  explicitly ask for at the moment it fires. That is a meaningful amount of
  trust, so the bar is deliberately narrow:

    1. The verb must be autonomy-eligible per action_registry — class A,
       non-bulk. Enforced at import time by _assert_safe(), so a job that
       violates it cannot even be defined; the module fails to load.
    2. Nothing may leave the system. Every job below produces DRAFTS in the
       approval queue or a briefing the practitioner reads. Sending stays a
       human act, which is the whole point of the class C wall.
    3. The practitioner can see it (`list_scheduled`) and kill it
       (`cancel_scheduled`) from day one. No hidden automation.

  The registry is the authority, not this file. If a verb is reclassified to
  C tomorrow, the import guard fails here and this module stops shipping that
  job — rather than quietly continuing to run it.

WHY run_agent AND NOT draft_nurture
  draft_nurture requires a contact_id and fails without one, so as a standing
  weekly job it would fail every single week. run_agent in batch mode takes
  only an agent name and lets the agent find its own targets. The distinction
  cost a bug that would have looked like "autopilot is broken" rather than
  "autopilot was configured wrong".

SEEDING
  seed_defaults() is idempotent on (business_id, job key) so re-running
  onboarding, or a practitioner re-triggering the seed, cannot stack
  duplicate schedules. It is called from business_profile_router's
  seed-from-onboarding hook, alongside the module blueprint walk, and is
  non-fatal there for the same reason that one is.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("vertical_autopilot")

# The label prefix every seeded row carries. It is how seeding stays
# idempotent without a schema change: we look for an existing queued row
# whose label starts with this marker plus the job key.
SEED_MARKER = "[auto]"


def _job(key: str, label: str, agent: str, recurrence: str, hour: int,
         why: str) -> Dict[str, Any]:
    """One default job. `hour` is UTC — the scheduler compares against UTC
    and businesses.settings has no reliable per-business timezone at
    onboarding time. 11:00 UTC is early morning across US timezones, which
    is when a practitioner wants yesterday's drafts waiting."""
    return {
        "key": key,
        "label": label,
        "action": {"type": "run_agent", "agent": agent},
        "recurrence": recurrence,
        "hour_utc": hour,
        "why": why,
    }


# ─────────────────────────────────────────────────────────────────────
# The jobs. One per vertical minimum — the thing that vertical would miss.
# ─────────────────────────────────────────────────────────────────────

DEFAULT_AUTOPILOT: Dict[str, List[Dict[str, Any]]] = {

    # Rebooking is the barber's entire business model. A client who does not
    # rebook is not a lost sale, it is a lost RELATIONSHIP, and the industry
    # answer is a standing cadence. This is the single most load-bearing
    # default in the file.
    "personal_services": [
        _job("rebooking", "Rebooking check-ins", "nurture", "weekly", 11,
             "Drafts a check-in for clients who haven't rebooked. The chair "
             "only earns when it's full."),
        # NOT seeded: a no-show follow-up. The obvious second job here, and
        # it was written before being checked — session_agent's no-show pass
        # reads /sessions?status=eq.no_show, but this vertical books through
        # the booking_calendar archetype, which does not write /sessions
        # rows. The job would have found nothing every weekday forever and
        # looked like working autopilot.
        #
        # Real no-show protection for a chair business is a no-show FEE, not
        # a follow-up email, and that needs the money primitives that do not
        # exist yet. It belongs to that arc, not this one.
    ],

    # Deadlines in a legal practice are not reminders, they are obligations.
    # Weekdays rather than weekly: a Friday-to-Monday gap is where a filing
    # date goes missing.
    "lawyer": [
        _job("deadlines", "Matter and deadline sweep", "briefing", "weekdays", 11,
             "Surfaces matters, approaching deadlines, trust and retainer "
             "balances, and unbilled time every working morning."),
    ],

    # Accountability between sessions IS the coaching product. A client who
    # drifts for three weeks does not come back for the fourth.
    "coach": [
        _job("accountability", "Client accountability check-ins", "nurture",
             "weekly", 11,
             "Drafts check-ins for clients who have gone quiet between "
             "sessions."),
    ],

    "consultant": [
        _job("engagement_review", "Engagement and milestone review", "briefing",
             "weekly", 11,
             "Weekly read on active engagements, milestone dates, retainer "
             "balances, unbilled time and what is slipping."),
    ],

    # A first-time attendee who is not contacted within a week usually does
    # not return. The follow-up window is the whole ballgame.
    "ministry": [
        _job("new_attendee", "New attendee follow-up", "nurture", "weekly", 12,
             "Drafts a warm follow-up for people who visited recently."),
    ],

    # A grant deadline is an obligation, not a reminder — the same
    # reasoning the lawyer's sweep is built on, and weekdays for the same
    # reason: a Friday-to-Monday gap is where a submission date goes
    # missing. It matters after the award too, because federal reporting
    # runs on its own clocks (interim commonly within 30 days of a period
    # end, final within 120) and a missed report is how the next grant is
    # lost.
    #
    # The briefing agent reads pipelines through
    # briefing_verticals._scan_pipelines, which only walks modules whose
    # archetype is work_pipeline — so the Grants module had to become a
    # real pipeline (FE#521) before this job could see anything at all.
    "nonprofit": [
        _job("grant_deadlines", "Grant and deadline sweep", "briefing",
             "weekdays", 11,
             "Surfaces grants approaching their submission or report date, "
             "and applications that have gone past one."),
        _job("donor_followup", "Donor follow-up", "nurture", "weekly", 12,
             "Drafts thank-yous and re-engagement for lapsing donors."),
    ],

    "creative": [
        _job("project_review", "Project and deliverable review", "briefing",
             "weekly", 11,
             "Weekly read on live projects, due dates approaching and work "
             "that has stalled."),
    ],

    "course_creator": [
        _job("student_checkin", "Student check-ins", "nurture", "weekly", 11,
             "Drafts nudges for students who have stalled in the curriculum."),
    ],

    "financial_educator": [
        _job("program_review", "Program review", "briefing", "weekly", 11,
             "Weekly read on client engagement plus program balances running "
             "low or expiring."),
    ],

    "fitness_wellness": [
        _job("client_checkin", "Client check-ins", "nurture", "weekly", 11,
             "Drafts check-ins for clients who have missed sessions."),
    ],

    # An estimate that never gets followed up is the trade's classic leak:
    # the work was quoted, the customer went quiet, and nobody called back.
    "contractor": [
        _job("estimate_followup", "Estimate follow-ups", "nurture", "weekly", 12,
             "Drafts a follow-up for customers who got a quote and haven't "
             "answered. A bid with no follow-up is a job given away."),
    ],

    # A practice runs on the schedule holding. Note this is the BRIEFING and
    # not a nurture run: drafting outreach to therapy clients on a timer is
    # exactly the kind of automation this vertical should not have.
    "therapist": [
        _job("practice_review", "Practice review", "briefing", "weekly", 12,
             "Weekly read on the schedule, cancellations and unpaid "
             "invoices. Admin only — never client outreach."),
    ],

    # A store's leaks are physical: an order nobody packed, a product that
    # quietly hit zero, a return sitting undecided. All three are visible in
    # the data and invisible in the day.
    "ecommerce": [
        _job("store_review", "Store review", "briefing", "weekly", 11,
             "Weekly read on orders still unshipped, products at or below "
             "their reorder point, and returns waiting on a decision."),
    ],

    # Churn is decided weeks before the renewal reveals it, so the job that
    # earns its place looks at accounts that have gone quiet — not at the
    # invoice, which is the last place it shows.
    "saas": [
        _job("account_review", "Account review", "briefing", "weekly", 11,
             "Weekly read on renewals coming up, accounts that have gone "
             "quiet, and subscriptions past due."),
    ],

    # The two deliberately-generic verticals still get the briefing — a
    # generic voice is not a reason to ship no autopilot at all.
    "service_provider": [
        _job("weekly_briefing", "Weekly briefing", "briefing", "weekly", 11,
             "A weekly read on the business."),
    ],
    "custom": [
        _job("weekly_briefing", "Weekly briefing", "briefing", "weekly", 11,
             "A weekly read on the business."),
    ],
}


# ─────────────────────────────────────────────────────────────────────
# Import-time safety guard — the trust layer, not a copy of it.
# ─────────────────────────────────────────────────────────────────────

def _assert_safe() -> None:
    """Every default job must be a verb Chief may run unprompted.

    Deliberately raises at import. A default job that sends email or moves
    money is not a bug to be logged and skipped — it is one that must stop
    the process, because the alternative is discovering it from a customer.
    """
    try:
        import action_registry
    except Exception:                                    # pragma: no cover
        # action_registry is the authority; if it cannot be imported we are
        # in a context (a bare script, a partial deploy) where no seeding
        # will happen anyway. Refusing to import here would be worse.
        logger.warning("action_registry unavailable — autopilot guard skipped")
        return

    for vertical, jobs in DEFAULT_AUTOPILOT.items():
        for job in jobs:
            verb = job["action"]["type"]
            if not action_registry.is_autonomy_eligible(verb):
                raise RuntimeError(
                    f"vertical_autopilot: {vertical}/{job['key']} schedules "
                    f"'{verb}', which is not autonomy-eligible in "
                    f"action_registry (class "
                    f"{action_registry.reversibility(verb)!r}, bulk="
                    f"{action_registry.is_bulk(verb)}). A default job runs "
                    f"unattended — it may only ever be a class A, non-bulk "
                    f"verb that produces drafts.")


_assert_safe()


# ─────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────

def defaults_for(business_type: Optional[str]) -> List[Dict[str, Any]]:
    """The default jobs for a vertical, resolved through the alias table so
    'church' and 'ministry' get the same schedule. Unknown types fall back
    to the generic briefing rather than to nothing."""
    try:
        import vertical_registry
        key = vertical_registry.resolve(business_type)
    except Exception:
        key = "custom"
    return list(DEFAULT_AUTOPILOT.get(key) or DEFAULT_AUTOPILOT["custom"])


def _first_run_at(hour_utc: int, recurrence: str) -> datetime:
    """The next occurrence of `hour_utc`, never in the past. A job seeded at
    09:00 for an 11:00 slot runs the same morning; one seeded at 14:00 waits
    for tomorrow rather than firing instantly at seed time."""
    now = datetime.now(timezone.utc)
    run = now.replace(hour=hour_utc, minute=0, second=0, microsecond=0)
    if run <= now:
        run += timedelta(days=1)
    if recurrence == "weekdays":
        while run.weekday() >= 5:
            run += timedelta(days=1)
    return run


def seed_defaults(business_id: str, business_type: Optional[str],
                  owner_id: Optional[str] = None) -> Dict[str, Any]:
    """Queue this vertical's default jobs. Idempotent per (business, key).

    Returns a summary rather than raising — the caller is an onboarding hook
    where a failed autopilot seed must never block the business from being
    created.
    """
    import sb_clients

    jobs = defaults_for(business_type)
    created: List[str] = []
    skipped: List[str] = []

    try:
        existing_rows = sb_clients.sb_get_as_service(
            f"/chief_scheduled_actions?business_id=eq.{business_id}"
            "&status=eq.queued&select=label&limit=200") or []
    except Exception as e:
        logger.warning(f"[autopilot] could not read existing schedule: {e}")
        existing_rows = []
    existing = {str(r.get("label") or "") for r in existing_rows}

    for job in jobs:
        marker = f"{SEED_MARKER}{job['key']}"
        # Idempotency: the marker is embedded in the label, so a second seed
        # finds its own previous row and leaves it alone.
        if any(lbl.startswith(marker) for lbl in existing):
            skipped.append(job["key"])
            continue

        row = {
            "business_id": business_id,
            "owner_id": owner_id,
            "label": f"{marker} {job['label']}",
            "action": job["action"],
            "run_at": _first_run_at(job["hour_utc"], job["recurrence"]).isoformat(),
            "recurrence": job["recurrence"],
            "status": "queued",
        }
        try:
            sb_clients.sb_post_as_service("/chief_scheduled_actions", row)
            created.append(job["key"])
        except Exception as e:
            logger.warning(f"[autopilot] seed failed for {job['key']}: {e}")

    logger.info(f"[autopilot] {business_id}: created={created} skipped={skipped}")
    return {"ok": True, "created": created, "skipped": skipped,
            "vertical_jobs": [j["key"] for j in jobs]}


def describe(business_type: Optional[str]) -> str:
    """One line per default job — for Chief prompts and the settings UI, so
    the practitioner can find out what is running without reading the DB."""
    jobs = defaults_for(business_type)
    if not jobs:
        return "No default autopilot for this business type."
    return "\n".join(f"- {j['label']} ({j['recurrence']}): {j['why']}"
                     for j in jobs)
