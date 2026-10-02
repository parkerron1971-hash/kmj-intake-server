"""Private care intake is owner-only and never enters marketing/AI pipelines."""
from fastapi import HTTPException
from urllib.parse import quote
import sb_clients

def needs_private_care(form, data):
    settings = form.get("settings") or {}
    answer = str(data.get("confidential", "")).strip().lower()
    # Prayer is sensitive by default, even when someone leaves the question blank.
    return (answer in ("yes", "true", "1", "on")
            or settings.get("private_care") is True
            or "prayer" in str(form.get("name", "")).lower()
            or any(str(k).lower() in ("prayer_request", "pastoral_care") and v for k, v in data.items()))

def save_submission(business_id, form_id, data):
    rows = sb_clients.sb_post_as_service("/ministry_care_requests", {
        "business_id": business_id, "form_id": form_id, "submission": data,
        "status": "new",
    })
    if not isinstance(rows, list) or not rows:
        raise HTTPException(503, "Your private request could not be saved. Please retry.")
    return {"success": True, "contact_id": None, "queued": False,
            "private": True, "message": "Your request was saved privately for the ministry owner."}

def require_owner(business_id, user):
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{quote(str(business_id), safe='')}&select=id,owner_id&limit=1")
    if not isinstance(rows, list):
        raise HTTPException(503, "Private care is temporarily unavailable")
    if not rows or str(rows[0].get("owner_id")) != str(user.id):
        raise HTTPException(403, "Private care requests are available only to the business owner")
