"""
site_composer.py — Arc 26 PR3 — the page composer.

The Arc 26 inversion of the Builder pipeline: the LLM never writes
HTML. It reads the business (brand bundle, offerings, voice) and fills
a STRICT page spec — module choices, expression variants, copy — which
site_modules renders deterministically against the brand_dna tokens.
Function is guaranteed by the modules; creativity lives in the spec.

Flow (compose):
  1. gather context  (brand bundle → DNA, offerings, testimonials,
                      booking URL, contact)
  2. LLM composition → validated spec  (deterministic vibe-keyed
                      fallback if the LLM fails — compose NEVER 500s
                      on creativity)
  3. render          (site_modules.render_page, slots empty)
  4. slot population (existing Pass 4.0b.5 pipeline, unchanged)
  5. slot resolution (existing resolve_html_slots, unchanged)
  6. persist         html_content (live on /public/site/{slug} and the
                     subdomain immediately) + site_config.page_spec /
                     generated_html / html_source="module-composer"

Shuffle: re-pick a section's expression variant and re-render from the
stored spec — no LLM, sub-second, the "try another look" affordance.

Composed pages carry a marker meta tag; public_site's legacy dynamic-
section injection skips marked pages (the modules already render
offerings/testimonials/gallery from live data at compose time).
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import sb_clients
from auth_supabase import UserSession

import brand_dna
import site_modules

logger = logging.getLogger("site_composer")

router = APIRouter(prefix="/composer", tags=["site_composer"])

RAILWAY_BASE = "https://kmj-intake-server-production.up.railway.app"
COMPOSER_MARK = '<meta name="x-solutionist-composer" content="module-composer">'

_MAX_FIELD = {"body": 900, "intro": 400, "note": 300, "subheadline": 260,
              "pull_quote": 260, "headline": 120, "eyebrow": 60, "cta_label": 40}


# ─── Context gathering ────────────────────────────────────────────────

def _slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (name or "site").lower()).strip("-")
    return s[:48] or "site"


def gather_context(business_id: str) -> Dict[str, Any]:
    import brand_engine
    bundle = brand_engine.get_bundle(business_id) or {}

    biz_rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{business_id}&select=id,name,type,settings&limit=1") or []
    if not biz_rows:
        raise HTTPException(404, "business not found")
    biz = biz_rows[0]
    settings = biz.get("settings") or {}

    site_rows = sb_clients.sb_get_as_service(
        f"/business_sites?business_id=eq.{business_id}"
        "&select=id,slug,site_config,status&limit=1") or []
    site = site_rows[0] if site_rows else None
    slug = (site or {}).get("slug") or ""

    offerings = sb_clients.sb_get_as_service(
        f"/offerings?business_id=eq.{business_id}&is_active=eq.true"
        "&order=created_at.asc&select=*&limit=24") or []

    booking_cfg = settings.get("booking") or {}
    booking = {
        "enabled": bool(booking_cfg.get("enabled")) and bool(slug),
        "url": f"{RAILWAY_BASE}/public/booking/{slug}" if slug else "",
    }

    testimonials = ((settings.get("website_content") or {}).get("testimonials")) or []

    # Arc 27 — sellable products feed the store module + hosted store page.
    try:
        from store_router import _sellable_offerings
        sellable = _sellable_offerings(business_id)
    except Exception:
        sellable = []
    store = {"enabled": bool(sellable) and bool(slug),
             "url": f"{RAILWAY_BASE}/public/store/{slug}/page" if slug else "",
             "items": sellable}

    dna = brand_dna.build_brand_dna(business_id, bundle)
    return {
        "store": store,
        "dna": dna,
        "bundle": bundle,
        "business": {"id": business_id, "name": biz.get("name") or "",
                     "type": biz.get("type") or "", "slug": slug},
        "settings": settings,
        "site": site,
        "offerings": offerings,
        "testimonials": testimonials,
        "booking": booking,
        "contact": {"email": (settings.get("contact_email")
                              or (bundle.get("practitioner") or {}).get("email") or "")},
        "footer": bundle.get("footer") or {},
    }


# ─── Spec validation ─────────────────────────────────────────────────

def sanitize_spec(raw: Any, ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Clamp an LLM (or stored) spec to the module registry: known
    modules and variants only, known content fields only, length caps,
    hero first, contact last, no duplicate modules."""
    sections_in = (raw or {}).get("sections") if isinstance(raw, dict) else raw
    out: List[Dict[str, Any]] = []
    seen = set()
    for sec in (sections_in or []):
        if not isinstance(sec, dict):
            continue
        mid = sec.get("module")
        spec = site_modules.MODULES.get(mid)
        if not spec or mid in seen:
            continue
        seen.add(mid)
        variant = sec.get("variant")
        if variant not in spec["variants"]:
            variant = spec["variants"][0]
        content_in = sec.get("content") or {}
        content = {}
        for f in spec["fields"]:
            v = content_in.get(f)
            if isinstance(v, (int, float)):
                v = str(v)
            if isinstance(v, str) and v.strip():
                content[f] = v.strip()[:_MAX_FIELD.get(f, 200)]
        out.append({"module": mid, "variant": variant, "content": content})

    # Structural guarantees regardless of what the LLM did.
    if not any(s["module"] == "hero" for s in out):
        out.insert(0, _default_spec(ctx)[0])
    if not any(s["module"] == "contact" for s in out):
        out.append({"module": "contact", "variant": "standard", "content": {}})
    out.sort(key=lambda s: (0 if s["module"] == "hero" else
                            2 if s["module"] == "contact" else 1))
    return out


def _default_spec(ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Deterministic vibe-keyed composition — the no-LLM floor."""
    dna = ctx["dna"]
    biz = ctx["business"]
    hero_variant = {"warm": "split", "formal": "statement", "bold": "banner"}[dna["vibe"]]
    tagline = ((ctx.get("bundle") or {}).get("business") or {}).get("tagline") or ""
    spec = [
        {"module": "hero", "variant": hero_variant,
         "content": {"headline": biz["name"], "subheadline": tagline,
                     "cta_label": "Book a session"}},
        {"module": "about", "variant": "portrait" if dna["vibe"] != "formal" else "narrative",
         "content": {"headline": "The practice"}},
        {"module": "offerings", "variant": "cards" if dna["vibe"] != "formal" else "list",
         "content": {"headline": "Ways to work together"}},
        {"module": "testimonials",
         "variant": "spotlight" if len(ctx.get("testimonials") or []) < 3 else "grid",
         "content": {}},
        {"module": "cta", "variant": "band", "content": {"headline": "Ready when you are."}},
        {"module": "contact", "variant": "standard", "content": {"headline": "Get in touch"}},
    ]
    if dna["vibe"] == "bold" or "creative" in (biz.get("type") or ""):
        spec.insert(3, {"module": "gallery", "variant": "grid", "content": {}})
    if (ctx.get("store") or {}).get("enabled"):
        spec.insert(-2, {"module": "store", "variant": "featured", "content": {}})
    return spec


# ─── LLM composition ─────────────────────────────────────────────────

def _module_menu() -> str:
    lines = []
    for mid, spec in site_modules.MODULES.items():
        lines.append(f'- "{mid}": variants {list(spec["variants"])}, '
                     f'content fields {list(spec["fields"])}')
    return "\n".join(lines)


def compose_spec_llm(ctx: Dict[str, Any], brief_notes: str = "") -> List[Dict[str, Any]]:
    from studio_designer_agent import _call_claude, _extract_json

    bundle = ctx.get("bundle") or {}
    voice = bundle.get("voice") or {}
    intel = bundle.get("practitioner_intelligence") or {}
    biz = ctx["business"]
    off_names = ", ".join(o.get("name") or "" for o in (ctx.get("offerings") or [])[:8])
    n_testi = len(ctx.get("testimonials") or [])

    prompt = f"""You are a creative director composing a one-page website. You do NOT write HTML or CSS — the platform renders everything. Your job: choose section modules + expression variants, and write the copy in the practitioner's voice.

BUSINESS
- Name: {biz['name']}
- Type: {biz['type']}
- Tagline: {(bundle.get('business') or {}).get('tagline') or '(none)'}
- About (real, from the practitioner): {str(intel.get('about_business') or intel.get('about_me') or '')[:600] or '(none provided)'}
- Voice/tone: {voice.get('brand_voice') or ''} {voice.get('tone_words') or ''}
- Design vibe: {ctx['dna']['vibe']}, intensity: {ctx['dna']['intensity']}
- Real offerings on file: {off_names or '(none)'}
- Real testimonials on file: {n_testi}
{f'- Practitioner notes for this build: {brief_notes[:400]}' if brief_notes else ''}

AVAILABLE MODULES (use each at most once; order is yours except hero first, contact last):
{_module_menu()}

RULES
- Copy must sound like THIS practitioner, not a template. Specific beats generic.
- NEVER invent facts, testimonials, credentials, or offerings. The offerings and
  testimonials modules render the real records automatically — you only write the
  section framing (eyebrow/headline/intro).
- Include "offerings" only if offerings exist; "testimonials" only if testimonials exist;
  "store" only if sellable products exist ({(ctx.get('store') or {}).get('enabled') and len((ctx.get('store') or {}).get('items') or []) or 0} on file).
- headline ≤ 9 words. subheadline/intro: 1-2 sentences. about body: 2-4 sentences,
  first person where natural.
- Choose variants for contrast and rhythm — don't pick the first variant of everything.

Respond with ONLY this JSON:
{{"sections": [{{"module": "hero", "variant": "...", "content": {{"headline": "...", ...}}}}, ...]}}"""

    raw = _call_claude(prompt, max_tokens=1600, timeout=75.0)
    parsed = _extract_json(raw)
    if not parsed:
        raise ValueError("composer LLM returned no JSON")
    return sanitize_spec(parsed, ctx)


# ─── Render + persist ────────────────────────────────────────────────

def _mark(html: str) -> str:
    return html.replace("<head>", f"<head>\n{COMPOSER_MARK}", 1)


def render_and_persist(business_id: str, spec: List[Dict[str, Any]],
                       ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    ctx = ctx or gather_context(business_id)
    title = ctx["business"]["name"] or "Welcome"

    html = _mark(site_modules.render_page(spec, ctx, title))

    # Ensure a business_sites row exists (slug drives the live URL).
    site = ctx.get("site")
    if not site:
        slug = _slugify(ctx["business"]["name"])
        taken = sb_clients.sb_get_as_service(
            f"/business_sites?slug=eq.{slug}&select=id&limit=1") or []
        if taken:
            slug = f"{slug}-{business_id[:6]}"
        created = sb_clients.sb_post_as_service("/business_sites", {
            "business_id": business_id, "slug": slug,
            "status": "published", "html_content": "",
        })
        site = (created or [None])[0] if isinstance(created, list) else created
        if not site:
            raise HTTPException(500, "could not create business_sites row")
        ctx["site"] = site
        ctx["business"]["slug"] = slug

    # Slot population (existing pipeline) then resolution into the HTML.
    slots_meta: Dict[str, Any] = {}
    try:
        from agents.slot_system.builder_post_process import populate_slots_for_site
        slots_meta = populate_slots_for_site(
            html=html, business_id=business_id,
            business=(ctx.get("bundle") or {}).get("business") or {},
        ) or {}
    except Exception as e:
        logger.warning(f"[composer] slot population failed (non-fatal): {e}")

    final_html = html
    try:
        from agents.slot_system.slot_resolver import resolve_html_slots
        fresh = sb_clients.sb_get_as_service(
            f"/business_sites?id=eq.{site['id']}&select=site_config&limit=1") or []
        slot_records = ((fresh[0].get("site_config") or {}).get("slots")
                        if fresh else {}) or {}
        final_html, _credits, _warns = resolve_html_slots(html, slot_records)
    except Exception as e:
        logger.warning(f"[composer] slot resolution failed (non-fatal): {e}")

    # Persist: html_content serves live; site_config carries the spec.
    fresh = sb_clients.sb_get_as_service(
        f"/business_sites?id=eq.{site['id']}&select=site_config&limit=1") or []
    cfg = dict((fresh[0].get("site_config") or {}) if fresh else {})
    from datetime import datetime, timezone
    cfg.update({
        "page_spec": {"sections": spec},
        "generated_html": final_html,
        "html_source": "module-composer",
        "html_generated_at": datetime.now(timezone.utc).isoformat(),
        "use_smart_sites": False,
    })
    sb_clients.sb_patch_as_service(
        f"/business_sites?id=eq.{site['id']}",
        {"html_content": final_html, "site_config": cfg, "status": "published"})

    return {"site_id": site["id"], "slug": ctx["business"]["slug"],
            "sections": [{"module": s["module"], "variant": s["variant"]} for s in spec],
            "slots": {"found": slots_meta.get("slots_found", []),
                      "populated": len(slots_meta.get("slots_populated") or [])},
            "url": f"https://{ctx['business']['slug']}.mysolutionist.app" if ctx["business"]["slug"] else None}


# ─── Endpoints ────────────────────────────────────────────────────────

class ComposeBody(BaseModel):
    business_id: str
    brief_notes: Optional[str] = None
    use_llm: bool = True


@router.post("/compose")
def compose(body: ComposeBody,
            _: UserSession = Depends(sb_clients.authed_request)) -> Dict[str, Any]:
    ctx = gather_context(body.business_id)
    spec: List[Dict[str, Any]]
    source = "llm"
    if body.use_llm:
        try:
            spec = compose_spec_llm(ctx, body.brief_notes or "")
        except Exception as e:
            logger.warning(f"[composer] LLM composition failed, using default: {e}")
            spec, source = _default_spec(ctx), "default"
    else:
        spec, source = _default_spec(ctx), "default"
    result = render_and_persist(body.business_id, spec, ctx)
    return {"ok": True, "composition_source": source, **result}


class ShuffleBody(BaseModel):
    business_id: str
    section_index: int


@router.post("/shuffle")
def shuffle(body: ShuffleBody,
            _: UserSession = Depends(sb_clients.authed_request)) -> Dict[str, Any]:
    """Cycle one section to its next expression variant and re-render.
    Deterministic + instant — no LLM call."""
    ctx = gather_context(body.business_id)
    site = ctx.get("site")
    spec_raw = ((site or {}).get("site_config") or {}).get("page_spec")
    if not spec_raw:
        raise HTTPException(409, "no composed page yet — run /composer/compose first")
    spec = sanitize_spec(spec_raw, ctx)
    if not (0 <= body.section_index < len(spec)):
        raise HTTPException(400, "section_index out of range")
    sec = spec[body.section_index]
    variants = site_modules.MODULES[sec["module"]]["variants"]
    if len(variants) < 2:
        return {"ok": True, "unchanged": True,
                "reason": f"{sec['module']} has a single expression"}
    sec["variant"] = variants[(variants.index(sec["variant"]) + 1) % len(variants)]
    result = render_and_persist(body.business_id, spec, ctx)
    return {"ok": True, "shuffled": {"index": body.section_index,
                                     "module": sec["module"],
                                     "variant": sec["variant"]}, **result}


@router.get("/spec/{business_id}")
def get_spec(business_id: str,
             _: UserSession = Depends(sb_clients.authed_request)) -> Dict[str, Any]:
    ctx = gather_context(business_id)
    cfg = ((ctx.get("site") or {}).get("site_config") or {})
    return {"ok": True,
            "has_composition": bool(cfg.get("page_spec")),
            "page_spec": cfg.get("page_spec"),
            "html_source": cfg.get("html_source"),
            "dna": {k: ctx["dna"][k] for k in ("vibe", "intensity", "accent_style", "palette")},
            "modules": {mid: {"variants": list(s["variants"]), "fields": list(s["fields"])}
                        for mid, s in site_modules.MODULES.items()}}
