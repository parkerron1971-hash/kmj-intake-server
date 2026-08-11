"""
booking_confirmation_emails.py — Phase D.4 customer confirmation emails.

Fired (best-effort, async) after a successful book / book-anon insert.
Loads the booking + business + offering, generates an .ics attachment,
and ships the email via the existing Resend integration.

Discipline:
  - Send is fully wrapped in try/except. The booking is the load-bearing
    entity; email is opportunistic. Errors log + return; never raise.
  - .ics generation is a pure function (build_ics). Unit-tested on
    fixtures — see __tests__/test_booking_confirmation_emails.py.
  - All times stored / transmitted in UTC. The body shows the customer's
    local time formatted via Intl-style UTC offsets (computed
    server-side from the business timezone).
"""
from __future__ import annotations

import base64
import html
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import sb_clients

logger = logging.getLogger("booking_confirmation_emails")


# ─────────────────────────────────────────────────────────────────────
# .ics generation
# ─────────────────────────────────────────────────────────────────────

# Per RFC 5545 §3.3.11, these characters must be escaped in TEXT values.
_ICS_ESCAPE = [
    ("\\", "\\\\"),
    ("\n", "\\n"),
    ("\r", ""),
    (",", "\\,"),
    (";", "\\;"),
]


def _ics_escape(value: Optional[str]) -> str:
    """Escape a string for safe use inside an iCalendar TEXT value."""
    if value is None:
        return ""
    s = str(value)
    for needle, repl in _ICS_ESCAPE:
        s = s.replace(needle, repl)
    return s


def _ics_fold(line: str) -> str:
    """Fold an iCalendar content line to 75 octets per RFC 5545 §3.1.
    Continuation lines begin with a single space."""
    # Octets, not characters — encode to UTF-8 and chunk by byte length.
    raw = line.encode("utf-8")
    if len(raw) <= 75:
        return line
    chunks = []
    i = 0
    while i < len(raw):
        chunk = raw[i : i + 75]
        chunks.append(chunk.decode("utf-8", errors="ignore"))
        i += 75
    return "\r\n ".join(chunks)


def _ics_dt(dt: datetime) -> str:
    """Format a datetime as iCalendar UTC: 20260612T123000Z."""
    if dt.tzinfo is None:
        # Assume UTC if no timezone — submission path always stores UTC.
        dt = dt.replace(tzinfo=timezone.utc)
    dt_utc = dt.astimezone(timezone.utc)
    return dt_utc.strftime("%Y%m%dT%H%M%SZ")


def build_ics(
    *,
    booking_id: str,
    appointment_at_utc: str,
    duration_min: int,
    business_name: str,
    service_name: Optional[str],
    description: Optional[str],
    location: Optional[str],
    organizer_email: Optional[str],
    attendee_email: Optional[str],
    attendee_name: Optional[str],
) -> bytes:
    """Generate a valid iCalendar VEVENT for one booking.

    Returns UTF-8-encoded bytes ready to attach to an email. Per RFC
    5545, lines are CRLF-terminated and folded at 75 octets.
    """
    start = _parse_iso(appointment_at_utc)
    if start is None:
        # Defensive fallback — use now+1h so the file at least parses.
        start = datetime.now(timezone.utc) + timedelta(hours=1)
    end = start + timedelta(minutes=max(int(duration_min or 0), 0))
    now = datetime.now(timezone.utc)

    summary = _ics_escape(
        f"{service_name} at {business_name}"
        if service_name
        else f"Appointment with {business_name}"
    )
    desc = _ics_escape((description or "").strip())
    loc = _ics_escape((location or "").strip())

    # UID must be globally unique; booking id is already a UUID.
    uid = f"{booking_id}@mysolutionist.app"

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Solutionist//Booking//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTAMP:{_ics_dt(now)}",
        f"DTSTART:{_ics_dt(start)}",
        f"DTEND:{_ics_dt(end)}",
        f"SUMMARY:{summary}",
    ]
    if desc:
        lines.append(f"DESCRIPTION:{desc}")
    if loc:
        lines.append(f"LOCATION:{loc}")
    if organizer_email:
        org_cn = _ics_escape(business_name)
        lines.append(f"ORGANIZER;CN={org_cn}:mailto:{organizer_email}")
    if attendee_email:
        att_cn = _ics_escape(attendee_name or attendee_email)
        lines.append(
            f"ATTENDEE;CN={att_cn};RSVP=TRUE;PARTSTAT=NEEDS-ACTION:"
            f"mailto:{attendee_email}"
        )
    lines.append("STATUS:CONFIRMED")
    lines.append("TRANSP:OPAQUE")
    lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")

    folded = [_ics_fold(l) for l in lines]
    body = "\r\n".join(folded) + "\r\n"
    return body.encode("utf-8")


def _parse_iso(s: str) -> Optional[datetime]:
    """Best-effort ISO-8601 parser tolerant of trailing 'Z'."""
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s)
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────────────
# Email body
# ─────────────────────────────────────────────────────────────────────


def _fmt_local(dt_utc_iso: str, tz_label: Optional[str]) -> str:
    """Render the appointment time for human reading. We don't have
    zoneinfo guaranteed in the email rendering context, so format UTC
    + the practitioner's tz label and let recipients reason about it.
    The .ics file carries the canonical UTC value for calendar apps."""
    dt = _parse_iso(dt_utc_iso)
    if not dt:
        return dt_utc_iso
    # Human-readable UTC stamp; calendar apps convert via the .ics.
    fmt = dt.strftime("%A, %B %-d at %-I:%M %p UTC") if os.name != "nt" \
        else dt.strftime("%A, %B %d at %I:%M %p UTC")
    if tz_label:
        return f"{fmt} ({tz_label} business time)"
    return fmt


def _fmt_when(
    dt_utc_iso: str,
    tz_label: Optional[str],
    arrival_window_min: Optional[int] = None,
) -> str:
    """The email's when-line. Plain bookings keep the exact-time render
    (_fmt_local, unchanged). WINDOWED bookings (contractor scheduling —
    data.arrival_window_min_at_booking) say the DATE and the ARRIVAL
    WINDOW, never a precise time: the vertical_intelligence contractor
    tone note is explicit that committing to an exact time is the thing
    a trade must not do. Format mirrors _fmt_local's UTC + business-tz
    label convention."""
    if not arrival_window_min or arrival_window_min <= 0:
        return _fmt_local(dt_utc_iso, tz_label)
    start = _parse_iso(dt_utc_iso)
    if not start:
        return dt_utc_iso
    end = start + timedelta(minutes=int(arrival_window_min))
    if os.name != "nt":
        day = start.strftime("%A, %B %-d")
        s_t = start.strftime("%-I:%M %p")
        e_t = end.strftime("%-I:%M %p")
    else:
        day = start.strftime("%A, %B %d")
        s_t = start.strftime("%I:%M %p")
        e_t = end.strftime("%I:%M %p")
    line = f"{day} — arrival between {s_t} and {e_t} UTC"
    if tz_label:
        return f"{line} ({tz_label} business time)"
    return line


def _build_html_body(
    *,
    business_name: str,
    customer_name: str,
    service_name: Optional[str],
    appointment_at_iso: str,
    duration_min: int,
    price: Optional[float],
    tz_label: Optional[str],
    hosted_page_url: Optional[str],
    cancellation_policy: str,
    pay_now_url: Optional[str] = None,
    business_type: Optional[str] = None,
    arrival_window_min: Optional[int] = None,
) -> str:
    name = html.escape(customer_name or "there")
    biz = html.escape(business_name)
    svc = html.escape(service_name or "your appointment")

    # VABI v1 — vertical-aware intro line. Lawyers get a confidentiality
    # nudge; coaches an outcome-focused nudge; barbers stay plain.
    intro_extra = _vertical_intro_for_email(business_type)
    # Windowed bookings say the date + arrival window; plain bookings
    # keep the exact-time line (see _fmt_when).
    when = html.escape(_fmt_when(appointment_at_iso, tz_label, arrival_window_min))
    price_line = ""
    if price is not None:
        try:
            price_line = (
                f'<p style="margin:6px 0;color:#475569;font-size:14px">'
                f'Price: <strong>${float(price):.2f}</strong> · '
                f'{int(duration_min) if duration_min else "—"} minutes</p>'
            )
        except Exception:
            pass

    hosted_link = ""
    if hosted_page_url:
        safe_url = html.escape(hosted_page_url)
        hosted_link = (
            f'<p style="margin:18px 0 8px;font-size:13px;color:#475569">'
            f'Need to reschedule? Visit '
            f'<a href="{safe_url}" style="color:#4f46e5">{safe_url}</a></p>'
        )

    pay_now_block = ""
    if pay_now_url:
        safe_pay = html.escape(pay_now_url)
        pay_now_block = (
            f'<p style="margin:16px 0 8px;text-align:center">'
            f'<a href="{safe_pay}" '
            f'style="display:inline-block;background:#4f46e5;color:white;'
            f'padding:12px 24px;border-radius:8px;font-weight:600;'
            f'text-decoration:none">Pay now (optional)</a>'
            f'</p>'
            f'<p style="margin:0 0 16px;font-size:11.5px;color:#94a3b8;'
            f'text-align:center">Or pay at your appointment — either works.</p>'
        )

    policy = html.escape(cancellation_policy or "")

    return f"""<!doctype html>
<html><body style="font-family:system-ui,sans-serif;color:#0f172a;
background:#f8fafc;margin:0;padding:24px;">
  <div style="max-width:560px;margin:0 auto;background:white;
              padding:28px;border-radius:12px;
              border:1px solid #e2e8f0;">
    <h1 style="margin:0 0 16px;font-size:22px;color:#0f172a;">
      You're booked
    </h1>
    <p style="margin:0 0 16px;font-size:15px;line-height:1.5">
      Hi {name}, your appointment with <strong>{biz}</strong> is confirmed.
      {intro_extra}
    </p>

    <div style="background:#f1f5f9;border-radius:8px;padding:14px 16px;
                margin:18px 0;">
      <p style="margin:0 0 6px;font-weight:600">{svc}</p>
      <p style="margin:6px 0;color:#475569;font-size:14px">{when}</p>
      {price_line}
    </div>

    {pay_now_block}

    <p style="margin:18px 0 6px;font-size:13px;color:#475569">
      The attached .ics file will add this to your calendar.
    </p>
    {hosted_link}

    <p style="margin:24px 0 6px;font-size:12px;color:#94a3b8;
              font-weight:600;letter-spacing:0.4px;text-transform:uppercase">
      Cancellation policy
    </p>
    <p style="margin:4px 0;font-size:12.5px;color:#64748b;line-height:1.5">
      {policy}
    </p>

    <p style="margin:24px 0 0;font-size:11px;color:#94a3b8;text-align:center">
      Powered by Solutionist
    </p>
  </div>
</body></html>
"""


DEFAULT_CANCELLATION_POLICY = (
    "We appreciate at least 24 hours' notice for cancellations or "
    "rescheduling, so we can offer the slot to someone else."
)


def _vertical_subject(business_type: Optional[str], business_name: str) -> str:
    """Phase C.1.4 — vertical-aware email subject. Lawyer customers
    see 'Your consultation with… is confirmed'; coach customers see
    'Your session with…'; generic businesses see 'Your appointment…'."""
    from vertical_terminology import get_term
    term = get_term(business_type, "appointment").lower()
    return f"Your {term} with {business_name} is confirmed"


def _vertical_intro_for_email(business_type: Optional[str]) -> str:
    """VABI v1 — short vertical-aware nudge that follows the main
    confirmation sentence. Lean on the booking_confirmation tone note
    from vertical_intelligence; render one sentence max so subjects
    + tone shifts don't bloat email length."""
    try:
        from vertical_intelligence import get_email_voice
        v = get_email_voice(business_type, "booking_confirmation") or {}
        note = (v.get("tone_note") or "").strip()
    except Exception:
        note = ""
    bt = (business_type or "").lower().strip()
    # Curated per-vertical sentence — terse, factual, no boilerplate.
    if bt == "lawyer":
        return (
            "Please bring any documents relevant to the matter; "
            "our conversation is privileged and confidential."
        )
    if bt == "coach":
        return "Come ready with a goal or intention you want to work on today."
    if bt == "consultant":
        return "If we shared a brief or pre-read, take a moment to review before we meet."
    if bt == "creative":
        return "If you have references, examples, or a brief to share, bring those along."
    if bt == "course_creator":
        return "Looking forward to seeing you — bring your questions."
    if bt == "fitness_wellness":
        return "Wear comfortable clothing and bring water; we'll meet you where you are."
    if bt == "ministry":
        return "We're glad you're coming. Childcare and dietary options are available — reply if you need anything."
    if bt == "financial_educator":
        return (
            "This is education, not personalized financial advice. "
            "Bring questions about concepts and frameworks."
        )
    if bt == "personal_services":
        return "Plan to arrive a few minutes early; cancellations are appreciated 24 hours in advance."
    if bt == "contractor":
        # Dispatch language — date + arrival window, and what the customer
        # does before the crew arrives (vertical_intelligence tone note).
        return (
            "We'll arrive within the window above on the date shown. "
            "Please have the work area accessible — vehicles moved, pets "
            "secured, and someone 18 or older on site."
        )
    if bt == "therapist":
        # Deliberately sparse and neutral — a confirmation email is often
        # read by someone other than the client, so it says nothing about
        # the content or purpose of the session. Scheduling only.
        return (
            "If you need to reschedule, please reach out as early as you "
            "can — the cancellation window in this email applies."
        )
    # Generic / unmapped — use the GENERIC tone_note if it surfaces;
    # otherwise stay silent (don't bloat the email).
    return ""


# ─────────────────────────────────────────────────────────────────────
# Email send (best-effort async)
# ─────────────────────────────────────────────────────────────────────


def _resolve_offering(business_id: str, offering_id: Optional[str]) -> Dict[str, Any]:
    """Return offering row (or {} on miss / no id)."""
    if not offering_id:
        return {}
    rows = sb_clients.sb_get_as_service(
        f"/offerings?id=eq.{offering_id}&business_id=eq.{business_id}"
        f"&select=id,name,slug,description,duration_min,current_price&limit=1"
    ) or []
    return rows[0] if rows else {}


def _resolve_hosted_url(business_id: str) -> Optional[str]:
    """Resolve the hosted booking URL. Best-effort.

    Prefers a VERIFIED custom domain over the platform subdomain — this
    link goes to the practitioner's customer, so it should name the
    address the practitioner actually advertises. Same defect and the
    same rule as brand_engine.public_site_url: a pending domain has no
    DNS behind it, and a dead booking link is far worse than an
    unfamiliar one."""
    try:
        rows = sb_clients.sb_get_as_service(
            f"/business_sites?business_id=eq.{business_id}"
            f"&select=slug,site_config&limit=1"
        ) or []
        if not rows:
            return None
        import brand_engine
        base = brand_engine.public_site_url(rows[0])
        return f"{base}/book" if base else None
    except Exception:
        return None


def _resolve_tz_label(business: Dict[str, Any]) -> Optional[str]:
    """Read business timezone for the email's 'business time' label."""
    settings = business.get("settings") or {}
    av = settings.get("availability") or {}
    tz = (av.get("timezone") or "").strip()
    return tz or None


def _business_address(business: Dict[str, Any]) -> Optional[str]:
    """Return a human-readable address from business.settings if any."""
    settings = business.get("settings") or {}
    addr = settings.get("address")
    if isinstance(addr, str) and addr.strip():
        return addr.strip()
    if isinstance(addr, dict):
        parts = [
            addr.get("street"), addr.get("city"),
            addr.get("region"), addr.get("postal_code"),
        ]
        joined = ", ".join(p for p in parts if p)
        return joined or None
    return None


async def send_confirmation_email(
    *,
    booking: Dict[str, Any],
    business: Dict[str, Any],
    customer_email: str,
    customer_name: str,
    offering_id: Optional[str] = None,
) -> None:
    """Send the customer's appointment confirmation email + .ics attachment.

    Best-effort: any error is logged and swallowed. Never raises."""
    try:
        if not customer_email or "@" not in customer_email:
            logger.info("skip confirmation: no customer email")
            return
        from email_sender import send_via_resend

        biz_name = business.get("name") or "Your appointment"
        biz_id = business.get("id") or ""
        # Data needed for the email body + .ics
        data = booking.get("data") or {}
        appointment_at = (
            data.get("appointment_at")
            or booking.get("appointment_at")
            or ""
        )
        duration_min = int(
            data.get("duration_min_at_booking")
            or data.get("duration_min")
            or 0
        )
        service_name = (
            data.get("service_name_at_booking")
            or data.get("service_name")
            or ""
        )
        price = data.get("price_at_booking") or data.get("price")
        # Arrival windows (contractor scheduling) — denormalized on the
        # entry at book time, like price_at_booking. None/0 = plain
        # exact-time booking.
        try:
            arrival_window_min = int(data.get("arrival_window_min_at_booking") or 0) or None
        except (TypeError, ValueError):
            arrival_window_min = None

        # If we have an offering_id, pull canonical fields to enrich.
        off = _resolve_offering(biz_id, offering_id) if offering_id else {}
        if off:
            service_name = service_name or off.get("name")
            duration_min = duration_min or int(off.get("duration_min") or 0)
            if price is None:
                price = off.get("current_price")
        description = (off or {}).get("description")
        tz_label = _resolve_tz_label(business)
        hosted_url = _resolve_hosted_url(biz_id)
        location = _business_address(business)

        # Compose .ics — for windowed bookings the event spans the
        # ARRIVAL WINDOW when it's longer than the job: the customer's
        # calendar should block the span they were asked to be
        # available, not imply the crew arrives at the window's opening
        # minute.
        ics_span_min = max(duration_min, arrival_window_min or 0)
        ics_bytes = build_ics(
            booking_id=str(booking.get("id") or ""),
            appointment_at_utc=str(appointment_at or ""),
            duration_min=ics_span_min,
            business_name=biz_name,
            service_name=service_name or None,
            description=description,
            location=location,
            organizer_email=os.environ.get("RESEND_FROM_EMAIL"),
            attendee_email=customer_email,
            attendee_name=customer_name,
        )
        ics_b64 = base64.b64encode(ics_bytes).decode("ascii")

        # Phase D.4 PR 3 — opportunistically generate a Stripe Checkout
        # Session at email-send time so the customer's confirmation email
        # carries a Pay Now link. Skipped if the business isn't connected
        # or has no price. Failures swallowed — email still ships.
        pay_now_url: Optional[str] = None
        try:
            stripe_acct = business.get("stripe_account_id")
            booking_id = booking.get("id")
            if stripe_acct and price and booking_id and not booking.get("paid_at"):
                from stripe_checkout_helpers import create_booking_checkout
                price_cents = int(round(float(price) * 100))
                if price_cents > 0:
                    public_url = hosted_url or "https://mysolutionist.app/"
                    session = await create_booking_checkout(
                        stripe_account_id=stripe_acct,
                        booking_id=str(booking_id),
                        service_name=service_name or "Booking",
                        amount_cents=price_cents,
                        customer_email=customer_email,
                        success_url=f"{public_url}?paid=1",
                        cancel_url=f"{public_url}?paid=0",
                    )
                    pay_now_url = session.get("url")
        except Exception as e:
            logger.warning(f"pay-now session create failed (non-fatal): {e!s}")

        # Compose body
        html_body = _build_html_body(
            business_name=biz_name,
            customer_name=customer_name,
            service_name=service_name,
            appointment_at_iso=str(appointment_at),
            duration_min=duration_min,
            price=price,
            tz_label=tz_label,
            hosted_page_url=hosted_url,
            cancellation_policy=DEFAULT_CANCELLATION_POLICY,
            pay_now_url=pay_now_url,
            business_type=business.get("type"),
            arrival_window_min=arrival_window_min,
        )

        # Slug-style filename: easier to identify in mail clients.
        fname_root = re.sub(r"[^a-z0-9-]+", "-", (biz_name or "appointment").lower()).strip("-") or "appointment"
        filename = f"{fname_root}-appointment.ics"

        # Phase C.1.4 — vertical-aware subject + body header.
        subject = _vertical_subject(business.get("type"), biz_name)

        await send_via_resend(
            to_email=customer_email,
            to_name=customer_name or None,
            from_email=os.environ.get("RESEND_FROM_EMAIL") or "noreply@mysolutionist.app",
            from_name=biz_name,
            subject=subject,
            body=html_body,
            reply_to=None,
            attachments=[{
                "filename": filename,
                "content": ics_b64,
                "content_type": "text/calendar",
            }],
            business_id=biz_id or None,
        )
        logger.info(
            f"confirmation email sent: booking={booking.get('id')} biz={biz_id} "
            f"to={customer_email}"
        )
    except Exception as e:
        logger.warning(
            f"confirmation email failed: booking={booking.get('id')} err={e!s}"
        )
