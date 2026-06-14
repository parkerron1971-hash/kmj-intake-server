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


def _fetch_public_modules(business_id: str) -> List[Dict[str, Any]]:
    """The practitioner's PUBLIC custom modules + their entries — the same
    awareness the legacy renderer had. Each module the business runs (and
    marked public) becomes a real section the composer can place and frame."""
    try:
        modules = sb_clients.sb_get_as_service(
            f"/custom_modules?business_id=eq.{business_id}&is_active=eq.true"
            "&select=id,name,schema,public_display&limit=50") or []
    except Exception as e:
        logger.warning(f"[composer] public-module fetch failed (non-fatal): {e}")
        return []
    out: List[Dict[str, Any]] = []
    for m in modules:
        pd = m.get("public_display") or {}
        if not pd.get("enabled"):
            continue
        try:
            entries = sb_clients.sb_get_as_service(
                f"/module_entries?module_id=eq.{m['id']}&status=eq.active"
                f"&order={pd.get('sort_by', 'created_at')}.desc"
                f"&limit={min(int(pd.get('max_display', 12) or 12), 24)}"
                "&select=id,data,created_at") or []
        except Exception:
            entries = []
        visible = pd.get("visible_fields") or []
        hidden = set(pd.get("hidden_fields") or ["assigned_to", "internal_notes", "contact_id"])
        filter_status = pd.get("filter_status") or []
        rows = []
        for e in entries:
            data = e.get("data") or {}
            if filter_status and data.get("status") not in filter_status:
                continue
            kept = ({k: data.get(k) for k in visible if data.get(k) not in (None, "")}
                    if visible else {k: v for k, v in data.items()
                                     if k not in hidden and v not in (None, "")})
            if kept:
                rows.append(kept)
        out.append({
            "module_id": m["id"],
            "title": pd.get("title_override") or m.get("name") or "",
            "display_type": pd.get("display_type", "list"),
            "description": pd.get("description") or "",
            "entries": rows,
        })
    return out


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

    # Logistics + socials the composer should KNOW (legacy renderer did).
    link_page = settings.get("link_page") or {}
    hours_cfg = (booking_cfg.get("hours") or {})
    contact = {
        "email": (settings.get("contact_email")
                  or (bundle.get("practitioner") or {}).get("email") or ""),
        "phone": settings.get("contact_phone") or link_page.get("phone") or "",
        "address": settings.get("address") or link_page.get("address") or "",
        "hours": (f"{hours_cfg.get('start')}–{hours_cfg.get('end')}"
                  if hours_cfg.get("start") and hours_cfg.get("end") else ""),
        "social": {k: v for k, v in (link_page.get("social_profiles") or {}).items() if v},
        "submit_url": f"{RAILWAY_BASE}/sites/{business_id}/contact-submit",
    }

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
        "public_modules": _fetch_public_modules(business_id),
        "contact": contact,
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


def _assemble_intake_text(ctx: Dict[str, Any]) -> str:
    """Build the intake material the DRL signal-detection pass reads. We have
    no raw transcript here, so we assemble the practitioner's own words from
    context (name, type, tagline, about, voice, offerings)."""
    bundle = ctx.get("bundle") or {}
    intel = bundle.get("practitioner_intelligence") or {}
    voice = bundle.get("voice") or {}
    biz = ctx["business"]
    parts = [
        f"Business name: {biz.get('name')}",
        f"Business type: {biz.get('type')}",
        f"Tagline: {(bundle.get('business') or {}).get('tagline') or ''}",
        f"About: {intel.get('about_business') or intel.get('about_me') or ''}",
        f"Voice / tone: {voice.get('brand_voice') or ''} {voice.get('tone_words') or ''}",
        f"Offerings: {', '.join(o.get('name') or '' for o in (ctx.get('offerings') or [])[:8])}",
    ]
    return "\n".join(p for p in parts if p.split(": ", 1)[-1].strip())


def _dro_directive(dro: Dict[str, Any]) -> str:
    """Turn the DRO into a COPY+STRUCTURE directive the composer must obey.
    The renderer owns visual tokens (color/type/spacing); here the DRO drives
    the CONCEPT VOICE in copy and the section order — the bespoke lever."""
    d = (dro or {}).get("decisions") or {}
    hero = d.get("hero_concept") or {}
    v2v = d.get("voice_to_visual") or {}
    layout = d.get("layout") or {}
    motion = d.get("motion") or {}
    notes = "; ".join(v2v.get("notes") or [])
    concept = hero.get("concept_statement") or ""
    return f"""DESIGN RATIONALE — OBEY THIS (authored from the practitioner's intake; it is the brief, not a suggestion):
- CONCEPT: {concept}
  Thread this concept through ALL copy. Reframe the hero headline, section eyebrows/labels, and EVERY call-to-action in the concept's voice (e.g. a "Royal Palace" concept turns "Book Now" into "Book Your Throne" and a testimonials eyebrow into "THE COURT"). Never use generic labels when an in-concept one fits.
- Hero direction: {hero.get('direction') or ''}. The hero copy must deliver the concept above, not a generic value prop.
- Voice→visual couplings to honor in copy: {notes or '(none)'}
- Section order / hierarchy: {layout.get('hierarchy_approach') or 'guided_descent'} — order sections as a persuasion funnel (hook → credibility → offer → proof → conversion → contact), shaped by this hierarchy.
- Pacing: layout density={layout.get('density') or 'balanced'}, motion={motion.get('temperature') or 'subtle_entrance'} — match copy length/rhythm to it (airy/quiet → fewer words; dense/expressive → punchier, more).
- Still NEVER invent facts. Concept reframing is about VOICE, not fabricated specifics."""


def compose_spec_llm(ctx: Dict[str, Any], brief_notes: str = "",
                     dro: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    from studio_designer_agent import _call_claude, _extract_json

    bundle = ctx.get("bundle") or {}
    voice = bundle.get("voice") or {}
    intel = bundle.get("practitioner_intelligence") or {}
    biz = ctx["business"]
    off_names = ", ".join(o.get("name") or "" for o in (ctx.get("offerings") or [])[:8])
    n_testi = len(ctx.get("testimonials") or [])

    dro_block = ("\n\n" + _dro_directive(dro) + "\n") if dro else ""

    prompt = f"""You are a creative director composing a one-page website. You do NOT write HTML or CSS — the platform renders everything. Your job: choose section modules + expression variants, and write the copy in the practitioner's voice.
{dro_block}
BUSINESS
- Name: {biz['name']}
- Type: {biz['type']}
- Tagline: {(bundle.get('business') or {}).get('tagline') or '(none)'}
- About (real, from the practitioner): {str(intel.get('about_business') or intel.get('about_me') or '')[:600] or '(none provided)'}
- Voice/tone: {voice.get('brand_voice') or ''} {voice.get('tone_words') or ''}
- Design vibe: {ctx['dna']['vibe']}, intensity: {ctx['dna']['intensity']}
- Real offerings on file: {off_names or '(none)'}
- Real testimonials on file: {n_testi}
- Public custom modules the business RUNS (surface via the "showcase" section): {', '.join((m.get('title') or '') + f" ({len(m.get('entries') or [])})" for m in (ctx.get('public_modules') or [])) or '(none)'}
- Contact wiring: a real contact form + {('hours, ' if (ctx.get('contact') or {}).get('hours') else '')}{('address, ' if (ctx.get('contact') or {}).get('address') else '')}{('phone, ' if (ctx.get('contact') or {}).get('phone') else '')}socials render automatically in the "contact" section — you only write its framing.
{f'- Practitioner notes for this build: {brief_notes[:400]}' if brief_notes else ''}

AVAILABLE MODULES (use each at most once; order is yours except hero first, contact last):
{_module_menu()}

RULES
- If a DESIGN RATIONALE block appears above, it OVERRIDES generic instincts: concept-voice copy (in-concept headline/eyebrows/CTAs) and the section order it specifies are REQUIRED, not optional.
- Copy must sound like THIS practitioner, not a template. Specific beats generic.
- NEVER invent facts, testimonials, credentials, or offerings. The offerings and
  testimonials modules render the real records automatically — you only write the
  section framing (eyebrow/headline/intro).
- Include "offerings" only if offerings exist; "testimonials" only if testimonials exist;
  "store" only if sellable products exist ({(ctx.get('store') or {}).get('enabled') and len((ctx.get('store') or {}).get('items') or []) or 0} on file).
- Include "showcase" whenever public custom modules exist (listed above) — it surfaces the real tools/programs the business runs; frame its eyebrow/headline/intro in-concept.
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


def _inject_color_overrides(html: str, business_id: str) -> str:
    """Apply per-element color overrides as a <style> block keyed on
    data-override-target — deterministic, no HTML rewriting, no LLM. Each
    color_role override (target_path → hex, from the Edit-Mode palette
    picker) sets that element's text color."""
    try:
        from agents.override_system.override_storage import overrides_as_lookup
        colors = overrides_as_lookup(business_id, "color_role") or {}
    except Exception:
        return html
    rules: List[str] = []
    for path, row in colors.items():
        hexv = ((row or {}).get("override_value") or "").strip()
        if not (hexv.startswith("#") and 4 <= len(hexv) <= 9):
            continue
        sel = str(path).replace("\\", "").replace('"', "").replace("<", "").replace(">", "")
        rules.append(f'[data-override-target="{sel}"]{{color:{hexv} !important;}}')
    if not rules:
        return html
    block = "<style>/* edit-mode color overrides */\n" + "\n".join(rules) + "\n</style>"
    return html.replace("</head>", block + "</head>", 1) if "</head>" in html else html + block


def render_and_persist(business_id: str, spec: List[Dict[str, Any]],
                       ctx: Optional[Dict[str, Any]] = None,
                       dro_id: Optional[str] = None) -> Dict[str, Any]:
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

    # DETERMINISTIC INLINE EDITS (no API): apply the practitioner's text +
    # color overrides onto the rendered HTML. Edits made in the editor
    # (words, colors) persist as overrides and show on re-render WITHOUT any
    # LLM call — the cost-reduction goal. Image swaps ride the slot system
    # above. A re-render is triggered on every override save (see the
    # override router → refresh_if_composed_async).
    try:
        from agents.override_system.override_resolver import resolve_html_overrides
        final_html = resolve_html_overrides(final_html, business_id)   # text
    except Exception as e:
        logger.warning(f"[composer] text override resolution failed (non-fatal): {e}")
    final_html = _inject_color_overrides(final_html, business_id)       # color

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
    if dro_id:
        cfg["design_rationale_id"] = dro_id   # powers the "why your site looks this way" view (PR4)
    sb_clients.sb_patch_as_service(
        f"/business_sites?id=eq.{site['id']}",
        {"html_content": final_html, "site_config": cfg, "status": "published"})

    return {"site_id": site["id"], "slug": ctx["business"]["slug"],
            "sections": [{"module": s["module"], "variant": s["variant"]} for s in spec],
            "slots": {"found": slots_meta.get("slots_found", []),
                      "populated": len(slots_meta.get("slots_populated") or [])},
            "url": f"https://{ctx['business']['slug']}.mysolutionist.app" if ctx["business"]["slug"] else None}


# DRO hero_concept.direction → hero module variant. Cinematic (full-bleed,
# art-directed) for image-led concepts; statement (oversized type, no photo)
# for typographic / visual-metaphor concepts (a real metaphor render is a
# later lever).
_HERO_DIRECTION_VARIANT = {
    "environment_mood": "cinematic",
    "artifact_showcase": "cinematic",
    "portrait_presence": "cinematic",
    # visual_metaphor would ideally render a constructed graphic, but that
    # render isn't built yet — use the cinematic image hero so there's always
    # a real hero image holder (no bare text-only hero).
    "visual_metaphor": "cinematic",
    "typographic_statement": "statement",
}


def _apply_hero_direction(spec: List[Dict[str, Any]], hero_concept: Optional[Dict[str, Any]]) -> None:
    """Deterministically set the hero variant from the DRO's concept direction
    (overrides the LLM's pick so the rationale reliably drives the hero)."""
    variant = _HERO_DIRECTION_VARIANT.get((hero_concept or {}).get("direction") or "")
    if not variant:
        return
    for s in spec:
        if s.get("module") == "hero":
            s["variant"] = variant
            return


def compose_site(business_id: str, brief_notes: str = "",
                 use_llm: bool = True) -> Dict[str, Any]:
    """Canonical site-compose entry (DRL PR3). Produces a Design Rationale
    Object first (best-effort), composes concept-threaded copy that obeys it,
    then renders + persists. Shared by the /compose endpoint and the
    Feature-2 `rebuild_site` background job, so both get DRO-driven output.
    Degrades gracefully: if DRO production fails, composes without it; if LLM
    composition fails, falls back to the deterministic default spec."""
    ctx = gather_context(business_id)
    dro: Optional[Dict[str, Any]] = None
    dro_id: Optional[str] = None
    source = "llm"

    if use_llm:
        # 1) Author the rationale from the practitioner's own words.
        try:
            from agents.composer.drl.passes import produce_dro
            dro = produce_dro(business_id, _assemble_intake_text(ctx))
            if dro:
                dro_id = dro.get("id")
        except Exception as e:
            logger.warning(f"[composer] DRO production failed (non-fatal): {e}")
        # 1b) DRO-driven DESIGN: the palette base (dark stage / light room) +
        # accent scarcity flow into the render via ctx; copy obeys it next.
        if dro:
            decisions = dro.get("decisions") or {}
            ctx["design"] = decisions
            ctx["dna"] = brand_dna.apply_dro_palette(ctx["dna"], decisions.get("palette"))
        # 2) Compose copy that obeys the rationale.
        try:
            spec = compose_spec_llm(ctx, brief_notes or "", dro=dro)
        except Exception as e:
            logger.warning(f"[composer] LLM composition failed, using default: {e}")
            spec, source = _default_spec(ctx), "default"
        # 3) Hero treatment from the DRO's concept direction (cinematic vs
        # typographic) — deterministic so the rationale reliably drives it.
        if dro:
            _apply_hero_direction(spec, (dro.get("decisions") or {}).get("hero_concept"))
    else:
        spec, source = _default_spec(ctx), "default"

    result = render_and_persist(business_id, spec, ctx, dro_id=dro_id)
    return {"composition_source": source, "design_rationale_id": dro_id, **result}


# ─── Endpoints ────────────────────────────────────────────────────────

class ComposeBody(BaseModel):
    business_id: str
    brief_notes: Optional[str] = None
    use_llm: bool = True


@router.post("/compose")
def compose(body: ComposeBody,
            _: UserSession = Depends(sb_clients.authed_request)) -> Dict[str, Any]:
    result = compose_site(body.business_id, body.brief_notes or "", body.use_llm)
    return {"ok": True, **result}


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


# ─── Arc 28b — live refresh on catalog change ─────────────────────────

def refresh_if_composed(business_id: str) -> bool:
    """Re-render a module-composer site from its stored spec (no LLM —
    deterministic and cheap). Called when offerings change so the site's
    offerings/store sections stay current without a manual recompose.
    Returns True when a refresh happened. No-op for legacy / Smart Sites
    pages (their own live-injection paths already handle freshness)."""
    ctx = gather_context(business_id)
    cfg = ((ctx.get("site") or {}).get("site_config") or {})
    if cfg.get("html_source") != "module-composer" or not cfg.get("page_spec"):
        return False
    spec = sanitize_spec(cfg["page_spec"], ctx)
    render_and_persist(business_id, spec, ctx)
    return True


def refresh_if_composed_async(business_id: str) -> None:
    """Fire-and-forget wrapper for request paths (offerings CRUD) — the
    catalog write must never wait on, or fail because of, a re-render."""
    import threading

    def _run() -> None:
        try:
            if refresh_if_composed(business_id):
                logger.info(f"[composer] refreshed composed site for {business_id[:8]}")
        except Exception as e:
            logger.warning(f"[composer] background refresh failed (non-fatal): {e}")

    threading.Thread(target=_run, daemon=True).start()
