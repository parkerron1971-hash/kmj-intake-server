"""
sms_usage.py — what texting costs, and how many texts a business sent.

Every outbound text costs the platform money at Twilio. Until 2026-11-03
none of it was recorded: no api_usage row, no line in the Costs view, and
no way to say how many texts a church sent this month, which is the number
a church plan's text allowance (500 / 1,500 / 3,000 / 8,000) is counted in.

ONE ROW PER TEXT, IN api_usage
------------------------------
twilio_sms.send_sms, the one Twilio send, writes one row after Twilio hands
back a message id; a send that raises writes nothing. The TwiML auto-reply
on the inbound webhook writes one too (Twilio bills it like any other
outbound text). The row:

    endpoint       "sms"              ENDPOINT, what every reader filters on
    model          "twilio-sms"
    provider       "twilio"
    input_tokens   billable segments  the unit Twilio bills (the TTS rows use
                                      this column for characters the same way)
    output_tokens  0
    units          0                  a text never costs Chief credits
    cost_cents     segments x pricing_config.sms_segment_cost_cents()
    task_type      "sms_<kind>"       message, automated, reply, pickup_code,
                                      signin_code, trial_check, test
    response_id    the Twilio message id
    business_id    the business whose line sent it; None for the platform's
                   own texts (the trial phone check, the operator test send)

WHY api_usage, AND WHAT KEEPS A TEXT OUT OF THE AI CONTROLS
-----------------------------------------------------------
api_usage is what the Costs view and margin's COGS read, so a text's cost
lands beside every other cost. But api_usage also feeds controls that are
about AI, and a text must move none of them: a 2,000-text announcement is
about $25, which is the default per-business daily AI ceiling.

  * spend_guard, the daily AI circuit breaker: reads NOT_SMS and skips SMS
    rows in memory as well.
  * usage_metering (Chief credits, the plan allowance, the low-credit
    nudge): reads NOT_SMS; the rows carry units=0 and weight_for prices the
    endpoint at 0 besides.
  * billing_limits.chief_messages_this_month, launch_access's platform
    meter, ops_desk's "AI spend against revenue" and chief_quality's spend
    all read NOT_SMS.

The filter sits in the QUERY, not only in memory, because PostgREST hands
back at most 1,000 rows a read: unfiltered, a busy day of texts would crowd
the AI rows out of the window those readers see.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional
from urllib.parse import quote

logger = logging.getLogger("sms_usage")

ENDPOINT = "sms"
MODEL = "twilio-sms"
PROVIDER = "twilio"

# The PostgREST filter every AI reader of api_usage adds. endpoint is NOT
# NULL on api_usage, so `neq` keeps every non-text row.
NOT_SMS = f"endpoint=neq.{ENDPOINT}"


def is_sms_row(row: Optional[Dict[str, Any]]) -> bool:
    return (row or {}).get("endpoint") == ENDPOINT


def cost_cents(segments: int) -> float:
    """What this many segments cost us, in cents."""
    import pricing_config
    return round(max(int(segments or 0), 0) * pricing_config.sms_segment_cost_cents(), 4)


def _kind(kind: Optional[str]) -> str:
    k = re.sub(r"[^a-z_]", "", str(kind or "").lower())[:40]
    return k or "message"


def usage_row(*, business_id: Optional[str], text: str, sid: Optional[str] = None,
              kind: str = "message") -> Dict[str, Any]:
    """The logger kwargs for one text. Pure. `text` is the body as it
    left (after gsm_safe), since that is what Twilio counts segments on."""
    import twilio_sms
    segments = twilio_sms.segments(text)
    return {
        "endpoint": ENDPOINT,
        "model": MODEL,
        "input_tokens": segments,
        "output_tokens": 0,
        "business_id": str(business_id) if business_id else None,
        "task_type": f"sms_{_kind(kind)}",
        "units": 0,
        "cost_cents_override": cost_cents(segments),
        "provider": PROVIDER,
        "response_id": str(sid)[:120] if sid else None,
        # A text sent inside a Chief turn is not one of the turn's model
        # calls: "" keeps the ambient turn id and lane off the row, so a
        # turn's cost stays the cost of its AI.
        "turn_id": "",
        "lane": "",
    }


def record_send(business_id: Optional[str], text: str, *, sid: Optional[str] = None,
                kind: str = "message") -> None:
    """Write the row for one text Twilio accepted. Blocking (call it where
    the send itself runs, off the event loop). Never raises: losing a cost
    row must never fail a text that already went."""
    try:
        import api_usage_logger
        import billing_context
        row = usage_row(business_id=business_id, text=text, sid=sid, kind=kind)
        # The row names its business itself. Without this the logger would
        # fill a None from the request's tenant, and the platform's own
        # texts would land on whichever business the request was for.
        with billing_context.unattributed():
            api_usage_logger.log_api_usage_sync(**row)
    except Exception as e:  # noqa: BLE001
        print(f"[sms_usage] text not recorded ({kind}): {type(e).__name__}: {e}", flush=True)


async def record_send_async(business_id: Optional[str], text: str, *, sid: Optional[str] = None,
                            kind: str = "message") -> None:
    """record_send for async code (the inbound webhook's TwiML reply)."""
    try:
        import api_usage_logger
        import billing_context
        row = usage_row(business_id=business_id, text=text, sid=sid, kind=kind)
        with billing_context.unattributed():
            await api_usage_logger.log_api_usage(**row)
    except Exception as e:  # noqa: BLE001
        print(f"[sms_usage] text not recorded ({kind}): {type(e).__name__}: {e}", flush=True)


# ─── Counting ─────────────────────────────────────────────────────────

def month_start_iso(now: Optional[datetime] = None) -> str:
    """First instant of this calendar month in UTC, in the Z form a
    PostgREST query string needs (a bare +00:00 decodes as a space)."""
    n = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    return n.replace(day=1, hour=0, minute=0, second=0, microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _business_path(business_id: str, now: Optional[datetime], select: str) -> str:
    return (f"/api_usage?business_id=eq.{quote(str(business_id), safe='')}"
            f"&endpoint=eq.{ENDPOINT}&created_at=gte.{month_start_iso(now)}&select={select}")


def texts_this_month(business_id: str, *, now: Optional[datetime] = None) -> Optional[int]:
    """Texts this business has sent since the 1st (UTC). Texts, not
    segments: the plan allowance is counted in texts. Counted by the
    database (HEAD, count=exact), so no 1,000-row cap applies. Served by
    idx_api_usage_business_created (business_id, created_at).

    None when the count can't be read. A caller holding an allowance must
    read None as "unknown", never as 0: a failed read is not an empty
    month. Blocking."""
    if not business_id:
        return None
    try:
        import sb_clients
        return sb_clients.sb_count_as_service(_business_path(business_id, now, "id"))
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[sms_usage] texts_this_month failed: {type(e).__name__}")
        return None


def segments_this_month(business_id: str, *, now: Optional[datetime] = None) -> Optional[int]:
    """Billable segments this business has sent since the 1st (UTC): what
    Twilio bills, where texts_this_month is what the allowance counts.
    Reads every row (paged); None when any page fails. Blocking."""
    if not business_id:
        return None
    try:
        import sb_clients
        rows = sb_clients.sb_get_all_as_service(
            _business_path(business_id, now, "id,input_tokens"), key="id", strict=True)
        return sum(int(r.get("input_tokens") or 0) for r in rows or [])
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[sms_usage] segments_this_month failed: {type(e).__name__}")
        return None


def cost_since(days: int = 30, *, now: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
    """Platform-wide texting over the last `days`: {texts, segments,
    cost_cents}, for the owner's Costs view. None when any page fails, so
    the view never shows a short read as the real number. Blocking."""
    start = ((now or datetime.now(timezone.utc)) - timedelta(days=days)).astimezone(timezone.utc)
    try:
        import sb_clients
        rows = sb_clients.sb_get_all_as_service(
            f"/api_usage?endpoint=eq.{ENDPOINT}&created_at=gte.{start.strftime('%Y-%m-%dT%H:%M:%SZ')}"
            f"&select=id,input_tokens,cost_cents", key="id", strict=True) or []
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[sms_usage] cost_since failed: {type(e).__name__}")
        return None
    return {
        "texts": len(rows),
        "segments": sum(int(r.get("input_tokens") or 0) for r in rows),
        "cost_cents": round(sum(float(r.get("cost_cents") or 0) for r in rows), 2),
    }
