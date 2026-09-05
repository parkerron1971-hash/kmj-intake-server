"""
chief_offering_actions.py — offerings, the wired-site contract, live
site copy, and availability.

Split out of chief_of_staff.py on 2026-09-04, the fourth slice of
"split the monolith along the registry" (after strategy, grow and
custom modules). Nineteen verbs, their constants and private helpers,
bodies byte-identical to where they were.

WHAT LIVES HERE
  Offerings, the canonical pricing layer (create / update / archive /
  list, plus setup_store and offering_readiness); the wired-site
  contract (set_site_capability); site copy, live (edit_site_text /
  revert_site_text, one text spot at a time through the override
  system); and availability (the weekly grid, overrides, block ranges,
  slot granularity, lead time, timezone, and the read).

WHAT STAYED BEHIND, AND WHY. Four private helpers stay in
chief_of_staff — _find_offering_by_name, _refresh_composed_site_bg,
_site_text_targets, _site_text_refresh_if_composed — because the tests
monkeypatch them THROUGH `cos.` (test_inventory, test_trust_hardening,
test_edit_site_text), and chief_inventory_actions imports the first
from chief_of_staff. The handlers here reach them by the same names
through call-time delegators, so a patch on chief_of_staff is what a
handler sees, exactly as before the move. _site_text_plain moved with
its callers and chief_of_staff imports it back for _site_text_targets.

HOST HELPERS. _sb, _fail, _nav and FALLBACK_BASE (the service's own
public address, used by setup_store) come from chief_host.

REGISTRATION. chief_of_staff imports every handle_* by name, so
`chief_of_staff.handle_edit_site_text` is the same function object the
tests drive and read the source of.
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

import module_vocabulary
import sb_clients

from chief_host import _sb, _fail, _nav, FALLBACK_BASE

# Same logger name as the file this came from.
logger = logging.getLogger("chief_of_staff")


# ─── Helpers the tests patch through chief_of_staff (see header) ───────

async def _find_offering_by_name(client, biz_id: str, name: str) -> Optional[Dict[str, Any]]:
    from chief_of_staff import _find_offering_by_name as _real
    return await _real(client, biz_id, name)


def _refresh_composed_site_bg(business_id: str) -> None:
    from chief_of_staff import _refresh_composed_site_bg as _real
    return _real(business_id)


def _site_text_targets(*args, **kwargs):
    from chief_of_staff import _site_text_targets as _real
    return _real(*args, **kwargs)


def _site_text_refresh_if_composed(*args, **kwargs):
    from chief_of_staff import _site_text_refresh_if_composed as _real
    return _real(*args, **kwargs)


# ─────────────────────────────────────────────────────────────────────
# Offerings (Phase C.1.2) — canonical pricing layer
# ─────────────────────────────────────────────────────────────────────
# Siblings of handle_create_product / handle_update_product / etc.
# Targets the offerings table (not products). Used by Chief when the
# practitioner says "change my haircut price" / "add a 60-min massage at
# $90" / "list my services" — anything service-pricing-shaped.
#
# 'donation' is intentionally NOT a valid category — Fork 25 Giving guard.

# Derived from module_vocabulary.py — the one place the category set is
# written down. A set typed out beside a Literal is how they drift.
_VALID_OFFERING_CATEGORIES = module_vocabulary.VALID_OFFERING_CATEGORIES

def _slugify_offering(s: str) -> str:
    import re
    s = (s or "").strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s or "offering"

async def handle_create_offering(client, biz, action) -> Dict:
    """Create a new offering. action: {name, category, current_price?,
    duration_min?, currency?, description?, show_price_to_customer?, slug?}
    """
    name = (action.get("name") or "").strip()
    if not name:
        return _fail("create_offering", "name required")
    category = (action.get("category") or "service").strip().lower()
    if category not in _VALID_OFFERING_CATEGORIES:
        return _fail(
            "create_offering",
            f"category must be one of {sorted(_VALID_OFFERING_CATEGORIES)} "
            f"(donations stay in the restricted-modules domain)"
        )
    slug = (action.get("slug") or _slugify_offering(name)).lower()

    # Idempotency — refuse if a same-slug offering already exists for this biz.
    existing = await _sb(client, "GET",
        f"/offerings?business_id=eq.{biz['id']}&slug=eq.{slug}&select=id,name&limit=1")
    if existing:
        return _fail(
            "create_offering",
            f"an offering with slug '{slug}' already exists "
            f"(currently named '{existing[0].get('name')}'). "
            f"Try update_offering instead, or pick a different name."
        )

    payload: Dict[str, Any] = {
        "business_id": biz["id"],
        "name": name,
        "slug": slug,
        "category": category,
        "is_active": True,
    }
    if action.get("description") is not None:
        payload["description"] = action["description"]
    if action.get("currency"):
        payload["currency"] = action["currency"]
    if action.get("show_price_to_customer") is not None:
        payload["show_price_to_customer"] = bool(action["show_price_to_customer"])
    # Arc 27 — store product fields (sellable categories surface in the
    # hosted storefront; harmless no-ops for service/session categories).
    if (action.get("image_url") or "").strip():
        payload["image_url"] = str(action["image_url"]).strip()[:600]
    if (action.get("sku") or "").strip():
        payload["sku"] = str(action["sku"]).strip()[:80]
    if action.get("inventory_qty") is not None:
        try:
            payload["inventory_qty"] = max(0, int(action["inventory_qty"]))
        except (TypeError, ValueError):
            return _fail("create_offering", f"invalid inventory_qty: {action.get('inventory_qty')!r}")
    if action.get("requires_shipping") is not None:
        payload["requires_shipping"] = bool(action["requires_shipping"])
    if (action.get("fulfillment_note") or "").strip():
        payload["fulfillment_note"] = str(action["fulfillment_note"]).strip()[:600]
    # Numeric coercions
    if "current_price" in action or "price" in action:
        raw = action.get("current_price", action.get("price"))
        try:
            payload["current_price"] = float(raw) if raw is not None else None
        except (TypeError, ValueError):
            return _fail("create_offering", f"invalid price: {raw!r}")
    if "duration_min" in action or "duration_minutes" in action or "duration" in action:
        raw = action.get("duration_min", action.get("duration_minutes", action.get("duration")))
        try:
            payload["duration_min"] = int(raw) if raw is not None else None
            if payload["duration_min"] is not None and payload["duration_min"] <= 0:
                return _fail("create_offering", "duration_min must be > 0")
        except (TypeError, ValueError):
            return _fail("create_offering", f"invalid duration_min: {raw!r}")

    rows = await _sb(client, "POST", "/offerings", payload)
    if not rows:
        return _fail("create_offering", "create failed")
    off = rows[0]
    price_str = f" at ${off.get('current_price')}" if off.get("current_price") is not None else ""
    dur_str = f" ({off['duration_min']} min)" if off.get("duration_min") else ""
    # Arc 27 — sellable categories with a price go live in the hosted
    # storefront automatically; say so in the label so the second-pass
    # reply tells the practitioner where the thing actually went.
    store_str = (" — live in your store" if category in ("product", "course", "package")
                 and off.get("current_price") else "")
    # THE WIRED-SITE CONTRACT (2026-07-26): a bookable offering's reply
    # states the SITE truth — where booking already lives, and how to
    # put the door on the website when the site plan doesn't carry it.
    site_note = ""
    if category in ("service", "session"):
        try:
            import offering_profiles
            state = await asyncio.to_thread(
                offering_profiles.business_state, str(biz["id"]))
            if state.get("booking_enabled") and state.get("booking_url"):
                site_note = f" — bookable at {state['booking_url']}"
                sites = await _sb(client, "GET",
                    f"/business_sites?business_id=eq.{biz['id']}"
                    "&select=site_config&limit=1")
                caps = ((((sites[0].get("site_config") or {})
                          .get("discovery_dossier") or {})
                         .get("capabilities") or {}) if sites else {})
                leaf = caps.get("booking") or {}
                if str(leaf.get("value")).strip().lower() != "on":
                    site_note += (". Your website doesn't carry a Book "
                                  "button yet — say 'wire booking into "
                                  "my site' and I'll add it to the site "
                                  "plan.")
        except Exception as e:
            logger.info(f"[create_offering] site-door note skipped: {e}")
    _refresh_composed_site_bg(biz["id"])
    return {
        "type": "create_offering",
        "result": "created",
        "label": f"💲 Created offering: {off.get('name')}{price_str}{dur_str}{store_str}{site_note}",
        "offering_id": off.get("id"),
        "nav": _nav("build"),
        # C.1.3.1b — refresh OfferingsManager + any other listener when
        # Chief mediates an offering write. Manual create dispatches this
        # event directly; Chief gets parity via the generic frontend_event
        # dispatch in ChiefOfStaff.tsx.
        "frontend_event": {"name": "solutionist-offerings-changed"},
    }

async def handle_update_offering(client, biz, action) -> Dict:
    """Update an offering's price / duration / etc. action: {offering_id |
    name, current_price?, price?, duration_min?, name?, description?,
    show_price_to_customer?, currency?, category?}.

    Price updates do NOT propagate to historical module_entries — the P5
    discipline preserves price_at_booking on past bookings. Only future
    bookings + the customer widget read the new current_price."""
    offering_id = action.get("offering_id")
    if not offering_id and action.get("name"):
        match = await _find_offering_by_name(client, biz["id"], action["name"])
        if match:
            offering_id = match["id"]
    if not offering_id:
        return _fail("update_offering",
                     f"no offering found for name={action.get('name')!r}. "
                     f"Try list_offerings to see what's on file.")

    patch: Dict[str, Any] = {}
    for k in ("name", "description", "currency"):
        if k in action and action[k] is not None:
            patch[k] = action[k]
    if action.get("category"):
        cat = action["category"].strip().lower()
        if cat not in _VALID_OFFERING_CATEGORIES:
            return _fail("update_offering",
                         f"category must be one of {sorted(_VALID_OFFERING_CATEGORIES)}")
        patch["category"] = cat
    if "current_price" in action or "price" in action:
        raw = action.get("current_price", action.get("price"))
        try:
            patch["current_price"] = float(raw) if raw is not None else None
        except (TypeError, ValueError):
            return _fail("update_offering", f"invalid price: {raw!r}")
    if "duration_min" in action or "duration_minutes" in action or "duration" in action:
        raw = action.get("duration_min", action.get("duration_minutes", action.get("duration")))
        try:
            patch["duration_min"] = int(raw) if raw is not None else None
            if patch["duration_min"] is not None and patch["duration_min"] <= 0:
                return _fail("update_offering", "duration_min must be > 0")
        except (TypeError, ValueError):
            return _fail("update_offering", f"invalid duration_min: {raw!r}")
    if action.get("show_price_to_customer") is not None:
        patch["show_price_to_customer"] = bool(action["show_price_to_customer"])
    # Arc 27 — store product fields.
    if action.get("image_url") is not None:
        patch["image_url"] = (str(action["image_url"]).strip()[:600]) or None
    if action.get("sku") is not None:
        patch["sku"] = (str(action["sku"]).strip()[:80]) or None
    if action.get("inventory_qty") is not None:
        try:
            patch["inventory_qty"] = max(0, int(action["inventory_qty"]))
        except (TypeError, ValueError):
            return _fail("update_offering", f"invalid inventory_qty: {action.get('inventory_qty')!r}")
    if action.get("requires_shipping") is not None:
        patch["requires_shipping"] = bool(action["requires_shipping"])
    if action.get("fulfillment_note") is not None:
        patch["fulfillment_note"] = (str(action["fulfillment_note"]).strip()[:600]) or None

    if not patch:
        return _fail("update_offering", "no fields to update")

    import time as _t
    patch["updated_at"] = _t.strftime("%Y-%m-%dT%H:%M:%SZ", _t.gmtime())
    rows = await _sb(client, "PATCH", f"/offerings?id=eq.{offering_id}", patch)
    if not rows:
        return _fail("update_offering", "update failed")
    off = rows[0]
    bits = []
    if "current_price" in patch:
        bits.append(f"price → ${patch['current_price']}")
    if "duration_min" in patch:
        bits.append(f"duration → {patch['duration_min']} min")
    if "name" in patch:
        bits.append(f"name → {patch['name']!r}")
    if "category" in patch:
        bits.append(f"category → {patch['category']}")
    if "show_price_to_customer" in patch:
        bits.append(f"price-visible → {patch['show_price_to_customer']}")
    if "inventory_qty" in patch:
        bits.append(f"stock → {patch['inventory_qty']}")
    if "requires_shipping" in patch:
        bits.append(f"physical item → {patch['requires_shipping']}")
    if "image_url" in patch:
        bits.append("image updated" if patch["image_url"] else "image removed")
    detail = "; ".join(bits) if bits else "updated"
    _refresh_composed_site_bg(biz["id"])
    return {
        "type": "update_offering",
        "result": "updated",
        "label": f"💲 {off.get('name')}: {detail}",
        "offering_id": offering_id,
        "offering": off,
        "nav": _nav("build"),
        # C.1.3.1b — see handle_create_offering note.
        "frontend_event": {"name": "solutionist-offerings-changed"},
    }

async def handle_set_site_capability(client, biz, action) -> Dict:
    """THE WIRED-SITE CONTRACT (2026-07-26) — record whether the website
    carries a connected door (booking, store). Writes the capability
    into the discovery dossier at 'asked' provenance (the owner said so
    in chat — same rank as a coach answer); the builder's connected-
    doors law then makes the next rebuild/refine carry it. action:
    {capability: "booking"|"store", on: true|false}.

    Trust-layer: the honesty gate refuses to wire a door the platform
    doesn't actually have live, so the label can never promise a Book
    button with no booking page behind it."""
    cap = str(action.get("capability") or "").strip().lower()
    if cap not in ("booking", "store"):
        return _fail("set_site_capability",
                     "capability must be 'booking' or 'store'")
    on = action.get("on")
    on = True if on is None else bool(on)
    import offering_profiles
    state = await asyncio.to_thread(
        offering_profiles.business_state, str(biz["id"]))
    if on and cap == "booking" and not (
            state.get("booking_enabled") and state.get("booking_url")):
        return _fail("set_site_capability",
                     "booking isn't live yet — publish the booking page "
                     "first (Build → Booking), then wire it into the site")
    if on and cap == "store" and not state.get("store_url"):
        return _fail("set_site_capability",
                     "no store page exists yet — the business needs a "
                     "published site slug first")
    import discovery
    patch = {"capabilities": {cap: {"value": "on" if on else "off",
                                    "source": "asked"}}}
    saved = await asyncio.to_thread(discovery.answer, str(biz["id"]), patch)
    if saved is None:
        return _fail("set_site_capability",
                     "no site row to store the site plan on yet — "
                     "create the site first")
    if on:
        url = (state.get("booking_url") if cap == "booking"
               else state.get("store_url"))
        label = (f"🔌 {cap.title()} is wired into the site plan ({url}). "
                 "The next site pass must carry it — say 'refine my "
                 "site' to apply it now.")
    else:
        label = (f"🔌 {cap.title()} removed from the site plan — the "
                 "next site pass drops the door.")
    return {"type": "set_site_capability", "result": "saved",
            "label": label, "nav": _nav("build")}


# ─── Site copy, live (2026-09-04) ──────────────────────────────────────
# Chief's first site-copy verb. It writes a TEXT OVERRIDE — the same row
# Studio Edit Mode writes — against one data-override-target on the stored
# page, so it works on every site that carries targets: composed pages are
# re-rendered in the background (no model call), hand-built ones
# (site_config.html_source == "manual") are served with overrides applied,
# so the edit is live on the next request. Never a rebuild, never a cost.

_SITE_TEXT_MAX = 600

def _site_text_plain(fragment: str) -> str:
    import html as _htmlmod
    s = re.sub(r"<[^>]+>", " ", str(fragment or ""))
    return " ".join(_htmlmod.unescape(s).split())

async def handle_edit_site_text(client, biz, action) -> Dict:
    """Change ONE piece of text on the public website. action: {text,
    find | target}. `find` is a few words quoted from the site; the one
    editable spot containing them is edited — several matches is a
    refusal that names them, never a guess. `target` is the spot's id
    (e.g. home.hero.lead) when known. Plain text only; HTML is escaped."""
    import html as _htmlmod
    text = " ".join(str(action.get("text") or "").split())
    if not text:
        return _fail("edit_site_text", "tell me the new wording first")
    if len(text) > _SITE_TEXT_MAX:
        return _fail("edit_site_text",
                     "that's longer than one spot on the site can hold — "
                     f"keep it under {_SITE_TEXT_MAX} characters")
    target = str(action.get("target") or action.get("target_path") or "").strip()
    find = " ".join(str(action.get("find") or "").split())
    if not target and not find:
        return _fail("edit_site_text",
                     "tell me which text to change — quote a few words of it "
                     "exactly as they appear on the site")
    biz_id = str(biz["id"])
    targets, manual = await asyncio.to_thread(_site_text_targets, biz_id)
    if not targets:
        return _fail("edit_site_text",
                     "this site doesn't carry editable text spots yet — "
                     "it needs a site pass first")
    if target:
        hits = [t for t in targets if t["target_path"] == target]
    else:
        needle = find.lower()
        hits = [t for t in targets if needle in t["current"].lower()]
    if not hits:
        return _fail("edit_site_text",
                     "I couldn't find that wording on the site — quote a few "
                     "words exactly as they appear there")
    if len(hits) > 1:
        opts = "; ".join(f"{h['page']}: “{h['current'][:60]}”" for h in hits[:4])
        return _fail("edit_site_text",
                     f"that matches more than one spot ({opts}) — quote a "
                     "longer piece so I change the right one")
    hit = hits[0]
    from agents.override_system import override_storage
    saved = await asyncio.to_thread(
        override_storage.upsert_override, biz_id, "text", hit["target_path"],
        _htmlmod.escape(text), None, hit["current"], "chief_command")
    if saved is None:
        return _fail("edit_site_text",
                     "I couldn't save that edit just now — try again in a moment")
    if not manual:
        _site_text_refresh_if_composed(biz_id)
    else:
        # A hand-built page is live at once, so look at it at once: the
        # free geometry pass only (no vision call for a one-line edit).
        try:
            import site_check
            site_check.run_in_background(biz_id, reason="edit", vision=False)
        except Exception:
            pass
    when = "Live now." if manual else "Re-rendering now — live in a moment."
    label = (f"✏️ Site updated ({hit['page']} page): “{hit['current'][:80]}” → "
             f"“{text[:80]}”. {when} Say 'undo' to put it back.")
    return {"type": "edit_site_text", "result": "saved",
            "target_path": hit["target_path"], "page": hit["page"],
            "previous_text": hit["current"], "text": text,
            "label": label, "nav": _nav("build")}


async def handle_check_site(client, biz, action) -> Dict:
    """Look at the live website the way a person does (site_check.py):
    open every public page at a phone and a desktop width, measure
    overlaps, overflow, broken images, empty headings and leftover
    placeholders, then have a vision judge review the screenshots for
    alignment. Runs as a background job (a minute or two); the report is
    filed on the site row and read back through site_health. action:
    {vision: true|false} — vision defaults on."""
    import chief_jobs
    vision = action.get("vision")
    vision = True if vision is None else bool(vision)
    try:
        job = await chief_jobs.enqueue(
            client, user_id=str(biz.get("owner_id") or ""), business_id=str(biz["id"]),
            kind="site_check", params={"vision": vision, "reason": "chief"},
            source="chief")
    except Exception as e:
        logger.info(f"[check_site] enqueue failed: {e}")
        job = None
    if not job:
        return _fail("check_site", "I couldn't start the site check just now — try again in a moment")
    if job.get("deduped"):
        return {"type": "check_site", "result": "already running",
                "label": "🔎 A site check is already running — I'll have the report in a minute.",
                "nav": _nav("build"), "job_id": job.get("id")}
    return {"type": "check_site", "result": "queued",
            "label": ("🔎 Looking at the live site now — every page at phone and desktop "
                      "size. Give me a minute or two, then ask for site health to read "
                      "what I found."),
            "nav": _nav("build"), "job_id": job.get("id")}

async def handle_revert_site_text(client, biz, action) -> Dict:
    """Put one edited site text back to the stored copy: removes the
    override for `target`. The inverse of edit_site_text."""
    target = str(action.get("target") or action.get("target_path") or "").strip()
    if not target:
        return _fail("revert_site_text", "tell me which spot to put back")
    biz_id = str(biz["id"])
    from agents.override_system import override_storage
    existing = await asyncio.to_thread(
        override_storage.get_override, biz_id, "text", target)
    if not existing:
        return _fail("revert_site_text", "there's no edit on that spot to put back")
    ok = await asyncio.to_thread(
        override_storage.delete_override_by_path, biz_id, "text", target)
    if not ok:
        return _fail("revert_site_text",
                     "I couldn't put that back just now — try again in a moment")
    _targets, manual = await asyncio.to_thread(_site_text_targets, biz_id)
    if not manual:
        _site_text_refresh_if_composed(biz_id)
    prev = _site_text_plain(existing.get("override_value") or "")
    return {"type": "revert_site_text", "result": "reverted",
            "target_path": target, "previous_text": prev,
            "label": "↩ Site text put back to the stored copy."
                     + ("" if manual else " Re-rendering now."),
            "nav": _nav("build")}

async def handle_offering_readiness(client, biz, action) -> Dict:
    """Arc 28 — per-offering functional readiness via the behavior-
    profile engine (offering_profiles.py). The label carries concrete
    per-offering blockers so the second-pass reply can name exactly
    what's broken and where the fix lives — never a vague 'looks good'.
    """
    import offering_profiles
    try:
        report = offering_profiles.business_readiness(str(biz["id"]))
    except Exception as e:
        return _fail("offering_readiness", f"readiness check failed: {e}")
    per = report["offerings"]
    summary = report["summary"]
    state = report["business"]
    if not per:
        return {
            "type": "offering_readiness",
            "result": "empty",
            "label": "🧭 No active offerings yet — nothing to check. "
                     "Create offerings first (bookable services or store products).",
            "nav": _nav("operate"),
            "signal": {"blocked": 0, "total": 0},
        }
    problems = []
    for r in per:
        if not r["ready"] and r["behavior"] in ("bookable", "sellable"):
            top = "; ".join(i["msg"] for i in r["issues"][:2])
            problems.append(f"'{r['name']}' ⚠ {top}")
    bits = [f"{summary['ready']}/{summary['total']} functional"]
    if state["booking_enabled"] and state["booking_url"]:
        bits.append(f"booking live at {state['booking_url']}")
    if state["store_url"] and summary["sellable_ready"]:
        bits.append(f"store live at {state['store_url']}")
    if problems:
        bits.append("blockers: " + " | ".join(problems[:4])
                    + (f" (+{len(problems) - 4} more)" if len(problems) > 4 else ""))
    return {
        "type": "offering_readiness",
        "result": "report",
        "label": "🧭 Readiness: " + " — ".join(bits),
        "summary": summary,
        "business_state": state,
        "offerings": per,
        "nav": _nav("operate"),
        "signal": {"blocked": len(problems), "total": summary.get("total", len(per))},
    }

async def handle_setup_store(client, biz, action) -> Dict:
    """Arc 27 — configure and/or report the hosted storefront. action:
    {tax_rate_pct?, flat_shipping_usd?}. With no args it's a status
    check. The store itself always exists once the site has a slug —
    offerings with category product/course/package + a price appear in
    it automatically; this handler sets tax/shipping and returns the
    live URL + product count so the reply can be concrete.

    Trust-layer notes: result='blocked' (no published site) carries the
    exact reason in the label so the second-pass reply can't narrate a
    store that isn't reachable. The label always states what IS true
    (URL, live product count, settings) — never an aspiration."""
    sites = await _sb(client, "GET",
        f"/business_sites?business_id=eq.{biz['id']}&select=slug&limit=1")
    slug = (sites[0].get("slug") if sites else "") or ""
    if not slug:
        return {
            "type": "setup_store",
            "result": "blocked",
            "label": ("🛒 Store not reachable yet — the business has no published "
                      "site address. Generate the site first (BUILD → My Site → "
                      "Compose my site); the store lives at that address."),
            "nav": _nav("build"),
        }
    store_url = f"{FALLBACK_BASE}/public/store/{slug}/page"

    # Settings (flat tax % + flat shipping) — only patch what was given.
    changed = []
    biz_rows = await _sb(client, "GET",
        f"/businesses?id=eq.{biz['id']}&select=settings&limit=1")
    settings = dict((biz_rows[0].get("settings") if biz_rows else {}) or {})
    store_cfg = dict(settings.get("store") or {})
    if action.get("tax_rate_pct") is not None:
        try:
            store_cfg["tax_rate_pct"] = max(0.0, min(20.0, float(action["tax_rate_pct"])))
            changed.append(f"tax {store_cfg['tax_rate_pct']:g}%")
        except (TypeError, ValueError):
            return _fail("setup_store", f"invalid tax_rate_pct: {action.get('tax_rate_pct')!r}")
    if action.get("flat_shipping_usd") is not None:
        try:
            store_cfg["flat_shipping_cents"] = max(0, int(round(float(action["flat_shipping_usd"]) * 100)))
            changed.append(f"flat shipping ${store_cfg['flat_shipping_cents'] / 100:,.2f}")
        except (TypeError, ValueError):
            return _fail("setup_store", f"invalid flat_shipping_usd: {action.get('flat_shipping_usd')!r}")
    if changed:
        settings["store"] = store_cfg
        await _sb(client, "PATCH", f"/businesses?id=eq.{biz['id']}", {"settings": settings})

    sellable = await _sb(client, "GET",
        f"/offerings?business_id=eq.{biz['id']}&is_active=eq.true"
        "&category=in.(product,course,package)&current_price=gt.0"
        "&select=id,name&limit=100") or []
    payments_ready = bool(biz.get("stripe_account_id"))
    if not payments_ready:
        biz_pay = await _sb(client, "GET",
            f"/businesses?id=eq.{biz['id']}&select=stripe_account_id&limit=1")
        payments_ready = bool(biz_pay and biz_pay[0].get("stripe_account_id"))

    bits = [f"{len(sellable)} product{'s' if len(sellable) != 1 else ''} live"]
    if changed:
        bits.append("set " + ", ".join(changed))
    if not payments_ready:
        bits.append("⚠ Stripe not connected — checkout will refuse until "
                    "Payments is set up (OPERATE → Payments)")
    if not sellable:
        bits.append("add products via create_offering with category='product' and a price")
    return {
        "type": "setup_store",
        "result": "configured" if changed else "ready",
        "label": f"🛒 Store: {store_url} — " + "; ".join(bits),
        "store_url": store_url,
        "sellable_count": len(sellable),
        "payments_ready": payments_ready,
        "nav": _nav("operate"),
        "frontend_event": {"name": "solutionist-offerings-changed"},
    }

async def handle_archive_offering(client, biz, action) -> Dict:
    """Soft-delete an offering (is_active=false, archived_at=now). Existing
    references to this offering remain valid for historical display
    (denormalized fields preserve service_name + price + duration)."""
    offering_id = action.get("offering_id")
    if not offering_id and action.get("name"):
        match = await _find_offering_by_name(client, biz["id"], action["name"])
        if match:
            offering_id = match["id"]
    if not offering_id:
        return _fail("archive_offering",
                     f"no offering found for name={action.get('name')!r}.")
    import time as _t
    now_iso = _t.strftime("%Y-%m-%dT%H:%M:%SZ", _t.gmtime())
    rows = await _sb(client, "PATCH", f"/offerings?id=eq.{offering_id}", {
        "is_active": False, "archived_at": now_iso, "updated_at": now_iso,
    })
    if not rows:
        return _fail("archive_offering", "archive failed")
    _refresh_composed_site_bg(biz["id"])
    return {
        "type": "archive_offering",
        "result": "archived",
        "label": f"📦 Archived {rows[0].get('name')}",
        "offering_id": offering_id,
        "nav": _nav("build"),
        # C.1.3.1b — see handle_create_offering note.
        "frontend_event": {"name": "solutionist-offerings-changed"},
    }

async def handle_list_offerings(client, biz, action) -> Dict:
    """List offerings for this business. action: {category?, include_archived?}"""
    cat = (action.get("category") or "").strip().lower()
    include_archived = bool(action.get("include_archived"))
    qs = (f"business_id=eq.{biz['id']}&order=category.asc,name.asc"
          f"&select=id,name,slug,category,current_price,currency,duration_min,"
          f"show_price_to_customer,is_active&limit=200")
    if cat and cat in _VALID_OFFERING_CATEGORIES:
        qs += f"&category=eq.{cat}"
    if not include_archived:
        qs += "&is_active=eq.true"
    rows = await _sb(client, "GET", f"/offerings?{qs}") or []
    summary_lines = []
    for r in rows[:25]:
        price = r.get("current_price")
        price_s = f"${price}" if price is not None else "—"
        dur = f" · {r['duration_min']}m" if r.get("duration_min") else ""
        cat_s = f"[{r.get('category')}]"
        flag = "" if r.get("is_active") else " (archived)"
        summary_lines.append(f"  {cat_s:<11} {r.get('name')}: {price_s}{dur}{flag}")
    label = f"💲 {len(rows)} offering(s)" + (f" in {cat}" if cat else "")
    if len(rows) > 25:
        label += " (showing first 25)"
    return {
        "type": "list_offerings",
        "result": "ok",
        "label": label,
        "summary": "\n".join(summary_lines),
        "offerings": rows,
        "nav": _nav("build"),
    }


# ─────────────────────────────────────────────────────────────────────
# Phase D.1.2 — Chief CRUD for availability
# ─────────────────────────────────────────────────────────────────────


_VALID_DAY_KEYS = frozenset({"mon", "tue", "wed", "thu", "fri", "sat", "sun"})

def _load_availability_settings(business_id: str) -> Dict[str, Any]:
    """Load business settings; return the availability sub-dict (empty
    dict when missing). Read via service role."""
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{business_id}&select=settings&limit=1"
    ) or []
    if not rows:
        return {}
    settings = rows[0].get("settings") or {}
    return dict(settings.get("availability") or {})

def _save_availability_settings(business_id: str, availability: Dict[str, Any]) -> None:
    """Merge availability back into settings JSON. Service-role write."""
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{business_id}&select=settings&limit=1"
    ) or []
    settings = dict((rows[0].get("settings") or {}) if rows else {})
    settings["availability"] = availability
    sb_clients.sb_patch_as_service(
        f"/businesses?id=eq.{business_id}", {"settings": settings},
    )

_AVAILABILITY_FRONTEND_EVENT = {"name": "solutionist-availability-changed"}

async def handle_set_availability_day(client, biz, action) -> Dict:
    """Set the weekly schedule for one day. action: {day, hours}
    where day is 'mon'..'sun' and hours is a list of {start, end}
    HH:MM ranges. Empty list = closed."""
    day = (action.get("day") or "").strip().lower()[:3]
    if day not in _VALID_DAY_KEYS:
        return _fail("set_availability_day",
                     f"day must be one of {sorted(_VALID_DAY_KEYS)}")
    hours = action.get("hours") or []
    if not isinstance(hours, list):
        return _fail("set_availability_day", "hours must be a list")
    # Coerce to canonical shape via the Pydantic model in availability.py
    try:
        from availability import TimeRange
        norm_hours = [TimeRange.model_validate(h).model_dump() for h in hours]
    except Exception as e:
        return _fail("set_availability_day", f"invalid hours: {e}")

    av = _load_availability_settings(biz["id"])
    weekly = dict(av.get("weekly") or {})
    weekly[day] = norm_hours
    av["weekly"] = weekly
    _save_availability_settings(biz["id"], av)

    if not norm_hours:
        label = f"📅 {day.title()} → closed"
    else:
        ranges = ", ".join(f"{h['start']}–{h['end']}" for h in norm_hours)
        label = f"📅 {day.title()} → {ranges}"
    return {
        "type": "set_availability_day",
        "result": "updated",
        "label": label,
        "day": day,
        "hours": norm_hours,
        "nav": _nav("build"),
        "frontend_event": _AVAILABILITY_FRONTEND_EVENT,
    }

async def handle_set_availability_override(client, biz, action) -> Dict:
    """Set a date-specific override that replaces the weekly schedule
    for that date. action: {date, hours}. hours=[] means closed."""
    date_s = (action.get("date") or "").strip()
    if not date_s or len(date_s) != 10:
        return _fail("set_availability_override",
                     "date is required, YYYY-MM-DD")
    hours = action.get("hours") or []
    try:
        from availability import DateOverride
        norm = DateOverride.model_validate({"date": date_s, "hours": hours}).model_dump()
    except Exception as e:
        return _fail("set_availability_override", f"invalid override: {e}")

    av = _load_availability_settings(biz["id"])
    overrides = [o for o in (av.get("overrides") or [])
                 if (o or {}).get("date") != date_s]  # remove existing for this date
    overrides.append(norm)
    overrides.sort(key=lambda o: o.get("date", ""))
    av["overrides"] = overrides
    _save_availability_settings(biz["id"], av)

    if not norm["hours"]:
        label = f"📅 {date_s} → closed (override)"
    else:
        ranges = ", ".join(f"{h['start']}–{h['end']}" for h in norm["hours"])
        label = f"📅 {date_s} → {ranges} (override)"
    return {
        "type": "set_availability_override",
        "result": "updated",
        "label": label,
        "date": date_s,
        "hours": norm["hours"],
        "nav": _nav("build"),
        "frontend_event": _AVAILABILITY_FRONTEND_EVENT,
    }

async def handle_add_block_range(client, biz, action) -> Dict:
    """Block a range of dates (vacation, holiday week). action:
    {start, end, reason?}. Inclusive both ends."""
    start = (action.get("start") or "").strip()
    end = (action.get("end") or start).strip()
    reason = action.get("reason")
    try:
        from availability import BlockedRange
        norm = BlockedRange.model_validate({
            "start": start, "end": end, "reason": reason,
        }).model_dump()
    except Exception as e:
        return _fail("add_block_range", f"invalid block: {e}")

    av = _load_availability_settings(biz["id"])
    blocks = list(av.get("blocks") or [])
    # De-dupe by (start, end) — replace prior with same range.
    blocks = [b for b in blocks
              if not ((b or {}).get("start") == norm["start"]
                      and (b or {}).get("end") == norm["end"])]
    blocks.append(norm)
    blocks.sort(key=lambda b: b.get("start", ""))
    av["blocks"] = blocks
    _save_availability_settings(biz["id"], av)

    if norm["start"] == norm["end"]:
        rng = norm["start"]
    else:
        rng = f"{norm['start']} → {norm['end']}"
    suffix = f" ({reason})" if reason else ""
    return {
        "type": "add_block_range",
        "result": "added",
        "label": f"🚫 Blocked {rng}{suffix}",
        "start": norm["start"], "end": norm["end"], "reason": reason,
        "nav": _nav("build"),
        "frontend_event": _AVAILABILITY_FRONTEND_EVENT,
    }

async def handle_remove_block_range(client, biz, action) -> Dict:
    """Remove a previously-added block. action: {start} (start date
    identifies the block)."""
    start = (action.get("start") or "").strip()
    if not start:
        return _fail("remove_block_range", "start date required")
    av = _load_availability_settings(biz["id"])
    before = list(av.get("blocks") or [])
    after = [b for b in before if (b or {}).get("start") != start]
    if len(after) == len(before):
        return _fail("remove_block_range",
                     f"no block found with start={start!r}")
    av["blocks"] = after
    _save_availability_settings(biz["id"], av)
    return {
        "type": "remove_block_range",
        "result": "removed",
        "label": f"🗓️ Removed block starting {start}",
        "start": start,
        "nav": _nav("build"),
        "frontend_event": _AVAILABILITY_FRONTEND_EVENT,
    }

async def handle_set_slot_granularity(client, biz, action) -> Dict:
    """Set slot grid spacing in minutes. action: {minutes}."""
    try:
        minutes = int(action.get("minutes"))
    except (TypeError, ValueError):
        return _fail("set_slot_granularity", "minutes must be an integer")
    if not (5 <= minutes <= 240):
        return _fail("set_slot_granularity",
                     "minutes must be between 5 and 240")
    av = _load_availability_settings(biz["id"])
    av["slot_granularity_min"] = minutes
    _save_availability_settings(biz["id"], av)
    return {
        "type": "set_slot_granularity",
        "result": "updated",
        "label": f"⏱️ Slot grid set to every {minutes} minutes",
        "minutes": minutes,
        "nav": _nav("build"),
        "frontend_event": _AVAILABILITY_FRONTEND_EVENT,
    }

async def handle_set_lead_time(client, biz, action) -> Dict:
    """Set required lead-time in minutes (customers can't book within
    this window of now). action: {minutes}."""
    try:
        minutes = int(action.get("minutes"))
    except (TypeError, ValueError):
        return _fail("set_lead_time", "minutes must be an integer")
    if minutes < 0:
        return _fail("set_lead_time", "minutes must be >= 0")
    av = _load_availability_settings(biz["id"])
    av["lead_time_min"] = minutes
    _save_availability_settings(biz["id"], av)
    if minutes == 0:
        label = "⏱️ Lead-time cleared (instant bookings allowed)"
    else:
        h, m = divmod(minutes, 60)
        if h and m:
            human = f"{h}h {m}m"
        elif h:
            human = f"{h}h"
        else:
            human = f"{m} min"
        label = f"⏱️ Lead-time set to {human}"
    return {
        "type": "set_lead_time",
        "result": "updated",
        "label": label,
        "minutes": minutes,
        "nav": _nav("build"),
        "frontend_event": _AVAILABILITY_FRONTEND_EVENT,
    }

async def handle_set_business_timezone(client, biz, action) -> Dict:
    """Set the canonical timezone for the business. action: {timezone}."""
    tz = (action.get("timezone") or "").strip()
    if not tz:
        return _fail("set_business_timezone", "timezone is required")
    # Quick sanity — must be parseable by zoneinfo
    try:
        from zoneinfo import ZoneInfo
        ZoneInfo(tz)
    except Exception:
        return _fail("set_business_timezone",
                     f"unknown timezone {tz!r}; use an IANA name like "
                     f"'America/New_York'")
    av = _load_availability_settings(biz["id"])
    av["timezone"] = tz
    _save_availability_settings(biz["id"], av)
    return {
        "type": "set_business_timezone",
        "result": "updated",
        "label": f"🌎 Business timezone set to {tz}",
        "timezone": tz,
        "nav": _nav("build"),
        "frontend_event": _AVAILABILITY_FRONTEND_EVENT,
    }

async def handle_list_availability(client, biz, action) -> Dict:
    """Return the current availability config in human-readable form."""
    av = _load_availability_settings(biz["id"])
    if not av:
        return {
            "type": "list_availability",
            "result": "ok",
            "label": "📅 No availability set — open by default (24/7).",
            "availability": {},
            "nav": _nav("build"),
        }
    lines = []
    tz = av.get("timezone")
    if tz:
        lines.append(f"  timezone: {tz}")
    weekly = av.get("weekly") or {}
    for day in ("mon", "tue", "wed", "thu", "fri", "sat", "sun"):
        h = weekly.get(day) or []
        if h:
            ranges = ", ".join(f"{r.get('start')}–{r.get('end')}" for r in h)
            lines.append(f"  {day}: {ranges}")
        else:
            lines.append(f"  {day}: closed")
    overrides = av.get("overrides") or []
    if overrides:
        lines.append("  overrides:")
        for o in overrides[:10]:
            d = o.get("date"); h = o.get("hours") or []
            if not h:
                lines.append(f"    {d}: closed")
            else:
                rs = ", ".join(f"{r.get('start')}–{r.get('end')}" for r in h)
                lines.append(f"    {d}: {rs}")
    blocks = av.get("blocks") or []
    if blocks:
        lines.append("  blocks:")
        for b in blocks[:10]:
            s = b.get("start"); e = b.get("end"); r = b.get("reason")
            lines.append(f"    {s} → {e}" + (f" ({r})" if r else ""))
    grain = av.get("slot_granularity_min", 30)
    lead = av.get("lead_time_min", 0)
    lines.append(f"  slot grid: every {grain} min · lead-time: {lead} min")
    return {
        "type": "list_availability",
        "result": "ok",
        "label": f"📅 Availability config ({len(lines)} settings)",
        "summary": "\n".join(lines),
        "availability": av,
        "nav": _nav("build"),
    }
