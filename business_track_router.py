"""
business_track_router.py — the day-one plug-in list, resolved server-side.

WHY THE LIST LIVES HERE AND NOT IN THE FRONTEND
═══════════════════════════════════════════════════════════════════════
Two surfaces need the same answer to "what should this business switch on
first, and what have they already done?": the Business Session's exit ramp
and the checklist that sits at the top of BUILD. Computing it twice means
two lists that drift, and the failure mode is specific and bad — a card
that says "connect your bank" to someone who connected their bank a week
ago, or worse, a card pointing at a door that doesn't open.

So the catalog lives in business_track_actions.PLUGIN_CATALOG (which the
coach also recommends from, so the conversation and the checklist can
never disagree), and the "is it done?" probes live here, next to it.

EVERY PROBE MATCHES AN EXISTING READER
Each check below was taken from the code that already decides this
question somewhere else in the app, not invented. Where two readers
disagreed, the choice is commented. That matters more than it sounds:
a probe that is subtly wrong produces a checklist item that can never be
ticked off, which is worse than not showing it at all.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

import sb_clients
from auth_supabase import AuthedUser, require_user
import business_track_actions as bta

logger = logging.getLogger("business_track_router")

router = APIRouter(prefix="/business-track", tags=["business_track"])


def _gate(biz_id: str, user: AuthedUser, min_role: str = "member") -> Dict[str, Any]:
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{biz_id}"
        f"&select=id,name,type,owner_id,settings,stripe_account_id&limit=1") or []
    if not rows:
        raise HTTPException(404, "business not found")
    from business_users_router import require_role
    require_role(biz_id, str(user.id), min_role)
    return rows[0]


def _exists(path: str) -> bool:
    try:
        return bool(sb_clients.sb_get_as_service(path))
    except Exception as e:  # a probe must never break the page
        logger.warning(f"[plugins] probe failed ({path}): {e}")
        return False


# ═══════════════════════════════════════════════════════════════════════
# PROBES
# ═══════════════════════════════════════════════════════════════════════

# An import leaves its mark on contacts.source: contacts_import_router
# writes "csv_import", and a people sheet in the structure import is
# handed to that same importer, so it does too. Matched as *import* so an
# importer added later ("vcard_import", …) counts without a second edit.
IMPORT_SOURCE_PATTERN = "*import*"


def _done_import_contacts(biz: Dict[str, Any]) -> bool:
    """The client list came over: an import ran, OR the business holds a
    real list (bta.REAL_CLIENT_LIST_MIN people).

    Until 2026-09-26 this was plain existence — ONE contact ticked "Bring
    your client list over", so the step meant to bring the list was done
    the moment someone typed a single name. Hand-typed people still count
    exactly as much as imported ones (a practitioner who typed their
    regulars in has brought them over); one of them is just not the list.
    The count reads every contacts row with no source or status filter —
    the same rows maturity_engine's contact_count signal counts."""
    bid = biz["id"]
    if _exists(f"/contacts?business_id=eq.{bid}"
               f"&source=like.{IMPORT_SOURCE_PATTERN}&select=id&limit=1"):
        return True
    try:
        rows = sb_clients.sb_get_as_service(
            f"/contacts?business_id=eq.{bid}&select=id"
            f"&limit={bta.REAL_CLIENT_LIST_MIN}") or []
    except Exception as e:  # a probe must never break the page
        logger.warning(f"[plugins] contact count probe failed: {e}")
        return False
    return isinstance(rows, list) and len(rows) >= bta.REAL_CLIENT_LIST_MIN


def _done_offerings(biz: Dict[str, Any]) -> bool:
    # is_active is the live flag, not a status string; archived_at is not
    # used as a filter anywhere else, so it isn't used here either.
    return _exists(f"/offerings?business_id=eq.{biz['id']}"
                   f"&is_active=eq.true&select=id&limit=1")


def _done_payments(biz: Dict[str, Any]) -> bool:
    """Three independent truths, any of which means money can arrive.

    stripe_account_id is a COLUMN on businesses (the Connect account) —
    not settings.payment_providers.stripe.connect_account_id, which is
    documented as 'future, null today' and would silently never match.
    """
    if (biz.get("stripe_account_id") or "").strip():
        return True
    settings = biz.get("settings") or {}
    providers = settings.get("payment_providers") or {}
    for key in ("stripe", "square", "paypal"):
        slot = providers.get(key) or {}
        if slot.get("enabled") and (slot.get("manual_link") or "").strip():
            return True
    # Legacy single-link shape, still live for early businesses.
    return bool(((settings.get("payments") or {}).get("stripe_link") or "").strip())


def _done_availability(biz: Dict[str, Any]) -> bool:
    """'Open by default' (no weekly ranges, no overrides, no blocks) is
    how the booking engine represents NOT CONFIGURED — so an untouched
    business must not read as done."""
    settings = biz.get("settings") or {}
    try:
        from availability_router import _is_open_default_dict
        return not _is_open_default_dict(settings.get("availability"))
    except Exception as e:
        logger.warning(f"[plugins] availability probe failed: {e}")
        return False


def _done_site(biz: Dict[str, Any]) -> bool:
    """status='booking_only' is a stub row that exists purely to host the
    booking page — it is not a website, and counting it would tick this
    off for someone who has never made one."""
    rows = sb_clients.sb_get_as_service(
        f"/business_sites?business_id=eq.{biz['id']}&status=eq.published"
        f"&select=id,site_config&limit=1") or []
    if not rows:
        return False
    # site_config.offline takes a published site down behind a "back soon"
    # page. Still built, so still done.
    return True


def _done_bank(biz: Dict[str, Any]) -> bool:
    # Lenient form (status != revoked): an item needing re-auth was still
    # linked, and telling that practitioner to "link your bank" is wrong.
    return _exists(f"/plaid_items?business_id=eq.{biz['id']}"
                   f"&status=not.eq.revoked&select=item_id&limit=1")


def _done_quickbooks(biz: Dict[str, Any]) -> bool:
    # quickbooks_connections has RLS enabled with ZERO policies (tokens
    # live there) — this MUST go through the service role or it reports
    # "not connected" for everyone.
    return _exists(f"/quickbooks_connections?business_id=eq.{biz['id']}"
                   f"&status=eq.connected&select=business_id&limit=1")


def _done_email_domain(biz: Dict[str, Any]) -> bool:
    """The same full conjunction email_sender uses to decide whether to
    actually send from the custom identity. A half-configured domain
    never sends, so it must not tick."""
    settings = biz.get("settings") or {}
    cfg = settings.get("email_domain") or {}
    local = (cfg.get("from_local_part") or "").strip()
    return bool(cfg.get("status") == "verified"
                and (cfg.get("domain") or "").strip()
                and local and "@" not in local)


def _done_site_domain(biz: Dict[str, Any]) -> bool:
    rows = sb_clients.sb_get_as_service(
        f"/business_sites?business_id=eq.{biz['id']}"
        f"&select=site_config&limit=1") or []
    cfg = (rows[0].get("site_config") or {}) if rows else {}
    return bool(cfg.get("custom_domain")
                and cfg.get("custom_domain_status") == "verified")


def _done_brand(biz: Dict[str, Any]) -> bool:
    """bool(brand_kit) is the flag brand_engine exposes, but it is true
    for a normalized-empty kit (_normalize_brand_kit always stamps
    'assets'). Probe the owner-set signals instead, in BOTH the nested and
    flat shapes — rows written by older code only carry the flat keys."""
    bk = (biz.get("settings") or {}).get("brand_kit") or {}
    colors = bk.get("colors") or {}
    fonts = bk.get("font_pair") or {}
    return bool(colors.get("primary") or bk.get("primary_color")
                or fonts.get("heading") or bk.get("font_heading"))


# The generic form complete_strategy_track seeds for everyone
# (chief_strategy_actions._seed_default_intake_form): a name/email/phone/
# message contact form. Left exactly as seeded it is not the intake form
# this step asks for, so it must not tick the step on its own.
_SEEDED_FORM_FIELDS = frozenset({"name", "email", "phone", "message"})


def _is_untouched_seed(form: Dict[str, Any]) -> bool:
    fields = form.get("fields") or []
    if not isinstance(fields, list):
        return False
    names = {str((f or {}).get("name") or "") for f in fields if isinstance(f, dict)}
    return len(fields) == len(_SEEDED_FORM_FIELDS) and names == _SEEDED_FORM_FIELDS


def _done_intake_form(biz: Dict[str, Any]) -> bool:
    """An active client form the practitioner made or shaped — the same
    is_active flag the public submit door and the composed site read."""
    rows = sb_clients.sb_get_as_service(
        f"/intake_forms?business_id=eq.{biz['id']}&is_active=eq.true"
        f"&select=id,fields&limit=20") or []
    return any(not _is_untouched_seed(r) for r in rows if isinstance(r, dict))


def _done_giving(biz: Dict[str, Any]) -> bool:
    """giving_router.giving_is_active, the ONE rubric the give page, the
    checkout and the composer already share: the vertical can give,
    giving is switched on, and Stripe is connected. Re-read here because
    not every caller of resolve_plugins passes stripe_account_id, and a
    missing column would read as "not connected" for everyone."""
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{biz['id']}"
        f"&select=id,type,settings,stripe_account_id&limit=1") or []
    if not rows:
        return False
    from giving_router import giving_is_active
    return bool(giving_is_active(rows[0]))


def _done_meta(biz: Dict[str, Any]) -> bool:
    return _exists(f"/social_accounts?business_id=eq.{biz['id']}"
                   f"&provider=eq.meta&status=eq.connected&select=page_id&limit=1")


def _done_concierge(biz: Dict[str, Any]) -> bool:
    # settings.concierge.enabled only. site_concierge.is_enabled also ANDs
    # a feature gate, but that is a billing-tier concern — not something
    # the practitioner did or failed to do.
    cfg = (biz.get("settings") or {}).get("concierge") or {}
    return bool(cfg.get("enabled"))


PROBES = {
    "import_contacts": _done_import_contacts,
    "offerings":       _done_offerings,
    "intake_form":     _done_intake_form,
    "giving":          _done_giving,
    "payments":        _done_payments,
    "availability":    _done_availability,
    "site":            _done_site,
    "bank":            _done_bank,
    "quickbooks":      _done_quickbooks,
    "email_domain":    _done_email_domain,
    "site_domain":     _done_site_domain,
    "brand":           _done_brand,
    "meta":            _done_meta,
    "concierge":       _done_concierge,
}


def _probe(key: str, biz: Dict[str, Any]) -> bool:
    fn = PROBES.get(key)
    if not fn:
        return False
    try:
        return bool(fn(biz))
    except Exception as e:
        logger.warning(f"[plugins] probe '{key}' raised: {e}")
        return False


# ═══════════════════════════════════════════════════════════════════════
# ENDPOINT
# ═══════════════════════════════════════════════════════════════════════

def resolve_plugins(biz: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The ordered plug-in list for one business.

    Order of preference:
      1. What the coach chose in the Business Track's 'plan' phase — it
         knows why each one matters to THIS business.
      2. The vertical default ordering, for anyone who hasn't finished
         (or started) the track.

    Either way every key is validated against the catalog before it is
    returned, so a coach that hallucinates a plug-in name can't put a
    dead card on someone's dashboard.
    """
    biz_id = biz["id"]
    chosen: List[str] = []
    reasons: Dict[str, str] = {}

    rows = sb_clients.sb_get_as_service(
        f"/business_tracks?business_id=eq.{biz_id}"
        f"&order=created_at.desc&limit=1&select=first_30_days,operations_map") or []
    plan = (rows[0].get("first_30_days") or {}) if rows else {}
    ops = (rows[0].get("operations_map") or {}) if rows else {}
    if not isinstance(ops, dict):
        ops = {}
    # Where their clients live — the onboarding answer plus any tool the
    # Business Session heard — so the import step's "how" can walk them
    # through THAT export instead of asking for one name.
    settings = biz.get("settings") if isinstance(biz.get("settings"), dict) else {}
    sources = bta.client_sources_for(settings, ops.get("tools_in_use"))
    other = bta.stored_client_sources(settings)["other"]
    for entry in (plan.get("plugins") or []):
        # Tolerate both a bare key and {key, why} — the coach writes keys,
        # but a richer shape is the obvious next thing someone adds.
        if isinstance(entry, str):
            key, why = entry, None
        elif isinstance(entry, dict):
            key, why = entry.get("key"), entry.get("why")
        else:
            continue
        if key in bta.PLUGIN_CATALOG and key not in chosen:
            chosen.append(key)
            if why:
                reasons[key] = str(why)[:400]

    if not chosen:
        chosen = bta.plugins_for_vertical(biz.get("type"))

    done_map = {k: _probe(k, biz) for k in chosen}

    out: List[Dict[str, Any]] = []
    for key in chosen:
        spec = bta.PLUGIN_CATALOG[key]
        # A prerequisite that isn't met yet is worth SAYING, not hiding —
        # "point your domain at your site" makes no sense before there is
        # a site, and silently dropping it looks like the list forgot.
        # Only prerequisites this vertical HAS count: a ministry has no
        # offerings step, so its site never waits on one.
        # (done_map first: .get(n, _probe(...)) ran the probe every time.)
        blocked = [n for n in bta.needs_for(key, biz.get("type"))
                   if not (done_map[n] if n in done_map else _probe(n, biz))]
        out.append({
            "key": key,
            "title": spec["title"],
            "why": reasons.get(key) or spec["why"],
            "nav": spec["nav"],
            "done": done_map[key],
            "blocked_by": blocked,
            # Added 2026-09-26 (existing keys unchanged): how Chief does
            # this step for THIS business — the catalog line, tailored for
            # the import step to where their clients live.
            "how": bta.plugin_how(key, sources, other),
        })

    # Undone first, then blocked ones after the things that unblock them.
    out.sort(key=lambda p: (p["done"], bool(p["blocked_by"])))
    return out


@router.get("/{business_id}/plugins")
def plugins(business_id: str,
            user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """What this business should plug in, and what it already has."""
    biz = _gate(business_id, user, "member")
    items = resolve_plugins(biz)
    return {
        "ok": True,
        "plugins": items,
        "done_count": sum(1 for p in items if p["done"]),
        "total": len(items),
    }


class ClientSourcesBody(BaseModel):
    """Where this business's clients live today. `sources` are keys of
    business_track_actions.CLIENT_SOURCES; anything else is dropped.
    `other` is their own words for a tool not on the list."""
    sources: List[str] = Field(default_factory=list, max_length=20)
    other: Optional[str] = Field(default=None, max_length=120)
    via: Optional[str] = Field(default="onboarding", max_length=40)


@router.put("/{business_id}/client-sources")
def put_client_sources(business_id: str, body: ClientSourcesBody,
                       user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """Store where the clients live (settings.client_sources). Owner only:
    it is written once at onboarding, by the person who just created the
    business, and it steers what Chief asks them to bring over. Replaces
    the stored answer — this is the practitioner saying it themselves."""
    _gate(business_id, user, "owner")
    value = bta.save_client_sources(business_id, body.sources, body.other,
                                    via=(body.via or "onboarding"))
    if not value:
        raise HTTPException(502, "could not save where your clients live")
    return {
        "ok": True,
        "client_sources": value,
        "labels": [bta.CLIENT_SOURCES[k]["label"] for k in value["sources"]],
    }
