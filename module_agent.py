"""
module_agent.py — Solutionist System Module Agent

Watches custom_modules + module_entries for this business and drafts
agent_queue rows when triggers fire:

  new_entry    — a new module_entries row was created in the last 24h
                 and no module_entry_notified event exists for it
  overdue      — entry.data[field] (a date) is in the past AND the
                 entry's status is not in agent_config.closed_statuses
  field_change — a module_field_changed event exists in the last 24h
                 matching the trigger's field/from/to

═══════════════════════════════════════════════════════════════════════
DEPLOYMENT
═══════════════════════════════════════════════════════════════════════

1. Drop into Railway project alongside the other agent files.
2. In main.py:
       from module_agent import router as module_router
       app.include_router(module_router)
3. Env vars (already set): SUPABASE_URL, SUPABASE_ANON, ANTHROPIC_API_KEY
"""

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

# ═══════════════════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════════════════

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
DRAFT_MODEL = "claude-sonnet-4-5-20250929"
HTTP_TIMEOUT = httpx.Timeout(connect=10.0, read=120.0, write=30.0, pool=10.0)

NEW_ENTRY_LOOKBACK_HOURS = 24
FIELD_CHANGE_LOOKBACK_HOURS = 24
OVERDUE_DEDUP_DAYS = 7
PER_RUN_DRAFT_CAP = 20  # safety net across all modules/triggers

logger = logging.getLogger("module_agent")
if not logger.handlers:
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] module: %(message)s"))
    logger.addHandler(h)
    logger.setLevel(logging.INFO)


def _supabase_url(): return os.environ.get("SUPABASE_URL", "")
def _supabase_anon(): return os.environ.get("SUPABASE_ANON", "")
def _anthropic_key(): return os.environ.get("ANTHROPIC_API_KEY", "")


# ═══════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════

async def _sb(client: httpx.AsyncClient, method: str, path: str, body=None):
    url = f"{_supabase_url()}/rest/v1{path}"
    headers = {
        "apikey": _supabase_anon(),
        "Authorization": f"Bearer {_supabase_anon()}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }
    resp = await client.request(method, url, headers=headers,
                                content=json.dumps(body) if body else None,
                                timeout=HTTP_TIMEOUT)
    if resp.status_code >= 400:
        logger.error(f"Supabase {method} {path}: {resp.status_code} {resp.text[:300]}")
        return None
    text = resp.text
    return json.loads(text) if text else None


async def _call_claude(client: httpx.AsyncClient, system: str, user_msg: str, max_tokens: int = 400) -> str:
    key = _anthropic_key()
    if not key:
        return ""
    try:
        resp = await client.post(ANTHROPIC_API_URL, headers={
            "x-api-key": key, "anthropic-version": ANTHROPIC_VERSION, "content-type": "application/json",
        }, json={
            "model": DRAFT_MODEL, "max_tokens": max_tokens, "system": system,
            "messages": [{"role": "user", "content": user_msg}],
        }, timeout=HTTP_TIMEOUT)
    except httpx.HTTPError as e:
        logger.warning(f"Claude request failed: {e}")
        return ""
    if resp.status_code >= 400:
        logger.warning(f"Claude error: {resp.status_code}")
        return ""
    data = resp.json()
    return "".join(b.get("text", "") for b in data.get("content", []) if isinstance(b, dict)).strip()


def _render_template(template: str, data: Dict[str, Any], module_name: str, contact_name: str = "") -> str:
    """Render a simple {{key}} template using entry data + module_name + contact_name."""
    if not template:
        return ""
    out = template
    out = out.replace("{{module_name}}", module_name)
    out = out.replace("{{contact_name}}", contact_name or "this contact")
    for key, val in (data or {}).items():
        out = out.replace("{{" + key + "}}", str(val) if val is not None else "")
    return out


async def _resolve_contact_name(client: httpx.AsyncClient, contact_id: Optional[str]) -> str:
    if not contact_id:
        return ""
    rows = await _sb(client, "GET", f"/contacts?id=eq.{contact_id}&select=name&limit=1") or []
    return rows[0].get("name", "") if rows else ""


def _parse_date(val: Any) -> Optional[datetime]:
    if not val or not isinstance(val, str):
        return None
    s = val[:19] if len(val) >= 19 else val
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s[:len(datetime.strftime(datetime.now(), fmt))], fmt).replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            continue
    # Last resort — full ISO
    try:
        return datetime.fromisoformat(val.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


async def _draft_and_insert(
    client: httpx.AsyncClient,
    biz: Dict, module: Dict, entry: Dict,
    trigger: Dict, subject: str, reasoning: str,
    priority: str = "medium",
) -> Optional[str]:
    """Draft a body via Claude and insert into agent_queue. Returns queue id."""
    biz_name = biz.get("name", "")
    voice = biz.get("voice_profile") or {}
    practitioner = (biz.get("settings") or {}).get("practitioner_name", "the team")
    tone = voice.get("tone", "warm and professional")
    module_name = module.get("name", "module")
    trigger_type = trigger.get("type", "")
    template = trigger.get("template", "")

    system_prompt = f"""You are the Module Agent for {biz_name}. Draft a short notification from {practitioner} about a {module_name} entry.

Voice: {tone}. Keep it under 4 sentences. Sign off as {practitioner}.

Trigger: {trigger_type}.
Template hint: "{template}" — rewrite it in the practitioner's voice; don't copy it verbatim."""

    user_msg = (
        f"Module: {module_name}\n"
        f"Entry data: {json.dumps(entry.get('data') or {})[:800]}\n"
        f"Trigger: {trigger_type}\n"
        f"Subject: {subject}\n\n"
        f"Draft the notification body."
    )

    body = await _call_claude(client, system_prompt, user_msg, max_tokens=400)
    if not body:
        body = subject

    # Map action to agent_queue.action_type (constraint-safe)
    action_map = {
        "draft_acknowledgment": "check_in",
        "draft_reminder": "alert",
        "draft_notification": "other",
    }
    action_type = action_map.get(trigger.get("action", ""), "other")

    inserted = await _sb(client, "POST", "/agent_queue", {
        "business_id": biz["id"],
        "contact_id": (entry.get("data") or {}).get("contact_id"),
        "agent": "module",
        "action_type": action_type,
        "subject": subject,
        "body": body,
        "channel": "in_app",
        "status": "draft",
        "priority": priority,
        "ai_reasoning": reasoning,
        "ai_model": DRAFT_MODEL,
    })
    if inserted and isinstance(inserted, list) and inserted:
        return inserted[0]["id"]
    return None


# ═══════════════════════════════════════════════════════════════════════
# TRIGGER HANDLERS
# ═══════════════════════════════════════════════════════════════════════

async def _handle_new_entry(client, biz, module, trigger, cap_remaining: int) -> List[Dict]:
    results = []
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=NEW_ENTRY_LOOKBACK_HOURS)).isoformat()
    entries = await _sb(client, "GET",
        f"/module_entries?module_id=eq.{module['id']}&status=eq.active"
        f"&created_at=gte.{cutoff}&order=created_at.desc&limit={max(1, cap_remaining)}"
        f"&select=*"
    ) or []

    for entry in entries:
        if len(results) >= cap_remaining:
            break
        # Has this entry already been notified?
        notified = await _sb(client, "GET",
            f"/events?business_id=eq.{biz['id']}&event_type=eq.module_entry_notified"
            f"&data->>entry_id=eq.{entry['id']}&select=id&limit=1"
        )
        if notified:
            continue

        contact_name = await _resolve_contact_name(client, (entry.get("data") or {}).get("contact_id"))
        subject = _render_template(trigger.get("template", f"New {module['name']} entry"),
                                   entry.get("data") or {}, module["name"], contact_name) \
                  or f"New {module['name']}"
        reasoning = f"new_entry trigger on module '{module['name']}'. Entry created in last 24h."

        qid = await _draft_and_insert(client, biz, module, entry, trigger, subject, reasoning, priority="medium")
        if qid:
            # Log the notification so we don't duplicate on the next run
            await _sb(client, "POST", "/events", {
                "business_id": biz["id"], "contact_id": (entry.get("data") or {}).get("contact_id"),
                "event_type": "module_entry_notified",
                "data": {"module_id": module["id"], "entry_id": entry["id"], "queue_id": qid},
                "source": "module_agent",
            })
            results.append({"module": module["name"], "trigger": "new_entry", "entry_id": entry["id"], "queue_id": qid})
    return results


async def _handle_overdue(client, biz, module, trigger, cap_remaining: int) -> List[Dict]:
    results = []
    field_name = trigger.get("field")
    if not field_name:
        return results

    closed_statuses = set(((module.get("agent_config") or {}).get("closed_statuses") or []))
    dedup_cutoff = (datetime.now(timezone.utc) - timedelta(days=OVERDUE_DEDUP_DAYS)).isoformat()
    now = datetime.now(timezone.utc)

    # Fetch all active entries for this module — overdue check runs client-side
    # since the date lives inside a JSONB field and comparing JSONB dates via
    # PostgREST is fragile.
    entries = await _sb(client, "GET",
        f"/module_entries?module_id=eq.{module['id']}&status=eq.active"
        f"&order=updated_at.desc&limit=200&select=*"
    ) or []

    # Identify status field — use schema.board_column as the hint
    status_field = (module.get("schema") or {}).get("board_column")

    for entry in entries:
        if len(results) >= cap_remaining:
            break
        data = entry.get("data") or {}
        raw = data.get(field_name)
        date_val = _parse_date(raw) if raw else None
        if not date_val or date_val >= now:
            continue
        if status_field and data.get(status_field) in closed_statuses:
            continue

        # Dedup — any overdue notification for this entry in last 7d?
        dedup = await _sb(client, "GET",
            f"/events?business_id=eq.{biz['id']}&event_type=eq.module_overdue_drafted"
            f"&data->>entry_id=eq.{entry['id']}&created_at=gte.{dedup_cutoff}"
            f"&select=id&limit=1"
        )
        if dedup:
            continue

        days_overdue = max(1, (now - date_val).days)
        merged_data = {**data, "days_overdue": days_overdue}
        contact_name = await _resolve_contact_name(client, data.get("contact_id"))
        subject = _render_template(trigger.get("template", f"{module['name']} overdue"),
                                   merged_data, module["name"], contact_name) \
                  or f"{module['name']} overdue"
        reasoning = f"overdue trigger on '{field_name}'. {days_overdue}d past due. Status: {data.get(status_field) if status_field else 'n/a'}."
        priority = "high" if days_overdue >= 7 else "medium"

        qid = await _draft_and_insert(client, biz, module, entry, trigger, subject, reasoning, priority=priority)
        if qid:
            await _sb(client, "POST", "/events", {
                "business_id": biz["id"], "contact_id": data.get("contact_id"),
                "event_type": "module_overdue_drafted",
                "data": {"module_id": module["id"], "entry_id": entry["id"], "queue_id": qid, "days_overdue": days_overdue, "field": field_name},
                "source": "module_agent",
            })
            results.append({"module": module["name"], "trigger": "overdue", "entry_id": entry["id"], "queue_id": qid, "days_overdue": days_overdue})
    return results


# ═══════════════════════════════════════════════════════════════════════
# INTERNAL CONNECTION HANDLERS (session-linked / contact-linked / scheduled)
# ═══════════════════════════════════════════════════════════════════════
# These run regardless of agent_config.triggers. They create module_entries
# rather than agent_queue drafts, so they don't count against PER_RUN_DRAFT_CAP.

SCHEDULE_INTERVALS = {
    "daily": timedelta(days=1),
    "weekly": timedelta(days=7),
    "biweekly": timedelta(days=14),
    "monthly": timedelta(days=30),
}


async def _handle_session_linked(client, biz, module) -> List[Dict]:
    """For modules flagged session_linked, create one module_entry per recently
    completed session that hasn't been linked yet (dedup via event)."""
    results = []
    cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    sessions = await _sb(client, "GET",
        f"/sessions?business_id=eq.{biz['id']}&status=eq.completed"
        f"&scheduled_for=gte.{cutoff}&order=scheduled_for.desc&limit=20&select=*"
    ) or []

    for s in sessions:
        dedup = await _sb(client, "GET",
            f"/events?business_id=eq.{biz['id']}&event_type=eq.module_session_linked"
            f"&data->>session_id=eq.{s['id']}&data->>module_id=eq.{module['id']}"
            f"&select=id&limit=1"
        )
        if dedup:
            continue

        # Pre-fill a module entry with session basics. The practitioner can add notes via DynamicModule.
        schema_field_names = {f.get("name") for f in (module.get("schema") or {}).get("fields") or [] if isinstance(f, dict)}
        data: Dict[str, Any] = {}
        if "title" in schema_field_names:
            data["title"] = f"Session: {s.get('title') or 'completed'}"
        if "deliverable_name" in schema_field_names:
            data["deliverable_name"] = s.get("title") or "Session notes"
        if "session_id" in schema_field_names:
            data["session_id"] = s["id"]
        if "contact_id" in schema_field_names and s.get("contact_id"):
            data["contact_id"] = s["contact_id"]
        if "status" in schema_field_names:
            data["status"] = "new"
        if "notes" in schema_field_names and s.get("notes"):
            data["notes"] = s["notes"]

        inserted = await _sb(client, "POST", "/module_entries", {
            "module_id": module["id"], "business_id": biz["id"],
            "data": data, "status": "active",
            "created_by": "session_agent", "source": "session_link",
        })
        if inserted and isinstance(inserted, list) and inserted:
            eid = inserted[0]["id"]
            await _sb(client, "POST", "/events", {
                "business_id": biz["id"], "contact_id": s.get("contact_id"),
                "event_type": "module_session_linked",
                "data": {"module_id": module["id"], "entry_id": eid, "session_id": s["id"]},
                "source": "module_agent",
            })
            results.append({"module": module["name"], "trigger": "session_linked", "entry_id": eid, "session_id": s["id"]})
    return results


async def _handle_contact_linked(client, biz, module) -> List[Dict]:
    """Create a module_entry when a contact's status transitions match."""
    results = []
    cfg = ((module.get("agent_config") or {}).get("contact_linked") or {})
    to_status = cfg.get("to")
    from_status = cfg.get("from")
    if not to_status:
        return results

    cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    events = await _sb(client, "GET",
        f"/events?business_id=eq.{biz['id']}&event_type=eq.contact_status_changed"
        f"&created_at=gte.{cutoff}&order=created_at.desc&limit=100&select=*"
    ) or []

    for ev in events:
        d = ev.get("data") or {}
        if str(d.get("to")) != str(to_status):
            continue
        if from_status is not None and str(d.get("from")) != str(from_status):
            continue

        dedup = await _sb(client, "GET",
            f"/events?business_id=eq.{biz['id']}&event_type=eq.module_contact_linked"
            f"&data->>source_event_id=eq.{ev['id']}&data->>module_id=eq.{module['id']}"
            f"&select=id&limit=1"
        )
        if dedup:
            continue

        contact_id = ev.get("contact_id")
        schema_field_names = {f.get("name") for f in (module.get("schema") or {}).get("fields") or [] if isinstance(f, dict)}
        data: Dict[str, Any] = {}
        if "contact_id" in schema_field_names and contact_id:
            data["contact_id"] = contact_id
        if "title" in schema_field_names:
            contact_name = await _resolve_contact_name(client, contact_id) or "contact"
            data["title"] = f"{contact_name} → {to_status}"
        if "status" in schema_field_names:
            data["status"] = "new"

        inserted = await _sb(client, "POST", "/module_entries", {
            "module_id": module["id"], "business_id": biz["id"],
            "data": data, "status": "active",
            "created_by": "contact_link", "source": "contact_link",
        })
        if inserted and isinstance(inserted, list) and inserted:
            eid = inserted[0]["id"]
            await _sb(client, "POST", "/events", {
                "business_id": biz["id"], "contact_id": contact_id,
                "event_type": "module_contact_linked",
                "data": {"module_id": module["id"], "entry_id": eid, "source_event_id": ev["id"]},
                "source": "module_agent",
            })
            results.append({"module": module["name"], "trigger": "contact_linked", "entry_id": eid, "contact_id": contact_id})
    return results


async def _handle_scheduled(client, biz, module) -> List[Dict]:
    """Create a periodic blank entry if the interval has elapsed since the last one."""
    results = []
    cfg = ((module.get("agent_config") or {}).get("schedule") or {})
    interval_key = str(cfg.get("interval", "weekly")).lower()
    delta = SCHEDULE_INTERVALS.get(interval_key)
    if not delta:
        return results

    # Find the most recent scheduled entry
    last = await _sb(client, "GET",
        f"/module_entries?module_id=eq.{module['id']}&source=eq.schedule"
        f"&order=created_at.desc&limit=1&select=id,created_at"
    ) or []

    if last:
        try:
            last_dt = datetime.fromisoformat(last[0]["created_at"].replace("Z", "+00:00"))
            if datetime.now(timezone.utc) - last_dt < delta:
                return results  # not yet due
        except (ValueError, TypeError, KeyError):
            pass

    schema_field_names = {f.get("name") for f in (module.get("schema") or {}).get("fields") or [] if isinstance(f, dict)}
    data: Dict[str, Any] = {}
    if "title" in schema_field_names:
        label_map = {"daily": "Daily", "weekly": "Weekly", "biweekly": "Biweekly", "monthly": "Monthly"}
        label = label_map.get(interval_key, "Scheduled")
        data["title"] = f"{label} — {datetime.now(timezone.utc).strftime('%b %d, %Y')}"
    if "status" in schema_field_names:
        data["status"] = "new"

    inserted = await _sb(client, "POST", "/module_entries", {
        "module_id": module["id"], "business_id": biz["id"],
        "data": data, "status": "active",
        "created_by": "schedule", "source": "schedule",
    })
    if inserted and isinstance(inserted, list) and inserted:
        eid = inserted[0]["id"]
        results.append({"module": module["name"], "trigger": "schedule", "entry_id": eid, "interval": interval_key})
    return results


async def _handle_field_change(client, biz, module, trigger, cap_remaining: int) -> List[Dict]:
    results = []
    field = trigger.get("field")
    to_val = trigger.get("to")
    if not field:
        return results

    cutoff = (datetime.now(timezone.utc) - timedelta(hours=FIELD_CHANGE_LOOKBACK_HOURS)).isoformat()
    events = await _sb(client, "GET",
        f"/events?business_id=eq.{biz['id']}&event_type=eq.module_field_changed"
        f"&created_at=gte.{cutoff}&data->>module_id=eq.{module['id']}"
        f"&data->>field=eq.{field}&order=created_at.desc&limit=50&select=*"
    ) or []

    for ev in events:
        if len(results) >= cap_remaining:
            break
        ev_data = ev.get("data") or {}
        new_val = ev_data.get("to")
        # Filter on from/to if present on the trigger
        if to_val is not None and str(new_val) != str(to_val):
            continue
        if trigger.get("from") is not None and str(ev_data.get("from")) != str(trigger["from"]):
            continue

        entry_id = ev_data.get("entry_id")
        if not entry_id:
            continue

        # Dedup — did we already draft for this event?
        dedup = await _sb(client, "GET",
            f"/events?business_id=eq.{biz['id']}&event_type=eq.module_fieldchange_drafted"
            f"&data->>source_event_id=eq.{ev['id']}&select=id&limit=1"
        )
        if dedup:
            continue

        entry_rows = await _sb(client, "GET",
            f"/module_entries?id=eq.{entry_id}&limit=1&select=*") or []
        if not entry_rows:
            continue
        entry = entry_rows[0]

        contact_name = await _resolve_contact_name(client, (entry.get("data") or {}).get("contact_id"))
        subject = _render_template(trigger.get("template", f"{module['name']} update"),
                                   entry.get("data") or {}, module["name"], contact_name) \
                  or f"{module['name']} update"
        reasoning = f"field_change trigger — {field} changed to {new_val}."

        qid = await _draft_and_insert(client, biz, module, entry, trigger, subject, reasoning, priority="medium")
        if qid:
            await _sb(client, "POST", "/events", {
                "business_id": biz["id"], "contact_id": (entry.get("data") or {}).get("contact_id"),
                "event_type": "module_fieldchange_drafted",
                "data": {"module_id": module["id"], "entry_id": entry_id, "queue_id": qid, "field": field, "to": new_val, "source_event_id": ev["id"]},
                "source": "module_agent",
            })
            results.append({"module": module["name"], "trigger": "field_change", "entry_id": entry_id, "queue_id": qid, "field": field, "to": new_val})
    return results


# ═══════════════════════════════════════════════════════════════════════
# ROUTER
# ═══════════════════════════════════════════════════════════════════════

router = APIRouter(tags=["module_agent"])


class ModuleCheckRequest(BaseModel):
    business_id: str


@router.post("/agents/module/check")
async def module_check(req: ModuleCheckRequest):
    async with httpx.AsyncClient() as client:
        businesses = await _sb(client, "GET", f"/businesses?id=eq.{req.business_id}&select=*&limit=1")
        if not businesses:
            raise HTTPException(404, "Business not found")
        biz = businesses[0]

        modules = await _sb(client, "GET",
            f"/custom_modules?business_id=eq.{req.business_id}&is_active=eq.true"
            f"&order=sort_order.asc&limit=50&select=*"
        ) or []

        all_results: List[Dict] = []
        per_module_stats: List[Dict] = []
        cap_remaining = PER_RUN_DRAFT_CAP

        entries_created_total = 0  # separate counter for internal-connection entries

        for module in modules:
            agent_config = module.get("agent_config") or {}
            if not agent_config.get("enabled", True):
                per_module_stats.append({"module": module["name"], "drafts_created": 0, "skipped_reason": "disabled"})
                continue

            module_results: List[Dict] = []

            # ── Draft-producing triggers ──────────────────────────────
            triggers = agent_config.get("triggers") or []
            for trigger in triggers:
                if cap_remaining <= 0:
                    break
                try:
                    ttype = trigger.get("type")
                    if ttype == "new_entry":
                        r = await _handle_new_entry(client, biz, module, trigger, cap_remaining)
                    elif ttype == "overdue":
                        r = await _handle_overdue(client, biz, module, trigger, cap_remaining)
                    elif ttype == "field_change":
                        r = await _handle_field_change(client, biz, module, trigger, cap_remaining)
                    else:
                        r = []
                    module_results.extend(r)
                    cap_remaining -= len(r)
                except Exception as e:
                    logger.exception(f"Trigger {trigger.get('type')} on module {module['name']} failed: {e}")

            # ── Internal-connection handlers (create entries, not drafts) ──
            internal_results: List[Dict] = []
            try:
                if agent_config.get("session_linked"):
                    internal_results.extend(await _handle_session_linked(client, biz, module))
                if agent_config.get("contact_linked"):
                    internal_results.extend(await _handle_contact_linked(client, biz, module))
                if agent_config.get("schedule"):
                    internal_results.extend(await _handle_scheduled(client, biz, module))
            except Exception as e:
                logger.exception(f"Internal connection on module {module['name']} failed: {e}")

            entries_created_total += len(internal_results)
            module_results.extend(internal_results)

            per_module_stats.append({
                "module": module["name"],
                "drafts_created": len([r for r in module_results if r.get("trigger") in ("new_entry", "overdue", "field_change")]),
                "entries_created": len(internal_results),
            })
            all_results.extend(module_results)

        drafts_count = len(all_results) - entries_created_total
        logger.info(
            f"Module check for {biz.get('name')}: {drafts_count} drafts, "
            f"{entries_created_total} auto-entries across {len(modules)} modules"
        )
        return {
            "business_id": req.business_id,
            "modules_checked": len(modules),
            "drafts_created": drafts_count,
            "entries_created": entries_created_total,
            "per_module": per_module_stats,
            "results": all_results,
        }


@router.get("/agents/module/health")
async def module_health():
    return {
        "status": "ok",
        "supabase_configured": bool(_supabase_url()),
        "anthropic_configured": bool(_anthropic_key()),
        "new_entry_lookback_hours": NEW_ENTRY_LOOKBACK_HOURS,
        "overdue_dedup_days": OVERDUE_DEDUP_DAYS,
        "per_run_cap": PER_RUN_DRAFT_CAP,
    }
