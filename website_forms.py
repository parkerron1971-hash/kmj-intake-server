"""Website form contract. Limits are documented in docs/WEBSITE_FORMS.md."""
from typing import Any, Dict
import hashlib
import json
import uuid

PLAIN_TEXT_LIMIT = 100_000
HISTORY_LIMIT = 10
APP_URL = "https://mysolutionist.app"
# Kevin can opt in later; default notices never carry private content.
PRAYER_EMAIL_INCLUDE_CONTENT = False

TEXT_LIMITS = {"name": 200, "email": 200, "phone": 40, "message": 5000}
FIELD_LIMITS = {
    "first_name": 90, "last_name": 90, "visits": 120,
    "heard_from": 200, "notes": 2500, "request": 4000,
}


def _text(value: Any, label: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be text.")
    if len(value) > maximum:
        raise ValueError(f"{label} must be at most {maximum} characters.")
    return value.strip()


def validate(body: Dict[str, Any]) -> Dict[str, Any]:
    kind = _text(body.get("form") or "", "form", 80).replace("-", "_")
    church = kind in ("connect_card", "prayer_request")
    data = {}
    for key, limit in TEXT_LIMITS.items():
        value = body.get(key) or ""
        if not church and isinstance(value, str):
            value = value[:PLAIN_TEXT_LIMIT if key == "message" else limit]
        data[key] = _text(value, key, limit if church or key != "message" else PLAIN_TEXT_LIMIT)
    # Unrecognized form labels used to be ignored; keep plain callers working.
    fields = body.get("fields", {})
    if not isinstance(fields, dict):
        raise ValueError("fields must be an object.")
    if fields and kind not in ("connect_card", "prayer_request"):
        raise ValueError("Structured fields require connect_card or prayer_request.")
    allowed = {"first_name", "last_name"}
    allowed |= ({"visits", "heard_from", "interests", "notes"} if kind == "connect_card"
                else {"request", "follow_up"})
    clean = {}
    for key, value in fields.items():
        if key not in allowed:
            raise ValueError("Unknown structured field.")
        if key == "interests":
            if not isinstance(value, list) or len(value) > 20:
                raise ValueError("interests must be a list of at most 20 items.")
            clean[key] = [_text(v, "interest", 120) for v in value]
            if any(not v for v in clean[key]):
                raise ValueError("Interests must not be empty.")
        elif key == "follow_up":
            if not isinstance(value, bool):
                raise ValueError("follow_up must be true or false.")
            clean[key] = value
        else:
            clean[key] = _text(value, key, FIELD_LIMITS[key])
    if not data["name"] or not data["email"]:
        raise ValueError("Name and email are required.")
    email = data["email"]
    if "@" not in email or "." not in email or any(c.isspace() for c in email):
        raise ValueError("Invalid email.")
    if kind == "prayer_request" and "fields" in body and not clean.get("request"):
        raise ValueError("A prayer request is required.")
    if not data["message"] and not clean:
        raise ValueError("A message is required.")
    data.update(form=kind, fields=clean,
                submission_id=_text(body.get("submission_id") or "", "submission_id", 80))
    return data


def notification_text(data: Dict[str, Any]) -> str:
    lines = [data["message"]] if data["message"] else []
    if data["phone"]:
        lines.append("Phone: " + data["phone"])
    for key, value in ({} if data["message"] else data["fields"]).items():
        if isinstance(value, list):
            value = ", ".join(value)
        elif isinstance(value, bool):
            value = "Yes" if value else "No"
        lines.append(f"{key.replace('_', ' ').capitalize()}: {value}")
    return "\n".join(lines)


def receipt_id(business_id: str, data: Dict[str, Any]) -> str:
    """Scope retry identity to both tenant and answers, never a visitor's key alone.

    Updated forms send a fresh submission_id per deliberate submission. Without
    a key, identical answers cannot distinguish a retry from a new submission;
    preserve each legacy submission rather than silently dropping later messages.
    """
    if not data.get("submission_id"):
        return str(uuid.uuid4())
    encoded = json.dumps([business_id, data], sort_keys=True, ensure_ascii=False)
    digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "website-form:" + digest))


def stored_row(table: str, row_id: str, business_id: str):
    from urllib.parse import quote
    import sb_clients
    rows = sb_clients.sb_get_as_service(
        f"/{table}?id=eq.{quote(row_id, safe='')}&business_id=eq.{quote(business_id, safe='')}&limit=1")
    if not isinstance(rows, list):
        raise RuntimeError(f"{table} receipt lookup failed")
    return rows[0] if rows else None


def store_once(table: str, row: Dict[str, Any]):
    """Primary-key conflict means retry: never overwrite an edited note/status.

    Check the scoped row after a conflict; an unconfirmed write can retry safely.
    A returned id is required before acknowledging storage.
    """
    import sb_clients
    rows = sb_clients.sb_post_as_service(
        "/" + table, row, prefer="resolution=ignore-duplicates,return=representation")
    if isinstance(rows, list) and rows and rows[0].get("id"):
        return rows[0]
    if rows == []:
        existing = stored_row(table, row["id"], row["business_id"])
        if existing and existing.get("id"):
            return existing
    raise RuntimeError(f"{table} write did not confirm storage")


def save_prayer(business_id: str, data: Dict[str, Any], receipt: str):
    return store_once("ministry_care_requests", {
        "id": receipt, "business_id": business_id, "form_id": None, "status": "new",
        "submission": {
            "name": data["name"], "email": data["email"], "phone": data["phone"],
            "prayer_request": data["fields"].get("request") or data["message"],
            "message": data["message"], "fields": data["fields"],
            "follow_up": data["fields"].get("follow_up", False),
            "confidential": "yes", "source": "website prayer request",
        },
    })


async def alert_church(business_id: str, kind: str, receipt: str):
    """Use the notification preference gate, retaining atomic retry identity."""
    import httpx
    from notification_engine import create_urgent_alert
    prayer = kind == "prayer_request"
    async with httpx.AsyncClient() as client:
        return await create_urgent_alert(
            client, business_id,
            "New prayer request" if prayer else "New connect card",
            ("A new prayer request is waiting in Prayer & care" if prayer else
             "A new connect card is waiting in Members. Open the person's Notes to read it."),
            notification_id=str(uuid.uuid5(uuid.UUID(receipt), "notification")),
            priority="normal",
            suggested_action="Open forms" if prayer else "Open Members",
            action_payload={"type": "navigate", "tab": "build" if prayer else "operate",
                            "sub": "intake-forms" if prayer else "contacts"},
        )
