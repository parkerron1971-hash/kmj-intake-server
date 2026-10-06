"""post_for_me.py — the one place that talks to Post for Me.

Post for Me (api.postforme.dev) is the posting service a business's
social accounts connect through (Kevin, 2026-09-28: practitioners publish
via Post for Me; 2026-10-04: the account is live, Quickstart mode). It is
headless — every screen a practitioner sees is ours; the only moment they
leave is the social network's own sign-in.

THE RULE THIS MODULE EXISTS TO KEEP
A Post for Me social-account object carries the network's ACCESS and
REFRESH TOKENS for that person's Instagram / Facebook / TikTok. Nothing
outside this file ever sees them: every account that leaves here has been
through public_account(), which keeps an allow-list of display fields and
drops everything else. Nothing here logs a response body.

The key (POST_FOR_ME_API_KEY) is an admin key for the whole Post for Me
project. Server only — it never reaches the browser or Chief.

Quickstart vs white label: Quickstart uses Post for Me's own approved
network apps, so the network's permission screen names "Post for Me" and
the project's redirect URL is set in THEIR dashboard (redirect overrides
are refused). Bringing our own network credentials later changes the
project settings, not this code.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger("post_for_me")
if not logger.handlers:
    # Root is at WARNING in production; a module logger needs its own
    # handler or its INFO lines never print.
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] post_for_me: %(message)s"))
    logger.addHandler(_h)
    logger.setLevel(logging.INFO)

BASE = "https://api.postforme.dev/v1"
TIMEOUT = 20.0

# Every network we know how to connect, in the order the card offers them.
# (Post for Me also has bluesky and tiktok_business; not offered yet.)
PLATFORMS = ("instagram", "facebook", "tiktok", "x", "linkedin", "youtube",
             "pinterest", "threads")

# The ones switched on in OUR Post for Me project (its dashboard → Setup).
# A network that is off there has no sign-in to hand out, so offering its
# button would be a dead end. Kept as a setting because the dashboard is
# where it changes. On 2026-10-05: Facebook, Instagram, TikTok, X, YouTube.
_DEFAULT_ENABLED = "instagram,facebook,tiktok,x,youtube"


def enabled_platforms() -> tuple:
    """POST_FOR_ME_PLATFORMS (comma-separated), in PLATFORMS order; unknown
    names ignored."""
    raw = os.environ.get("POST_FOR_ME_PLATFORMS") or _DEFAULT_ENABLED
    wanted = {x.strip().lower() for x in raw.split(",") if x.strip()}
    return tuple(p for p in PLATFORMS if p in wanted)

# Display fields only. Anything not named here — access_token,
# refresh_token, their expiry stamps, provider metadata — is dropped.
_PUBLIC_FIELDS = ("id", "platform", "username", "user_id", "profile_photo_url",
                  "status", "external_id")


class PostForMeError(RuntimeError):
    """A Post for Me call failed. `status` is the HTTP status (0 = no answer)."""

    def __init__(self, message: str, status: int = 0):
        super().__init__(message)
        self.status = status


def api_key() -> str:
    return (os.environ.get("POST_FOR_ME_API_KEY") or "").strip()


def configured() -> bool:
    return bool(api_key())


def pilot_businesses() -> frozenset:
    """Businesses allowed to connect and post (comma-separated ids in
    POST_FOR_ME_PILOT_BUSINESSES), or "*" for every business. Kevin
    opened it to every business on 2026-10-05; posting is in every
    marketing level (Basics included), so "*" takes nothing away later.
    Unset or empty = off everywhere."""
    raw = os.environ.get("POST_FOR_ME_PILOT_BUSINESSES") or ""
    return frozenset(x.strip() for x in raw.split(",") if x.strip())


def allowed_for(business_id: str) -> bool:
    if not configured() or not business_id:
        return False
    allowed = pilot_businesses()
    return "*" in allowed or str(business_id) in allowed


def public_account(acct: Dict[str, Any]) -> Dict[str, Any]:
    """A social account with only its display fields. See the module rule."""
    return {k: acct.get(k) for k in _PUBLIC_FIELDS if k in acct}


def _headers() -> Dict[str, str]:
    key = api_key()
    if not key:
        raise PostForMeError("Post for Me is not configured on the server.")
    return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}


async def _request(method: str, path: str, *, params: Any = None,
                   json: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as c:
            r = await c.request(method, f"{BASE}{path}", headers=_headers(),
                                params=params, json=json)
    except httpx.HTTPError as e:
        logger.warning("[post_for_me] %s %s: no answer (%s)", method, path, type(e).__name__)
        raise PostForMeError("Post for Me did not answer.") from e
    if r.status_code >= 400:
        # Status only: a body can echo request data back.
        logger.warning("[post_for_me] %s %s -> %s", method, path, r.status_code)
        raise PostForMeError(f"Post for Me answered {r.status_code}.", r.status_code)
    try:
        return r.json() if r.content else {}
    except ValueError:
        return {}


async def auth_url(platform: str, external_id: str) -> str:
    """The network sign-in link that connects one account to `external_id`
    (our business id). Instagram uses Instagram login, so a business or
    creator account connects without a Facebook Page. LinkedIn must be an
    organization connection on Quickstart credentials."""
    if platform not in PLATFORMS:
        raise PostForMeError(f"Unknown network: {platform}")
    body: Dict[str, Any] = {"platform": platform, "external_id": external_id,
                            # "feeds" now, so reading a post's results later
                            # doesn't make every owner reconnect.
                            "permissions": ["posts", "feeds"]}
    if platform == "instagram":
        body["platform_data"] = {"instagram": {"connection_type": "instagram"}}
    elif platform == "linkedin":
        body["platform_data"] = {"linkedin": {"connection_type": "organization"}}
    out = await _request("POST", "/social-accounts/auth-url", json=body)
    url = out.get("url")
    if not isinstance(url, str) or not url.startswith("https://"):
        raise PostForMeError("Post for Me returned no sign-in link.")
    return url


async def accounts_for(external_id: str) -> List[Dict[str, Any]]:
    """Every account Post for Me holds for this business, display fields only."""
    out = await _request("GET", "/social-accounts",
                         params=[("external_id", external_id), ("limit", "100")])
    data = out.get("data") if isinstance(out, dict) else out
    return [public_account(a) for a in (data or []) if isinstance(a, dict) and a.get("id")]


async def accounts_by_ids(account_ids: List[str]) -> List[Dict[str, Any]]:
    """Specific accounts by Post for Me id, whatever business they're
    labelled with now, display fields only."""
    if not account_ids:
        return []
    params = [("id", i) for i in account_ids] + [("limit", "100")]
    out = await _request("GET", "/social-accounts", params=params)
    data = out.get("data") if isinstance(out, dict) else out
    return [public_account(a) for a in (data or []) if isinstance(a, dict) and a.get("id")]


def media_item(item: Any) -> Dict[str, Any]:
    """One media entry of a post: a URL, or {url, thumbnail_url} for a video
    with its cover (Post for Me's SocialPostMediaDto; the thumbnail is a
    public image URL it fetches, like the media)."""
    if isinstance(item, dict):
        out: Dict[str, Any] = {"url": item["url"]}
        if item.get("thumbnail_url"):
            out["thumbnail_url"] = item["thumbnail_url"]
        return out
    return {"url": item}


async def create_post(*, caption: str, account_ids: List[str], media_urls: List[Any],
                      external_id: str, scheduled_at: Optional[str] = None,
                      platform_configurations: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Hand one post to Post for Me. No scheduled_at = post now. Media go by
    public URL (Post for Me fetches them); an item may be {url, thumbnail_url}
    (see media_item). platform_configurations overrides per network: its
    own media (a different thumbnail), placement, a YouTube title. Returns
    {id, status}."""
    body: Dict[str, Any] = {"caption": caption, "social_accounts": account_ids,
                            "external_id": external_id,
                            "media": [media_item(u) for u in media_urls]}
    if scheduled_at:
        body["scheduled_at"] = scheduled_at
    if platform_configurations:
        body["platform_configurations"] = platform_configurations
    out = await _request("POST", "/social-posts", json=body)
    if not out.get("id"):
        raise PostForMeError("Post for Me didn't accept the post.")
    return {"id": out["id"], "status": out.get("status")}


async def post_results(post_id: str) -> List[Dict[str, Any]]:
    """One result per account the post went to: success, error, and the
    live post's link (platform_data.url)."""
    out = await _request("GET", "/social-post-results",
                         params=[("post_id", post_id), ("limit", "100")])
    data = out.get("data") if isinstance(out, dict) else out
    keep = []
    for r in data or []:
        if not isinstance(r, dict):
            continue
        pd = r.get("platform_data") or {}
        keep.append({"social_account_id": r.get("social_account_id"),
                     "success": bool(r.get("success")),
                     "error": (str(r.get("error"))[:300] if r.get("error") else None),
                     "url": pd.get("url") if isinstance(pd, dict) else None})
    return keep


async def upload_slot() -> Dict[str, str]:
    """A place to put one photo or video: {upload_url, media_url}. The
    upload URL is signed for a short time and for that one file, so it is
    safe to hand to the browser, which PUTs the file straight to Post for
    Me (large videos never pass through our server). media_url is the
    public link a post then names."""
    out = await _request("POST", "/media/create-upload-url")
    up, media = out.get("upload_url"), out.get("media_url")
    if not (isinstance(up, str) and up.startswith("https://")
            and isinstance(media, str) and media.startswith("https://")):
        raise PostForMeError("Post for Me returned no upload link.")
    return {"upload_url": up, "media_url": media}


async def cancel_post(post_id: str) -> None:
    """Post for Me deletes a post only while it is still scheduled."""
    await _request("DELETE", f"/social-posts/{post_id}")


async def disconnect(account_id: str) -> None:
    """Removes the network tokens at Post for Me; the record stays there."""
    await _request("POST", f"/social-accounts/{account_id}/disconnect")
