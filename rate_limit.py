"""
rate_limit.py — tiny in-process sliding-window limiter.

Beta-readiness audit (AI-spend + adversarial): the paid AI endpoints had
no per-caller throttle, so one tester (or a leaked URL) could fire
thousands of requests. This is the same fixed-window pattern already
used by the intake + booking endpoints, factored out so chat, voice,
and the proxy can share it.

Keyed by caller identity — user id when the endpoint is authenticated,
else the client IP (from X-Forwarded-For behind Railway's proxy). Fully
in-process (single Railway instance); fail-OPEN by design — a limiter
glitch must never block a legitimate call.

Defaults are generous (meant to stop abuse/runaways, not normal use) and
env-overridable per bucket.
"""

import os
import time
from typing import Dict, Optional, Tuple

# bucket name → (max_requests, window_seconds), env-overridable.
_LIMITS: Dict[str, Tuple[int, int]] = {
    "platform_chief_creative": (12, 3600),
    "platform_marketing_week": (6, 3600),
    # A business owner asking Chief for this week's suggested post (marketing
    # suite B8). The model runs on the worker, at most once a day per business
    # (business_marketing_planner checks that); this only stops a tap loop.
    "business_marketing_engine": (int(os.environ.get("RL_BUSINESS_MARKETING_ENGINE_PER_HOUR", "6")), 3600),
    "business_learning": (int(os.environ.get("RL_BUSINESS_LEARNING_PER_HOUR", "24")), 3600),
    "chief":  (int(os.environ.get("RL_CHIEF_PER_MIN", "30")), 60),
    "voice":  (int(os.environ.get("RL_VOICE_PER_MIN", "40")), 60),
    "proxy":  (int(os.environ.get("RL_PROXY_PER_MIN", "60")), 60),
    # Interview v3 (B3) — the follow-up probe's per-business hourly budget.
    "interview_probe": (int(os.environ.get("RL_INTERVIEW_PROBE_PER_HOUR", "6")), 3600),
    # A PDF bank statement read by Claude (bank_statements.py), per business:
    # a year of monthly statements is twelve; this stops an upload loop.
    "bank_statement_read": (int(os.environ.get("RL_BANK_STATEMENT_READ_PER_HOUR", "30")), 3600),
    # A photo of a paper count sheet read by Claude (giving_sheets.py), per
    # church: a Sunday has a sheet or two; this stops a retake loop.
    "giving_sheet_read": (int(os.environ.get("RL_GIVING_SHEET_READ_PER_HOUR", "20")), 3600),
    # The agent-facing MCP surface. Tighter than the practitioner buckets
    # and checked with allow_strict() — an external agent that loops is a
    # different problem from a person clicking twice.
    "mcp": (int(os.environ.get("RL_MCP_PER_MIN", "20")), 60),
    # The agent-readable public site API (agent_site.py): anonymous,
    # cheap JSON, no model call — but checked with allow_strict(), because
    # the caller is a customer's agent and a looping one is a scripted
    # sweep of every business we host. Per IP.
    "agent_site": (int(os.environ.get("RL_AGENT_SITE_PER_MIN", "60")), 60),
    # ── Launch hardening (2026-09-04) ─────────────────────────────────
    # The OAuth front door to the MCP surface. These three were called
    # with allow_strict() but never registered, so each silently fell to
    # _DEFAULT (60/min) — a consent form that can be brute-forced 60
    # times a minute is not what the module docstring promised.
    "mcp_oauth_register": (int(os.environ.get("RL_MCP_OAUTH_REGISTER_PER_HOUR", "10")), 3600),
    "mcp_oauth_consent": (int(os.environ.get("RL_MCP_OAUTH_CONSENT_PER_MIN", "6")), 60),
    "mcp_oauth_token": (int(os.environ.get("RL_MCP_OAUTH_TOKEN_PER_MIN", "30")), 60),
    # Anonymous Stripe Checkout session for a booking. Its docstring
    # claimed "handled by the existing wizard rate-limit middleware";
    # there is no such middleware. Per IP, per hour, strict.
    "booking_checkout": (int(os.environ.get("RL_BOOKING_CHECKOUT_PER_HOUR", "20")), 3600),
    # The public waitlist: an anonymous insert per novel email, with no
    # limiter at all until now.
    "waitlist": (int(os.environ.get("RL_WAITLIST_PER_HOUR", "10")), 3600),
    # The public document check (document_ledger): anonymous, a hash in and
    # facts out, no model call. Strict and per IP, so it cannot be used to
    # sweep the ledger for hashes.
    "document_check": (int(os.environ.get("RL_DOCUMENT_CHECK_PER_MIN", "20")), 60),
    # Web-form SMS consent: writes the A2P audit trail, and was limited
    # only per PHONE, which the caller chooses. Per IP too, strict.
    "sms_opt_in": (int(os.environ.get("RL_SMS_OPT_IN_PER_HOUR", "10")), 3600),
    # A church's /daily sign-up (devotional_daily.py): anonymous, and a
    # sign-up can send a welcome text, so strict and per IP like the above.
    "daily_join": (int(os.environ.get("RL_DAILY_JOIN_PER_HOUR", "10")), 3600),
    # The no-card trial's phone check (no_card_trial.py). Sending a code
    # costs a text and is the classic SMS-pumping target, so few per
    # business per hour; checking a code is the brute-force target for a
    # six-digit number, so few per business per ten minutes. Strict.
    "trial_phone_send": (int(os.environ.get("RL_TRIAL_PHONE_SEND_PER_HOUR", "3")), 3600),
    "trial_phone_check": (int(os.environ.get("RL_TRIAL_PHONE_CHECK_PER_10MIN", "8")), 600),
    # The traffic beacon: keyed only on a caller-supplied session id,
    # which the anon-spend audit's own words call decorative. A per-IP
    # courtesy bucket beside it — fail-open, because a tracking endpoint
    # must never surface an error to a visitor's browser.
    "track": (int(os.environ.get("RL_TRACK_PER_MIN", "240")), 60),
    # Report-Only CSP violations (platform_watchdog.csp_report): anonymous,
    # sent by browsers, one log line per new kind. Per IP, fail-open — a
    # preview iframe can raise dozens on one render, and past the budget the
    # rest are simply not counted.
    "csp_report": (int(os.environ.get("RL_CSP_REPORT_PER_HOUR", "300")), 3600),
    # The booking widget's three anonymous routes (2026-09-04): they had
    # their own 10/hour dict in booking_widget_router; they ride the
    # strict, shared path now with the same numbers.
    "booking_config_anon": (int(os.environ.get("RL_BOOKING_ANON_PER_HOUR", "10")), 3600),
    "booking_book_anon": (int(os.environ.get("RL_BOOKING_ANON_PER_HOUR", "10")), 3600),
    "booking_fresh_link": (int(os.environ.get("RL_BOOKING_ANON_PER_HOUR", "10")), 3600),
    # Digital-delivery downloads — anon, token-gated; generous enough
    # for a buyer grabbing a multi-item order, tight enough to stop a
    # scripted token search.
    "store_download": (int(os.environ.get("RL_STORE_DOWNLOAD_PER_MIN", "30")), 60),
    # Auditor ledger links — anon, token-gated, checked with
    # allow_strict(). A reviewer reads a page and maybe exports twice;
    # anything faster is a scripted search for a valid token.
    "auditor_link": (int(os.environ.get("RL_AUDITOR_LINK_PER_MIN", "20")), 60),
    # Per-LINK budget, so one leaked credential cannot flood one
    # tenant's append-only ledger with view rows.
    "auditor_link_jti": (int(os.environ.get("RL_AUDITOR_LINK_PER_LINK", "60")), 3600),
    # The ledger navigator: an LLM call plus a ledger row per request.
    "ledger_nav": (int(os.environ.get("RL_LEDGER_NAV_PER_MIN", "12")), 60),
    # /pulse: anonymous, and the most expensive single request on the
    # platform — a Sonnet call at 4k tokens with five forced web
    # searches. It is called once when the app opens in the morning, so
    # a real caller needs a handful an hour and a script needs none.
    # Per HOUR rather than per minute, because the thing that matters is
    # the daily total. spend_guard's per-tenant ceiling does not cover
    # this one: an anonymous caller has no business to bill, so the spend
    # counts platform-only — and an unrated loop here still takes AI
    # offline for every tenant at once.
    "pulse": (int(os.environ.get("RL_PULSE_PER_HOUR", "10")), 3600),
    # The federal grants lane. Costs us nothing — Grants.gov asks for no
    # key — so this is not a ration and is generous enough that a
    # practitioner refining a search never meets it. It exists because a
    # retry loop on our side would hammer a public service in our name,
    # and because the free lane is the one most likely to be called on a
    # schedule later. Per business, per minute.
    "grants_search": (int(os.environ.get("RL_GRANTS_SEARCH_PER_MIN", "30")), 60),
    # Member sign-in (member_portal.py). Asking for a code mails a real
    # person, so both the sender (per IP) and the inbox (per church +
    # address) are capped; checking a code is capped per IP on top of the
    # 5 tries each code allows.
    # Per network (a church's own Wi-Fi is one address on a Sunday, so it
    # is generous), then per address: a one-minute cooldown and a daily
    # ceiling, rather than an hourly cap a stranger could spend to keep a
    # member from ever receiving a code. Wrong codes have their own daily
    # cap per address in member_portal (MAX_FAILED_PER_DAY).
    "member_code_ip": (int(os.environ.get("RL_MEMBER_CODE_PER_HOUR", "40")), 3600),
    "member_code_email_minute": (1, 60),
    "member_code_email_day": (int(os.environ.get("RL_MEMBER_CODE_EMAIL_PER_DAY", "12")), 86400),
    "member_verify": (int(os.environ.get("RL_MEMBER_VERIFY_PER_10MIN", "60")), 600),
    # A signed-in member's writes (RSVP, prayer, details), per person.
    "member_action": (int(os.environ.get("RL_MEMBER_ACTION_PER_HOUR", "30")), 3600),
    # Draft with Chief in the Text room (text_room.draft_reply), per person
    # on the team: each is a model call, and a tap loop shouldn't be.
    "text_draft": (int(os.environ.get("RL_TEXT_DRAFT_PER_HOUR", "60")), 3600),
    # Ask the church (member_asks.py), per member, on top of member_action:
    # a room, help, a visit, a life event or a pledge reaches the office, so
    # one member can't flood it. An hour's budget and a day's.
    "member_ask": (int(os.environ.get("RL_MEMBER_ASK_PER_HOUR", "6")), 3600),
    "member_ask_day": (int(os.environ.get("RL_MEMBER_ASK_PER_DAY", "15")), 86400),
    # The member app's Bible, per member: highlights, notes and saved verses
    # (a chapter can be many taps), and word searches (each reads a whole
    # translation).
    "bible_mark": (int(os.environ.get("RL_BIBLE_MARK_PER_10MIN", "120")), 600),
    "bible_search": (int(os.environ.get("RL_BIBLE_SEARCH_PER_MIN", "20")), 60),
    # Listen on a devotional's day (devotional_voice.py), per member: a day
    # is read aloud once and kept, so this only bounds taps.
    "devotional_listen": (int(os.environ.get("RL_DEVOTIONAL_LISTEN_PER_10MIN", "30")), 600),
    # Joining a free class from its public page (academy_join.py) mails a
    # class link, so the same shape as member sign-in: per network
    # (generous: a church lobby is one address), then per business +
    # address a one-minute cooldown and a daily ceiling.
    "class_join_ip": (int(os.environ.get("RL_CLASS_JOIN_PER_HOUR", "60")), 3600),
    "class_join_email_minute": (1, 60),
    "class_join_email_day": (int(os.environ.get("RL_CLASS_JOIN_EMAIL_PER_DAY", "6")), 86400),
    # Check-in stations (kids_station.py), all strict: pairing codes per
    # network, PIN tries per station, and mobile-number lookups per
    # self check-in kiosk — so neither a code nor a family can be guessed.
    "station_pair": (int(os.environ.get("RL_STATION_PAIR_PER_10MIN", "10")), 600),
    # Church event sign-ups (church_event_signups.py), strict: starting a
    # sign-up opens a Stripe page and can hold places, so per network a
    # family's few tries and no more; reading an offer or a receipt is looser.
    "event_signup": (int(os.environ.get("RL_EVENT_SIGNUP_PER_10MIN", "12")), 600),
    "event_signup_read": (int(os.environ.get("RL_EVENT_SIGNUP_READ_PER_10MIN", "60")), 600),
    "station_pin": (int(os.environ.get("RL_STATION_PIN_PER_15MIN", "6")), 900),
    "station_self_find": (int(os.environ.get("RL_STATION_SELF_PER_10MIN", "40")), 600),
    # Dev Desk relay: strict shared windows; screen cadence also uses a DB lock.
    "dev_fleet": (60, 60),
    "dev_screen": (1, 1.5),
    "dev_alert_push": (20, 3600),
    "dev_alert_source": (6, 600),
    "dev_kai_notify": (6, 3600),
    "dev_alert_digest": (1, 900),
    "dev_alert_email": (1, 1800),
    "dev_watch_run": (6, 60),
    # Chief's notes from a group leader to people who've been missing
    # (group_care), per leader. Strict.
    "care_notes": (int(os.environ.get("RL_CARE_NOTES_PER_HOUR", "6")), 3600),
    # Photos in a group's chat (chat_photos), per member: each one is
    # looked at by a model before it's kept. Strict.
    "chat_photos": (int(os.environ.get("RL_CHAT_PHOTOS_PER_HOUR", "20")), 3600),
    # Live chat, per member; "I'm here" rides member_action.
    "live_chat": (int(os.environ.get("RL_LIVE_CHAT_PER_MIN", "8")), 60),
    # Hearts in the live room, per member: a phone sends its taps in
    # batches of up to 30 at most every second or so.
    "live_heart": (int(os.environ.get("RL_LIVE_HEART_PER_MIN", "40")), 60),
    # Homework handed in as a file, by the class link (academy_work.py):
    # per link (hashed), so a whole class on one church Wi-Fi isn't one
    # budget; and a wide per-IP ceiling beside it. Opening a file is a
    # signed link, per link or per teacher. Strict.
    "academy_work_upload": (int(os.environ.get("RL_ACADEMY_WORK_UPLOAD_PER_HOUR", "30")), 3600),
    "academy_work_upload_ip": (int(os.environ.get("RL_ACADEMY_WORK_UPLOAD_IP_PER_HOUR", "300")), 3600),
    "academy_work_file": (int(os.environ.get("RL_ACADEMY_WORK_FILE_PER_10MIN", "60")), 600),
    # Chief sums up a live class's answers (academy_class_sum), per class
    # night: 8 every ten minutes, counting only asks that reach the model.
    "class_sum": (int(os.environ.get("RL_CLASS_SUM_PER_10MIN", "8")), 600),
    # A board's draft minutes emailed to its members (church_board.py), per
    # meeting: a resend or two is normal, a loop of them isn't.
    "church_board_send": (int(os.environ.get("RL_CHURCH_BOARD_SEND_PER_HOUR", "6")), 3600),
    # The Monday leaders note (church_leaders_note.py), per church: it goes
    # once a week anyway; this only stops a tap loop of tries that fail.
    "church_leaders_note_send": (int(os.environ.get("RL_CHURCH_LEADERS_NOTE_SEND_PER_HOUR", "4")), 3600),
}
_DEFAULT = (60, 60)

# (bucket, key) → {"start": epoch, "count": n}
_buckets: Dict[Tuple[str, str], Dict[str, float]] = {}


def trusted_client_ip(request) -> str:
    """The LAST X-Forwarded-For hop, not the first.

    client_ip() takes the first hop, which is whatever the caller typed
    into the header — fine for a courtesy limit on a practitioner
    screen, useless as a defence. Railway APPENDS the real peer, so the
    last entry is the one the platform observed. Use this on any
    unauthenticated surface where the limiter is a control rather than
    a courtesy.
    """
    try:
        xff = (request.headers.get("x-forwarded-for") or "").strip()
        if xff:
            hops = [h.strip() for h in xff.split(",") if h.strip()]
            if hops:
                return hops[-1]
        return (getattr(getattr(request, "client", None), "host", "") or "unknown")
    except Exception:
        return "unknown"


def client_ip(request) -> str:
    """Best-effort caller IP. Railway sits behind a proxy, so prefer the
    first X-Forwarded-For hop; fall back to the socket peer."""
    try:
        xff = request.headers.get("x-forwarded-for") or ""
        if xff:
            return xff.split(",")[0].strip()
        return (request.client.host if request.client else "unknown")
    except Exception:
        return "unknown"


def _check(bucket: str, key: str, max_requests: Optional[int] = None) -> bool:
    """The window arithmetic, with no error handling. RAISES on trouble —
    the two public wrappers below decide what a failure means, and they
    disagree on purpose."""
    max_req, window = _LIMITS.get(bucket, _DEFAULT)
    if max_requests is not None:
        max_req = max(1, int(max_requests))
    now = time.time()
    bkey = (bucket, key or "unknown")
    b = _buckets.get(bkey)
    if not b or now - b["start"] > window:
        _buckets[bkey] = {"start": now, "count": 1}
        return True
    if b["count"] >= max_req:
        return False
    b["count"] += 1
    return True


def allow(bucket: str, key: str) -> bool:
    """True if this (bucket, key) is under its limit for the current
    window. Fail-OPEN on any error."""
    try:
        return _check(bucket, key)
    except Exception:
        return True


# ─── The shared window (2026-09-04) ──────────────────────────────────
#
# Every bucket above lives in THIS process. The platform runs N web
# replicas (scheduler_lock exists for that), so every anonymous budget
# was really N times the number in _LIMITS. The strict buckets — the
# ones that are a control, not a courtesy — now also take from a window
# in Postgres (supabase/APPLY-2026-09-04-rate-windows.sql, rate_take()),
# which every replica shares.
#
# Order matters and is deliberate: the in-process check runs FIRST. It
# is free, and under a flood it answers "no" before a single database
# round-trip is spent — the shared window exists to stop the sum across
# replicas, not to absorb one replica's flood. Only a call the local
# window admits goes on to the shared one.
#
# Fail-SOFT to local, not open: if the RPC is missing (migration not
# applied yet) or the database blips, allow_strict() returns the local
# answer it already computed, with a warning. That is a limiter still,
# just per process again — the posture the service had until today.
# RATE_LIMIT_SHARED=off pins that behaviour deliberately.

_SHARED_RPC = "/rpc/rate_take"
# Flips False after the first refused RPC so a not-yet-applied migration
# costs one warning, not one failed round-trip per anonymous request.
# Re-armed by the purge tick, so an applied migration is picked up
# within the hour without a restart.
_shared_ok = True


def shared_enabled() -> bool:
    return (os.environ.get("RATE_LIMIT_SHARED") or "on").strip().lower() != "off"


def _shared_take(bucket: str, key: str, max_requests: Optional[int] = None) -> Optional[bool]:
    """True/False from the shared window, or None when it could not
    decide (disabled, unavailable, unexpected shape)."""
    global _shared_ok
    if not shared_enabled() or not _shared_ok:
        return None
    max_req, window = _LIMITS.get(bucket, _DEFAULT)
    if max_requests is not None:
        max_req = max(1, int(max_requests))
    try:
        import sb_clients
        out = sb_clients.sb_post_as_service(_SHARED_RPC, {
            "p_bucket": str(bucket)[:80], "p_key": str(key or "unknown")[:200],
            "p_max": int(max_req), "p_window_sec": int(window)})
    except Exception as e:
        _shared_ok = False
        _log_shared_down(e)
        return None
    if isinstance(out, bool):
        return out
    if isinstance(out, list) and out and isinstance(out[0], bool):
        return out[0]
    # sb_post_as_service returns None on any 4xx/5xx (a missing function
    # is a 404) — treat exactly like a transport failure.
    _shared_ok = False
    _log_shared_down(f"unexpected reply {out!r}")
    return None


def _log_shared_down(reason) -> None:
    import logging
    logging.getLogger("rate_limit").warning(
        "[rate_limit] shared window unavailable (%s) — strict buckets are "
        "per-process until the next purge tick re-arms it. Apply "
        "APPLY-2026-09-04-rate-windows.sql if this persists.", reason)


def rearm_shared() -> None:
    """Try the shared window again. Called by the purge tick."""
    global _shared_ok
    _shared_ok = True


def purge_shared(older_than_sec: int = 86400) -> int:
    """Delete rows nobody has touched in a day. Called hourly on the
    scheduler leader; re-arms the shared path first so a migration
    applied after boot is picked up. Never raises."""
    rearm_shared()
    if not shared_enabled():
        return 0
    try:
        import sb_clients
        out = sb_clients.sb_post_as_service("/rpc/rate_purge",
                                            {"p_older_than_sec": int(older_than_sec)})
        return int(out) if isinstance(out, int) else 0
    except Exception as e:
        _log_shared_down(e)
        return 0


def allow_strict(bucket: str, key: str, *, max_requests: Optional[int] = None) -> bool:
    """`allow`, but FAIL-CLOSED — and, since 2026-09-04, shared across
    replicas.

    Every bucket above fails open, which is right for a practitioner: a
    limiter glitch must never stop someone running their own business.
    It is wrong for an external agent. On that surface the caller is not
    a person waiting on a screen, the credential may be stolen, and
    "the limiter broke so everything was permitted" is the failure you
    least want. Same window arithmetic, opposite answer when it breaks.

    Kept separate from `allow` rather than adding a flag, so that no
    existing caller can acquire this behaviour by accident.

    The local window decides first (free; absorbs a flood). A call it
    admits is then counted in the shared window, whose answer wins. If
    the shared window cannot decide, the local answer stands.
    """
    try:
        local = _check(bucket, key) if max_requests is None else _check(bucket, key, max_requests)
        if not local:
            return False
        shared = _shared_take(bucket, key) if max_requests is None else _shared_take(bucket, key, max_requests)
        return local if shared is None else shared
    except Exception:
        return False


def retry_after(bucket: str) -> int:
    """Seconds a caller should wait — the window length."""
    return int(_LIMITS.get(bucket, _DEFAULT)[1])
