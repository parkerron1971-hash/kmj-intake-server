"""Website form contract. Limits are documented in docs/WEBSITE_FORMS.md."""
from typing import Any, Dict

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
    data = {key: _text(body.get(key) or "", key, limit)
            for key, limit in TEXT_LIMITS.items()}
    kind = _text(body.get("form") or "", "form", 80).replace("-", "_")
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
            raise ValueError(f"Unknown field: {key}.")
        if key == "interests":
            if not isinstance(value, list) or len(value) > 20:
                raise ValueError("interests must be a list of at most 20 items.")
            clean[key] = [_text(v, "interest", 120) for v in value]
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
    data.update(form=kind, fields=clean)
    return data


def notification_text(data: Dict[str, Any]) -> str:
    lines = [data["message"]] if data["message"] else []
    if data["phone"]:
        lines.append("Phone: " + data["phone"])
    for key, value in data["fields"].items():
        if isinstance(value, list):
            value = ", ".join(value)
        elif isinstance(value, bool):
            value = "Yes" if value else "No"
        lines.append(f"{key.replace('_', ' ').capitalize()}: {value}")
    return "\n".join(lines)
