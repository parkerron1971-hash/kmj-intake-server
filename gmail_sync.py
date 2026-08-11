"""gmail_sync.py — pulling mail out of a connected mailbox.

THE JOB THIS DOES
  google_oauth.py stores a revocable grant. Nothing read it. This is the
  half that makes a connected mailbox mean something: a bounded, repeated
  pull of recent INBOX mail into mailbox_messages, where the Email Hub can
  show it and Chief's selection policy can decide what little of it is
  allowed anywhere near a prompt.

WHAT IT DELIBERATELY DOES NOT DO
  It does not read the whole mailbox. First run reaches back seven days
  and no further; every run is capped. A practitioner with 40,000 archived
  messages does not get 40,000 rows, and we do not become the owner of a
  copy of their entire correspondence because they clicked Connect.

  It does not read sent mail or drafts — INBOX only, and messages from the
  mailbox's own address are skipped. Chief quoting the practitioner's own
  words back to them as "mail that arrived" is not a feature.

  It does not write to email_replies. That table is seat-readable; this
  mail is the practitioner's personal inbox and lives in a table that is
  owner-only by construction. See APPLY-2026_08_11_mailbox_messages.sql.

INCREMENTAL, WITH A HONEST FALLBACK
  Gmail's History API is the cheap path: hand it the historyId you last
  saw and it returns what changed. Two things make it unreliable on its
  own, and both are handled rather than hoped about:

    - A historyId older than roughly a week returns 404. Google expires
      history, so a mailbox that went quiet (or a worker that was down)
      loses its watermark legitimately. That is not an error state; it
      falls back to a bounded list and re-establishes the watermark.
    - The watermark advances only after messages are processed. Advancing
      first would mean a mid-run failure silently skips mail forever, and
      the gap would look exactly like a quiet inbox.

STALENESS IS A STATE, NOT A GAP
  last_synced_at is written on every completed pass, including passes that
  found nothing. A connected source that has delivered no mail is
  indistinguishable from a broken one unless the last successful run is
  recorded — silence is what a dead feed looks like.
"""
from __future__ import annotations

import base64
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import httpx

import sb_clients
import mailbox_policy
import google_oauth

logger = logging.getLogger("gmail_sync")

GMAIL_BASE = "https://gmail.googleapis.com/gmail/v1/users/me"

# Per-run ceiling. A busy mailbox must not be able to turn one tick into a
# thousand API calls, and a run that cannot finish is worse than a run that
# catches up over several ticks.
MAX_MESSAGES_PER_RUN = 25

# How far back the FIRST sync reaches. Deliberately short: the feature is
# "see mail as it arrives", not "import my archive".
INITIAL_BACKFILL_DAYS = 7

# Bodies are capped to match email_replies. The prompt only ever sees ~280
# chars of this; the rest is for the Hub.
MAX_BODY_CHARS = 20000

HTTP_TIMEOUT = httpx.Timeout(connect=10.0, read=30.0, write=15.0, pool=10.0)


def _now_z() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ─── Header + body parsing ───────────────────────────────────────────

def _header(payload: Dict[str, Any], name: str) -> str:
    for h in (payload.get("headers") or []):
        if (h.get("name") or "").lower() == name.lower():
            return h.get("value") or ""
    return ""


_ADDR_RE = re.compile(r"<([^>]+)>")


def _split_from(raw: str) -> Tuple[str, str]:
    """"Marcus Webb <marcus@client.com>" -> ("marcus@client.com", "Marcus Webb").

    Falls back to treating the whole string as the address, which is what
    a bare "marcus@client.com" From header actually is.
    """
    raw = (raw or "").strip()
    if not raw:
        return "", ""
    match = _ADDR_RE.search(raw)
    if match:
        email = match.group(1).strip().lower()
        name = raw[:match.start()].strip().strip('"').strip()
        return email, name
    return raw.lower(), ""


def _b64url(data: str) -> str:
    """Gmail pads inconsistently; decoding must not throw on a real message."""
    if not data:
        return ""
    try:
        padded = data + "=" * (-len(data) % 4)
        return base64.urlsafe_b64decode(padded.encode("ascii")).decode(
            "utf-8", errors="replace")
    except Exception:
        return ""


def _find_mime(payload: Dict[str, Any], want: str) -> str:
    """First decoded part of `want` anywhere in the tree."""
    mime = (payload.get("mimeType") or "").lower()
    data = ((payload.get("body") or {}).get("data")) or ""
    if mime == want and data:
        return _b64url(data)
    for part in (payload.get("parts") or []):
        found = _find_mime(part, want)
        if found.strip():
            return found
    return ""


def _extract_body(payload: Dict[str, Any]) -> str:
    """Prefer text/plain anywhere in the tree; fall back to stripped HTML.

    The preference has to be resolved across the WHOLE tree, in two
    passes — not per node on the way down. A multipart/alternative lists
    text/html before text/plain, so a single depth-first walk that falls
    back to HTML at each leaf returns the HTML copy of a message whose
    plain-text copy was sitting right beside it. That does not raise; it
    just quietly stores markup-derived text for most real mail.

    Multipart nesting is the normal case, not an edge one — a reply from
    Outlook with an attachment is routinely multipart/mixed wrapping
    multipart/alternative.
    """
    plain = _find_mime(payload, "text/plain")
    if plain.strip():
        return plain

    html = _find_mime(payload, "text/html")
    if html.strip():
        try:
            import email_sender
            return email_sender._strip_html(html)
        except Exception:
            return re.sub(r"<[^>]+>", " ", html)
    return ""


def _received_at(msg: Dict[str, Any]) -> str:
    """internalDate is epoch millis and is what Gmail sorts by. The Date
    header is attacker-controlled and routinely wrong; using it would let
    a sender pin themselves to the top of the practitioner's mail."""
    raw = msg.get("internalDate")
    try:
        return datetime.fromtimestamp(int(raw) / 1000.0, tz=timezone.utc)\
            .strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return _now_z()


# ─── Gmail API ───────────────────────────────────────────────────────

async def _list_recent_ids(client: httpx.AsyncClient, token: str) -> List[str]:
    """Bounded fallback / first run: recent INBOX only."""
    after = (datetime.now(timezone.utc)
             - timedelta(days=INITIAL_BACKFILL_DAYS)).strftime("%Y/%m/%d")
    resp = await client.get(
        f"{GMAIL_BASE}/messages",
        headers={"Authorization": f"Bearer {token}"},
        params={"maxResults": MAX_MESSAGES_PER_RUN,
                "labelIds": "INBOX",
                "q": f"after:{after}"})
    if resp.status_code >= 400:
        logger.warning("[GMAIL] messages.list %s: %s",
                       resp.status_code, resp.text[:300])
        return []
    return [m.get("id") for m in (resp.json().get("messages") or []) if m.get("id")]


async def _list_history_ids(client: httpx.AsyncClient, token: str,
                            start_history_id: str) -> Tuple[List[str], bool]:
    """Returns (message_ids, watermark_valid).

    watermark_valid=False means Google expired the historyId and the
    caller must fall back to a bounded list. That is a normal outcome for
    a mailbox nobody wrote to for a week, not a failure.
    """
    resp = await client.get(
        f"{GMAIL_BASE}/history",
        headers={"Authorization": f"Bearer {token}"},
        params={"startHistoryId": start_history_id,
                "historyTypes": "messageAdded",
                "labelId": "INBOX",
                "maxResults": 200})
    if resp.status_code == 404:
        logger.info("[GMAIL] historyId expired; falling back to bounded list")
        return [], False
    if resp.status_code >= 400:
        logger.warning("[GMAIL] history.list %s: %s",
                       resp.status_code, resp.text[:300])
        return [], True          # transient: keep the watermark, retry next tick
    ids: List[str] = []
    for record in (resp.json().get("history") or []):
        for added in (record.get("messagesAdded") or []):
            msg_id = (added.get("message") or {}).get("id")
            if msg_id and msg_id not in ids:
                ids.append(msg_id)
    return ids[:MAX_MESSAGES_PER_RUN], True


async def _get_message(client: httpx.AsyncClient, token: str,
                       msg_id: str) -> Optional[Dict[str, Any]]:
    resp = await client.get(
        f"{GMAIL_BASE}/messages/{msg_id}",
        headers={"Authorization": f"Bearer {token}"},
        params={"format": "full"})
    if resp.status_code >= 400:
        logger.warning("[GMAIL] messages.get %s %s", msg_id, resp.status_code)
        return None
    return resp.json()


async def _current_history_id(client: httpx.AsyncClient,
                              token: str) -> Optional[str]:
    resp = await client.get(f"{GMAIL_BASE}/profile",
                            headers={"Authorization": f"Bearer {token}"})
    if resp.status_code >= 400:
        return None
    return str((resp.json() or {}).get("historyId") or "") or None


# ─── Storage ─────────────────────────────────────────────────────────

def _contact_by_email(business_id: str, email: str) -> Optional[str]:
    if not email:
        return None
    safe = email.replace("*", "").replace(",", "")
    rows = sb_clients.sb_get_as_service(
        f"/contacts?business_id=eq.{business_id}"
        f"&email=ilike.{safe}&select=id&limit=1") or []
    return rows[0].get("id") if rows else None


def _store(business_id: str, google_email: str,
           msg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Returns the stored row, or None when nothing was written.

    The row comes back rather than a bool because the caller has to decide
    who is worth interrupting for, and that decision needs the sender.
    Idempotent on (business_id, gmail_message_id) — a history replay or an
    overlapping run must not create a second copy.
    """
    payload = msg.get("payload") or {}
    from_email, from_name = _split_from(_header(payload, "From"))

    # The practitioner's own sent mail is not "mail that arrived".
    if from_email and from_email == (google_email or "").strip().lower():
        return None

    row = {
        "business_id": business_id,
        "google_email": google_email,
        "gmail_message_id": msg.get("id"),
        "gmail_thread_id": msg.get("threadId"),
        "from_email": from_email or None,
        "from_name": from_name or None,
        "subject": _header(payload, "Subject") or None,
        "body_text": (_extract_body(payload) or "")[:MAX_BODY_CHARS] or None,
        "received_at": _received_at(msg),
        "contact_id": _contact_by_email(business_id, from_email),
        "read": False,
        "metadata": {
            "source": "mailbox",
            "message_id": _header(payload, "Message-ID") or None,
            "in_reply_to": _header(payload, "In-Reply-To") or None,
            "snippet": (msg.get("snippet") or "")[:400] or None,
        },
    }
    written = sb_clients.sb_post_as_service(
        "/mailbox_messages", row,
        prefer="resolution=ignore-duplicates,return=minimal")
    # sb_* returns None on 4xx/5xx. Treating that as success would report
    # mail as ingested over a write that never landed.
    return row if written is not None else None


# ─── Telling the practitioner ────────────────────────────────────────
#
# Ingest without an alert solved half the problem. The arc exists because
# "a new lead emails you and nobody knows" — and a mailbox that fills a
# tray you have to remember to open is still nobody knowing.
#
# THREE RULES, ALL OF THEM ABOUT RESTRAINT
#
# 1. Only mail that passed the selection policy is worth interrupting
#    for. Pushing on every newsletter trains someone to swipe the channel
#    away, which is worse than silence because it also buries the message
#    that mattered.
#
# 2. NO SENDER-CONTROLLED TEXT IN THE NOTIFICATION. Not the subject, not
#    even the From display name. Both are attacker-chosen, and a lock
#    screen showing "Your account is suspended — click here" under this
#    app's name is a phishing message WE delivered. _neutralize_untrusted
#    does not help: it guards the prompt, not the push.
#
#    The name shown comes from OUR contacts row — text the practitioner
#    typed themselves. If we cannot resolve one, the alert says how many
#    arrived and no more.
#
# 3. One notification per sync pass, never one per message. The pass runs
#    every ten minutes, so that is also the rate limit: a morning of mail
#    is at most six buzzes, each bundling whatever landed.

def _contact_names_by_email(business_id: str) -> Dict[str, str]:
    rows = sb_clients.sb_get_as_service(
        f"/contacts?business_id=eq.{business_id}&select=name,email&limit=500") or []
    out: Dict[str, str] = {}
    for r in rows:
        email = (r.get("email") or "").strip().lower()
        if email and (r.get("name") or "").strip():
            out[email] = r["name"].strip()
    return out


def _describe(names: List[str], count: int) -> str:
    """Notification body from trusted names only."""
    if not names:
        # Eligible but unnamed: the contact row has an email and no name.
        return f"{count} new email{'s' if count != 1 else ''} from your contacts."
    if count == 1:
        return f"{names[0]} emailed you."
    if len(names) == 1:
        return f"{names[0]} and {count - 1} other{'s' if count > 2 else ''} emailed you."
    if count == 2:
        return f"{names[0]} and {names[1]} emailed you."
    return f"{names[0]}, {names[1]} and {count - 2} other{'s' if count > 3 else ''} emailed you."


def _alert_new_mail(business_id: str, stored: List[Dict[str, Any]]) -> Dict[str, Any]:
    """One bundled alert for the eligible mail from a single sync pass.

    Never raises. A failed notification must not fail the sync — the mail
    is already stored and visible; the alert is a courtesy on top.
    """
    result = {"eligible": 0, "notified": False, "pushed": 0}
    if not stored:
        return result
    try:
        contacts = sb_clients.sb_get_as_service(
            f"/contacts?business_id=eq.{business_id}&select=email,name&limit=500") or []
        known = mailbox_policy.known_sender_emails(contacts)
        eligible = [r for r in stored
                    if mailbox_policy.is_prompt_eligible(r, known)]
        result["eligible"] = len(eligible)
        if not eligible:
            # Mail arrived, none of it from anyone they know. Stays in the
            # Hub with a count; nobody's phone buzzes for a newsletter.
            return result

        by_email = _contact_names_by_email(business_id)
        names: List[str] = []
        for row in eligible:
            name = by_email.get((row.get("from_email") or "").strip().lower())
            if name and name not in names:
                names.append(name)
        body = _describe(names, len(eligible))

        # In-app first: this is the one that makes Chief LEAD with the news
        # next time they open a chat, rather than waiting to be asked.
        sb_clients.sb_post_as_service("/chief_notifications", {
            "business_id": business_id,
            "type": "reminder",
            "title": "New email"[:120],
            "body": body[:300],
            "priority": "normal",
            "data": {"source": "mailbox", "count": len(eligible)},
        })
        result["notified"] = True

        try:
            import push_notifications
            result["pushed"] = push_notifications.send_to_business(
                # "operate:email", not "email". The service worker hands
                # nav to resolveNav, which splits on ":" into tab and sub
                # — a bare "email" matches no tab and silently lands on
                # home. A notification that opens the wrong screen is a
                # dead end wearing a working button's clothes.
                business_id, title="New email", body=body, nav="operate:email",
                # Same tag collapses an unread stack into the latest one
                # instead of stacking six separate banners.
                tag="mailbox-new-mail")
        except Exception as exc:
            logger.warning("[GMAIL] push failed for business=%s: %s",
                           business_id, exc)
    except Exception as exc:
        logger.warning("[GMAIL] alert failed for business=%s: %s",
                       business_id, exc)
    return result


# ─── One mailbox ─────────────────────────────────────────────────────

async def _sync_one(client: httpx.AsyncClient,
                    mailbox: Dict[str, Any]) -> Dict[str, Any]:
    business_id = mailbox.get("business_id")
    google_email = mailbox.get("google_email") or ""
    refresh_token = mailbox.get("refresh_token")
    result = {"business_id": business_id, "google_email": google_email,
              "stored": 0, "seen": 0, "status": "ok"}

    if not refresh_token:
        result["status"] = "no_refresh_token"
        return result

    tokens = await google_oauth._refresh_access_token(client, refresh_token)
    if not tokens or not tokens.get("access_token"):
        # Google rejected the refresh token: revoked, password reset, or a
        # Workspace admin pulled third-party access. A real state, not a
        # blip — mark it so the card can say so and the job stops retrying
        # a credential that will never work again.
        sb_clients.sb_patch_as_service(
            f"/google_mailboxes?business_id=eq.{business_id}"
            f"&google_email=eq.{google_email}",
            {"status": "revoked",
             "last_error": "Google rejected the stored permission. Reconnect the mailbox.",
             "updated_at": _now_z()})
        result["status"] = "revoked"
        return result

    token = tokens["access_token"]
    watermark = (mailbox.get("last_history_id") or "").strip()

    if watermark:
        ids, valid = await _list_history_ids(client, token, watermark)
        if not valid:
            ids = await _list_recent_ids(client, token)
    else:
        ids = await _list_recent_ids(client, token)

    result["seen"] = len(ids)
    stored_rows: List[Dict[str, Any]] = []
    for msg_id in ids[:MAX_MESSAGES_PER_RUN]:
        msg = await _get_message(client, token, msg_id)
        if not msg:
            continue
        row = _store(business_id, google_email, msg)
        if row:
            stored_rows.append(row)
            result["stored"] += 1

    # Do NOT alert on the first pass. Without a watermark this run is the
    # initial seven-day backfill, so everything looks new — connecting a
    # mailbox would fire a notification about last Tuesday's mail the
    # instant you finished the consent screen. The first pass establishes
    # the baseline silently; from the second on, new means new.
    if watermark:
        result["alert"] = _alert_new_mail(business_id, stored_rows)
    elif stored_rows:
        logger.info("[GMAIL] first pass for business=%s: %d stored, no alert",
                    business_id, len(stored_rows))

    # Watermark AFTER processing, never before. Advancing first would make
    # a mid-run failure skip mail permanently, and the hole would be
    # indistinguishable from a quiet week.
    patch = {"last_synced_at": _now_z(), "updated_at": _now_z()}
    fresh = await _current_history_id(client, token)
    if fresh:
        patch["last_history_id"] = fresh
    if mailbox.get("status") != "connected":
        patch["status"] = "connected"
        patch["last_error"] = None
    sb_clients.sb_patch_as_service(
        f"/google_mailboxes?business_id=eq.{business_id}"
        f"&google_email=eq.{google_email}", patch)
    return result


# ─── The worker tick ─────────────────────────────────────────────────

async def sync_tick() -> Dict[str, Any]:
    """Scheduled on the WORKER service. One pass over connected mailboxes.

    Never raises: a single bad mailbox must not take down the tick for
    every other business on the platform.
    """
    if not google_oauth._configured():
        return {"skipped": "google_oauth_not_configured"}

    mailboxes = sb_clients.sb_get_as_service(
        "/google_mailboxes?status=eq.connected"
        "&select=business_id,google_email,refresh_token,last_history_id,status"
        "&limit=200") or []
    if not mailboxes:
        return {"mailboxes": 0, "stored": 0}

    stored = 0
    results: List[Dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        for mailbox in mailboxes:
            try:
                one = await _sync_one(client, mailbox)
                stored += one.get("stored") or 0
                results.append(one)
            except Exception as exc:
                logger.warning("[GMAIL] sync failed for business=%s: %s",
                               mailbox.get("business_id"), exc)
                results.append({"business_id": mailbox.get("business_id"),
                                "status": "error"})
    logger.info("[GMAIL] sync tick: %d mailbox(es), %d stored",
                len(mailboxes), stored)
    return {"mailboxes": len(mailboxes), "stored": stored, "results": results}
