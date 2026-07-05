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
from auth_supabase import AuthedUser, require_user

logger = logging.getLogger("site_composer")

router = APIRouter(prefix="/composer", tags=["site_composer"])

RAILWAY_BASE = "https://kmj-intake-server-production.up.railway.app"
COMPOSER_MARK = '<meta name="x-solutionist-composer" content="module-composer">'

_MAX_FIELD = {"body": 900, "intro": 400, "note": 300, "subheadline": 260,
              "pull_quote": 260, "headline": 120, "eyebrow": 60, "cta_label": 40}


# ─── Arc 2 "Ask the Owner" — design preferences ───────────────────────

_PREF_STR_CAP = 400
_IMAGERY_PRIORITIES = ("my_photos", "atmosphere", "typography")
_BOLDNESS_TO_INTENSITY = {1: "restrained", 2: "confident", 3: "bold"}


def sanitize_design_prefs(raw: Any) -> Optional[Dict[str, Any]]:
    """Lenient shape validation for the Ask-the-Owner design_prefs object:
    unknown keys dropped, strings trimmed + capped, feel_words ≤ 3,
    imagery_priority / boldness clamped to their enums. Returns None when
    nothing usable remains — callers treat that as 'no prefs given'."""
    if not isinstance(raw, dict):
        return None
    out: Dict[str, Any] = {}
    fw = raw.get("feel_words")
    if isinstance(fw, (list, tuple)):
        words = [str(w).strip()[:_PREF_STR_CAP] for w in fw
                 if isinstance(w, (str, int, float)) and str(w).strip()]
        if words:
            out["feel_words"] = words[:3]
    for key in ("inspiration", "avoid", "notes"):
        v = raw.get(key)
        if isinstance(v, str) and v.strip():
            out[key] = v.strip()[:_PREF_STR_CAP]
    ip = raw.get("imagery_priority")
    if isinstance(ip, str) and ip.strip().lower() in _IMAGERY_PRIORITIES:
        out["imagery_priority"] = ip.strip().lower()
    try:
        b = int(raw.get("boldness"))
    except (TypeError, ValueError):
        b = None
    if b in (1, 2, 3):
        out["boldness"] = b
    return out or None


def _persist_site_prefs(business_id: str, prefs: Dict[str, Any]) -> None:
    """Write sanitized prefs to businesses.settings.site_prefs via the
    read-modify-write settings idiom (same as rules_router.pause_all) so
    sibling settings keys survive. Called BEFORE gather_context so the
    compose that follows reads the fresh prefs back from settings."""
    from datetime import datetime, timezone
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{business_id}&select=settings&limit=1") or []
    if not rows:
        raise HTTPException(404, "business not found")
    settings = dict(rows[0].get("settings") or {})
    settings["site_prefs"] = {
        **prefs, "updated_at": datetime.now(timezone.utc).isoformat()}
    sb_clients.sb_patch_as_service(
        f"/businesses?id=eq.{business_id}", {"settings": settings})


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


def _platform_sms_capable() -> bool:
    """True when the platform can actually send SMS (Twilio primary or
    Telnyx fallback env present) — gates the contact-form SMS opt-in
    checkbox so we never collect consent we can't honor."""
    import os
    try:
        from sms_service import _twilio_configured
        if _twilio_configured():
            return True
    except Exception:
        pass
    return bool((os.environ.get("TELNYX_API_KEY") or "").strip()
                and (os.environ.get("TELNYX_PHONE_NUMBER") or "").strip())


def gather_context(business_id: str) -> Dict[str, Any]:
    import brand_engine
    bundle = brand_engine.get_bundle(business_id) or {}

    biz_rows = sb_clients.sb_get_as_service(
        # voice_profile added (2026-07-03) — feeds the DRL intake text.
        # created_at added (Arc 3) — feeds statband's years-in-business.
        f"/businesses?id=eq.{business_id}&select=id,name,type,settings,voice_profile,created_at&limit=1") or []
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
        # A2P compliance (Arc 1): the contact module renders the SMS
        # opt-in checkbox only when the platform can actually text.
        "sms_capable": _platform_sms_capable(),
    }

    # Arc 2 "Ask the Owner": stored prefs shape the DNA even on the no-LLM
    # path. feel_words feed the legacy vibe keyword matcher (_infer_vibe
    # reads voice.tone_words) and boldness maps onto the legacy intensity
    # ladder. Precedence: an explicit design.vibe_family still beats
    # feel_words (an exact enum choice outranks fuzzy words), but boldness —
    # the owner's freshest explicit answer — wins over the older
    # creative_expression intensity dial.
    site_prefs = (settings.get("site_prefs")
                  if isinstance(settings.get("site_prefs"), dict) else {})
    if site_prefs:
        feel = [str(w).strip() for w in (site_prefs.get("feel_words") or [])
                if str(w or "").strip()]
        if feel:
            voice = bundle.get("voice") if isinstance(bundle.get("voice"), dict) else {}
            tw = voice.get("tone_words")
            if isinstance(tw, list):
                voice["tone_words"] = tw + feel
            else:
                voice["tone_words"] = ((f"{tw} " if tw else "") + " ".join(feel))
            bundle["voice"] = voice
        intensity = _BOLDNESS_TO_INTENSITY.get(site_prefs.get("boldness"))
        if intensity:
            design_cfg = bundle.get("design") if isinstance(bundle.get("design"), dict) else {}
            expr = (design_cfg.get("creative_expression")
                    if isinstance(design_cfg.get("creative_expression"), dict) else {})
            expr["intensity"] = intensity
            design_cfg["creative_expression"] = expr
            bundle["design"] = design_cfg

    dna = brand_dna.build_brand_dna(business_id, bundle)
    return {
        "site_prefs": site_prefs,
        "store": store,
        "dna": dna,
        "bundle": bundle,
        "business": {"id": business_id, "name": biz.get("name") or "",
                     "type": biz.get("type") or "", "slug": slug,
                     "created_at": biz.get("created_at") or ""},
        "voice_profile": biz.get("voice_profile") if isinstance(biz.get("voice_profile"), dict) else {},
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

def sanitize_spec(raw: Any, ctx: Dict[str, Any],
                  mark_defaults: bool = False) -> List[Dict[str, Any]]:
    """Clamp an LLM (or stored) spec to the module registry: known
    modules and variants only, known content fields only, length caps,
    hero first, contact last, no duplicate modules.

    mark_defaults (Arc 3): sections whose variant had to be defaulted
    (missing/invalid — i.e. the LLM did NOT explicitly pick) carry an
    internal `_variant_defaulted` flag so the DRO symmetry preference
    can steer them; _apply_symmetry_preference strips the flag before
    anything is persisted. Stored-spec re-sanitizes (shuffle/refresh)
    keep the default False and are byte-identical to before."""
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
        defaulted = variant not in spec["variants"]
        if defaulted:
            variant = spec["variants"][0]
        content_in = sec.get("content") or {}
        content = {}
        for f in spec["fields"]:
            v = content_in.get(f)
            if isinstance(v, (int, float)):
                v = str(v)
            if isinstance(v, str) and v.strip():
                content[f] = v.strip()[:_MAX_FIELD.get(f, 200)]
        entry = {"module": mid, "variant": variant, "content": content}
        if mark_defaults and defaulted:
            entry["_variant_defaulted"] = True
        out.append(entry)

    # Structural guarantees regardless of what the LLM did.
    if not any(s["module"] == "hero" for s in out):
        hero_default = _default_spec(ctx)[0]
        if mark_defaults:
            hero_default = {**hero_default, "_variant_defaulted": True}
        out.insert(0, hero_default)
    if not any(s["module"] == "contact" for s in out):
        out.append({"module": "contact", "variant": "standard", "content": {}})
    out.sort(key=lambda s: (0 if s["module"] == "hero" else
                            2 if s["module"] == "contact" else 1))
    return out


def _default_spec(ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Deterministic vibe-keyed composition — the no-LLM floor. Copy
    comes from the practitioner's own words: tagline as the headline
    when present (business name is the fallback, not the lead), the
    elevator pitch as the supporting line. Never generated."""
    dna = ctx["dna"]
    biz = ctx["business"]
    hero_variant = {"warm": "split", "formal": "statement", "bold": "banner"}[dna["vibe"]]
    b = (ctx.get("bundle") or {}).get("business") or {}
    tagline = str(b.get("tagline") or "").strip()
    pitch = str(b.get("elevator_pitch") or "").strip()
    headline = tagline or biz["name"]
    subheadline = pitch if pitch and pitch != headline else (tagline if tagline != headline else "")
    spec = [
        {"module": "hero", "variant": hero_variant,
         "content": {"headline": headline, "subheadline": subheadline,
                     "cta_label": "Book a session"}},
        # about body left empty on purpose: the about module backfills it
        # from practitioner_intelligence.about_business (real data) and
        # DROPS the section when nothing real exists.
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
    """Build the intake material the DRL signal-detection pass reads.

    Quality pass (2026-07-03): the DRL was reasoning over ~6 short fields,
    so most signals came back `inferred`/low-confidence and were dropped
    before authoring — the engine ran on fumes. Now we hand it every scrap
    of the practitioner's OWN language the system already holds: identity
    file, brand-kit messaging, voice profile, offering descriptions, and
    their customers' words (testimonial quotes). The detection prompt is
    untouched — only its input got richer.
    """
    bundle = ctx.get("bundle") or {}
    intel = bundle.get("practitioner_intelligence") or {}
    voice = bundle.get("voice") or {}
    biz = ctx["business"]
    # ctx["business"] is the reduced dict — settings + voice_profile ride
    # ctx directly (see gather_context).
    settings = ctx.get("settings") if isinstance(ctx.get("settings"), dict) else {}
    kit = (settings.get("brand_kit") or {}) if isinstance(settings.get("brand_kit"), dict) else {}
    vp = ctx.get("voice_profile") if isinstance(ctx.get("voice_profile"), dict) else {}
    offerings = ctx.get("offerings") or []

    kit_tone = kit.get("tone_words")
    kit_tone_str = " ".join(kit_tone) if isinstance(kit_tone, list) else (kit_tone or "")

    offering_descs = " | ".join(
        (o.get("description") or "").strip()[:140]
        for o in offerings[:5] if (o.get("description") or "").strip()
    )

    quotes = []
    for t in (ctx.get("testimonials") or [])[:4]:
        if isinstance(t, dict):
            q = (t.get("quote") or t.get("text") or t.get("content") or "").strip()
            if q:
                quotes.append(q[:160])

    parts = [
        f"Business name: {biz.get('name')}",
        f"Business type: {biz.get('type')}",
        f"Tagline: {(bundle.get('business') or {}).get('tagline') or kit.get('tagline') or ''}",
        f"Elevator pitch: {kit.get('elevator_pitch') or ''}",
        f"About the business: {intel.get('about_business') or ''}",
        f"About the practitioner: {intel.get('about_me') or ''}",
        f"Voice / tone: {voice.get('brand_voice') or ''} {voice.get('tone_words') or ''} {kit_tone_str}".rstrip(),
        f"Communication style: {(vp or {}).get('tone') or ''} {(vp or {}).get('style') or ''}".rstrip(),
        f"Offerings: {', '.join(o.get('name') or '' for o in offerings[:8])}",
        f"How they describe their offerings: {offering_descs}",
        f"In their customers' words: {' | '.join(quotes)}",
    ]
    text = "\n".join(p for p in parts if p.split(": ", 1)[-1].strip())

    # Arc 2 "Ask the Owner": the owner's stated preferences are the highest-
    # priority evidence the DRL can get — a clearly-attributed first-person
    # block so detect_signals can quote it VERBATIM (its whole design is
    # evidence-quoted signals). Only fields actually present render; when no
    # prefs exist the intake text is byte-identical to before.
    prefs = ctx.get("site_prefs") if isinstance(ctx.get("site_prefs"), dict) else {}
    pref_lines: List[str] = []
    if prefs.get("feel_words"):
        pref_lines.append("The site should feel: "
                          + ", ".join(str(w) for w in prefs["feel_words"]) + ".")
    if prefs.get("inspiration"):
        pref_lines.append(f"Inspiration: {prefs['inspiration']}")
    if prefs.get("avoid"):
        pref_lines.append(f"It should NOT feel: {prefs['avoid']}")
    if prefs.get("imagery_priority"):
        label = {"my_photos": "lead with my own photos",
                 "atmosphere": "atmosphere / mood imagery",
                 "typography": "typography-led, minimal imagery",
                 }.get(prefs["imagery_priority"], prefs["imagery_priority"])
        pref_lines.append(f"Imagery: {label}.")
    if prefs.get("boldness") in (1, 2, 3):
        pref_lines.append(f"Boldness: {prefs['boldness']}/3.")
    if prefs.get("notes"):
        pref_lines.append(f"Notes: {prefs['notes']}")
    if pref_lines:
        text += ("\n\nTHE OWNER'S OWN STYLE WORDS "
                 "(verbatim, highest priority evidence):\n"
                 + "\n".join(pref_lines))
    return text


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
- Layout symmetry: {layout.get('symmetry') or 'unspecified'} — asymmetric_tension/editorial_columns lean toward the offset variants (hero "editorial", about "pullquote", offerings "featured", testimonials "marquee", gallery "mosaic"); centered_formal leans toward the centered ones (hero "statement", about "narrative", testimonials "spotlight").
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

VARIANT GUIDE (when to reach for the expressive variants):
- hero "editorial": asymmetric offset split, oversized display type, one accent-italic word — personality-forward, editorial brands.
- hero "constructed": typographic statement over a generated ornament field, NO photo — when the concept is abstract/metaphorical or imagery is weak.
- about "pullquote": magazine spread — one strong line pulled large + narrative column + framed portrait. Pick when the about copy has a quotable line.
- offerings "featured": the first offering as a flagship feature card (with image), the rest as numbered compact rows — when one offering clearly leads.
- "statband": 3-4 big real numbers (years in business, offerings, testimonials). Include for established businesses; it renders nothing when the numbers aren't there, so never lean copy on it.
- testimonials "marquee": one oversized hero quote + two supporting — when the best quote deserves a spotlight and 3+ exist.
- gallery "mosaic": varied-size image mosaic with soft fades — for visual businesses with strong imagery.

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
    # mark_defaults: sections without an explicit valid variant stay
    # steerable by the DRO symmetry preference (Arc 3).
    return sanitize_spec(parsed, ctx, mark_defaults=True)


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


_CONCEPT_STOP = {"the", "a", "an", "and", "or", "of", "for", "with", "that",
                 "this", "their", "your", "our", "its", "into", "like",
                 "feels", "feel", "where", "when", "every", "into"}


def _dro_slot_brief(ctx: Dict[str, Any], dro: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Distill the DRO (+ business specifics) into the enriched_brief shape
    the slot pipeline's query/prompt composers already consume — so hero/
    atmosphere/gallery imagery derives from the DESIGN CONCEPT instead of
    a generic '{subject} interior {mood}' stock query. Pure composition."""
    biz = ctx.get("business") or {}
    d = ((dro or {}).get("decisions") or {})
    hero = d.get("hero_concept") or {}
    concept = str(hero.get("concept_statement") or "")

    # Concept keywords: metaphor_elements first (already short terms),
    # then significant words from the concept statement.
    keywords: List[str] = [str(k) for k in (hero.get("metaphor_elements") or []) if str(k or "").strip()]
    for w in re.findall(r"[A-Za-z]+", concept):
        lw = w.lower()
        if len(lw) > 3 and lw not in _CONCEPT_STOP and lw not in [k.lower() for k in keywords]:
            keywords.append(lw)
        if len(keywords) >= 8:
            break

    # Vibe text: _extract_mood substring-matches its vocab against this.
    vibe_bits = [
        str((d.get("palette") or {}).get("temperature") or ""),
        str((d.get("motion") or {}).get("temperature") or ""),
        str((d.get("typography") or {}).get("display_personality") or ""),
        str((d.get("whitespace") or {}).get("philosophy") or ""),
        str((ctx.get("dna") or {}).get("vibe") or ""),
    ]
    return {
        "inferred_vibe": " ".join(b for b in vibe_bits if b).strip(),
        "brand_metaphor": concept,
        "content_archetype": str(biz.get("type") or ""),
        "concept_keywords": keywords,
    }


def _ensure_og_image(html: str, slot_records: Dict[str, Any]) -> str:
    """After slot resolution the hero image URL is knowable — if the shell
    didn't already emit og:image (no brand social card), promote the
    resolved hero to the share image. Deterministic head injection, same
    trust model as _mark/_inject_color_overrides."""
    if 'property="og:image"' in html or "</head>" not in html:
        return html
    rec = (slot_records or {}).get("hero_main") or {}
    url = str(rec.get("custom_url") or rec.get("default_url") or "")
    if not url.startswith("http"):
        return html
    import html as _h
    u = _h.escape(url, quote=True)
    block = (f'<meta property="og:image" content="{u}">\n'
             f'<meta name="twitter:card" content="summary_large_image">\n'
             f'<meta name="twitter:image" content="{u}">\n')
    return html.replace("</head>", block + "</head>", 1)


def render_and_persist(business_id: str, spec: List[Dict[str, Any]],
                       ctx: Optional[Dict[str, Any]] = None,
                       dro_id: Optional[str] = None,
                       dro: Optional[Dict[str, Any]] = None,
                       dro_status: Optional[str] = None,
                       dro_summary: Optional[str] = None) -> Dict[str, Any]:
    ctx = ctx or gather_context(business_id)
    title = ctx["business"]["name"] or "Welcome"

    # Ensure a business_sites row exists BEFORE rendering — the slug
    # drives the live URL and the page's canonical/og:url tags.
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

    html = _mark(site_modules.render_page(spec, ctx, title))

    # No DRO handed in (shuffle/refresh paths) → best-effort load of the
    # stored one so image queries stay concept-aware on re-renders.
    if dro is None:
        stored_id = dro_id or (((site or {}).get("site_config") or {})
                               .get("design_rationale_id"))
        if stored_id:
            try:
                rows = sb_clients.sb_get_as_service(
                    f"/design_rationales?id=eq.{stored_id}&select=dro&limit=1") or []
                dro = (rows[0] or {}).get("dro") if rows else None
            except Exception as e:
                logger.info(f"[composer] stored DRO fetch skipped: {e}")

    # Slot population (existing pipeline) then resolution into the HTML.
    # The enriched_brief threads the DRO's design concept into the
    # Unsplash/DALL-E query composers (params existed, were never passed).
    slots_meta: Dict[str, Any] = {}
    try:
        from agents.slot_system.builder_post_process import populate_slots_for_site
        slots_meta = populate_slots_for_site(
            html=html, business_id=business_id,
            enriched_brief=_dro_slot_brief(ctx, dro),
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
        final_html = _ensure_og_image(final_html, slot_records)
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
    # Arc 2: surface whether the rationale actually drove THIS compose.
    # Only compose_site sets these (shuffle/refresh re-renders pass None and
    # leave the stored status untouched — they reuse the composed spec).
    if dro_status:
        cfg["dro_status"] = dro_status
        if dro_status == "applied" and dro_summary:
            cfg["dro_summary"] = dro_summary
        else:
            cfg.pop("dro_summary", None)   # never show a stale summary on fallback
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
# for typographic concepts; constructed (Arc 3) for visual metaphors — a
# generated ornament field built FROM the concept words, no stock photo.
_HERO_DIRECTION_VARIANT = {
    "environment_mood": "cinematic",
    "artifact_showcase": "cinematic",
    "portrait_presence": "cinematic",
    "visual_metaphor": "constructed",
    "typographic_statement": "statement",
}


# Arc 3 — DRO layout.symmetry → variant preference map. Applied ONLY to
# sections the LLM did not explicitly pick a valid variant for (the
# `_variant_defaulted` marker from sanitize_spec / _ensure_connections),
# so an explicit composer choice always survives. Hero is additionally
# subject to _apply_hero_direction, which runs after and outranks this.
_SYMMETRY_ASYM = {"hero": "editorial", "about": "pullquote",
                  "offerings": "featured", "testimonials": "marquee",
                  "gallery": "mosaic"}
_SYMMETRY_CENTERED = {"hero": "statement", "about": "narrative",
                      "offerings": "cards", "testimonials": "spotlight",
                      "gallery": "grid"}
_SYMMETRY_MODULAR = {"hero": "split", "about": "portrait",
                     "offerings": "cards", "gallery": "grid"}


def _apply_symmetry_preference(spec: List[Dict[str, Any]],
                               layout: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Wire the DRO's layout.symmetry to the pixels (previously a no-op):
    asymmetric leans → offset/editorial variants, symmetric → centered
    ones. Tolerant matching (DRO values are prose-ish); always strips the
    internal `_variant_defaulted` markers, DRO or not."""
    sym = str((layout or {}).get("symmetry") or "").lower()
    if "asym" in sym or "tension" in sym or "editorial" in sym:
        pref = _SYMMETRY_ASYM
    elif "center" in sym or "formal" in sym or "symmetr" in sym:
        pref = _SYMMETRY_CENTERED
    elif "grid" in sym or "modular" in sym:
        pref = _SYMMETRY_MODULAR
    else:
        pref = None
    for s in spec:
        defaulted = bool(s.pop("_variant_defaulted", False))
        if not (pref and defaulted):
            continue
        variant = pref.get(s.get("module"))
        if variant and variant in site_modules.MODULES[s["module"]]["variants"]:
            s["variant"] = variant
    return spec


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


def _ensure_connections(spec: List[Dict[str, Any]], ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Deterministically GUARANTEE the site connects to everything the
    business actually uses — never left to the LLM (the cause of missing
    modules/sections). Adds any missing connected section: showcase (public
    custom modules), offerings, store. Contact + hero are guaranteed by
    sanitize_spec. Sections insert before contact so it stays last."""
    present = {s.get("module") for s in spec}
    additions: List[Dict[str, Any]] = []
    # Additions are by definition not an explicit LLM pick — mark them so
    # the DRO symmetry preference (Arc 3) may steer their variant; the
    # marker is stripped in _apply_symmetry_preference.
    if ctx.get("public_modules") and "showcase" not in present:
        additions.append({"module": "showcase", "variant": "cards", "content": {},
                          "_variant_defaulted": True})
    if (ctx.get("offerings")) and "offerings" not in present:
        additions.append({"module": "offerings", "variant": "cards", "content": {},
                          "_variant_defaulted": True})
    if (ctx.get("store") or {}).get("enabled") and "store" not in present:
        additions.append({"module": "store", "variant": "featured", "content": {},
                          "_variant_defaulted": True})
    if not additions:
        return spec
    contact_idx = next((i for i, s in enumerate(spec) if s.get("module") == "contact"), len(spec))
    return spec[:contact_idx] + additions + spec[contact_idx:]


def compose_site(business_id: str, brief_notes: str = "",
                 use_llm: bool = True,
                 design_prefs: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Canonical site-compose entry (DRL PR3). Produces a Design Rationale
    Object first (best-effort), composes concept-threaded copy that obeys it,
    then renders + persists. Shared by the /compose endpoint and the
    Feature-2 `rebuild_site` background job, so both get DRO-driven output.
    Degrades gracefully: if DRO production fails, composes without it; if LLM
    composition fails, falls back to the deterministic default spec.

    Arc 2 "Ask the Owner": `design_prefs` (feel_words/inspiration/avoid/
    imagery_priority/boldness/notes) is sanitized and persisted to
    businesses.settings.site_prefs BEFORE composing, so gather_context reads
    it back; recomposes without fresh prefs reuse the stored ones."""
    prefs = sanitize_design_prefs(design_prefs)
    if prefs:
        _persist_site_prefs(business_id, prefs)

    ctx = gather_context(business_id)
    dro: Optional[Dict[str, Any]] = None
    dro_id: Optional[str] = None
    source = "llm"
    dro_fail_reason: Optional[str] = None

    if use_llm:
        # 1) Author the rationale from the practitioner's own words.
        try:
            from agents.composer.drl.passes import produce_dro
            intake = _assemble_intake_text(ctx)
            dro = produce_dro(business_id, intake)
            if dro is None:
                # One retry — cheap insurance against a transient LLM/parse
                # hiccup before accepting a rationale-less compose.
                logger.info(f"[composer] DRO production returned None for "
                            f"{business_id[:8]} — retrying once")
                dro = produce_dro(business_id, intake)
            if dro:
                dro_id = dro.get("id")
            else:
                dro_fail_reason = "produce_dro returned None after retry"
        except Exception as e:
            dro_fail_reason = f"DRO production raised: {e}"
            logger.warning(f"[composer] DRO production failed (non-fatal): {e}")
        # 1b) DRO-driven DESIGN: the palette base (dark stage / light room) +
        # accent scarcity flow into the render via ctx; copy obeys it next.
        if dro:
            decisions = dro.get("decisions") or {}
            ctx["design"] = decisions
            ctx["dna"] = brand_dna.apply_dro_palette(ctx["dna"], decisions.get("palette"))
            # Quality pass (2026-07-03): the rest of the DRO reaches the
            # pixels too — typography personality, whitespace/density,
            # motion temperature. Practitioner-pinned fonts stay supreme.
            _design_cfg = ((ctx.get("bundle") or {}).get("design") or {})
            _expr = (_design_cfg.get("creative_expression") or {})
            _fonts_pinned = bool((_design_cfg.get("font_heading") or "").strip()
                                 or (_expr.get("hero_font") or "").strip())
            ctx["dna"] = brand_dna.apply_dro_style(
                ctx["dna"], decisions, fonts_pinned=_fonts_pinned)
        # 2) Compose copy that obeys the rationale.
        try:
            spec = compose_spec_llm(ctx, brief_notes or "", dro=dro)
        except Exception as e:
            logger.warning(f"[composer] LLM composition failed, using default: {e}")
            spec, source = _default_spec(ctx), "default"
            if dro:
                # No LLM picks exist on the fallback spec — every variant
                # is steerable by the DRO's symmetry preference (Arc 3).
                for s in spec:
                    s["_variant_defaulted"] = True
    else:
        spec, source = _default_spec(ctx), "default"
        dro_fail_reason = "use_llm=False (deterministic compose requested)"

    # Arc 2: surface the DRO outcome — no more silent skips. "applied" means
    # this compose's design + copy were driven by a fresh rationale;
    # "fallback" means it composed without one (reason logged below).
    dro_status = "applied" if dro else "fallback"
    dro_summary: Optional[str] = None
    if dro:
        dro_summary = ((((dro.get("decisions") or {}).get("hero_concept") or {})
                        .get("concept_statement"))
                       or dro.get("summary_for_practitioner") or None)
    else:
        logger.warning(f"[composer] DRO FALLBACK compose for business "
                       f"{business_id}: {dro_fail_reason or 'unknown reason'}")

    # Deterministically guarantee the site connects to everything the business
    # uses (modules/offerings/store) — regardless of LLM choices or fallback.
    spec = _ensure_connections(spec, ctx)

    # Arc 3 — wire the DRO's layout.symmetry to variant selection where the
    # LLM didn't explicitly pick (also strips the internal markers), then let
    # the hero-concept direction have the final word on the hero (constructed
    # for visual_metaphor, cinematic for image-led, statement for typographic).
    decisions = (dro or {}).get("decisions") or {}
    spec = _apply_symmetry_preference(spec, decisions.get("layout"))
    if dro:
        _apply_hero_direction(spec, decisions.get("hero_concept"))

    result = render_and_persist(business_id, spec, ctx, dro_id=dro_id, dro=dro,
                                dro_status=dro_status, dro_summary=dro_summary)
    return {"composition_source": source, "design_rationale_id": dro_id,
            "dro_status": dro_status, "dro_summary": dro_summary, **result}


# ─── Endpoints ────────────────────────────────────────────────────────

class ComposeBody(BaseModel):
    business_id: str
    brief_notes: Optional[str] = None
    use_llm: bool = True
    design_prefs: Optional[Dict[str, Any]] = None   # Arc 2 "Ask the Owner"


@router.post("/compose")
def compose(body: ComposeBody,
            _: UserSession = Depends(sb_clients.authed_request)) -> Dict[str, Any]:
    result = compose_site(body.business_id, body.brief_notes or "", body.use_llm,
                          design_prefs=body.design_prefs)
    return {"ok": True, **result}


@router.get("/rationale/{business_id}")
def get_rationale(business_id: str,
                  user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """Arc 2 (feeds Arc 4's panel) — 'why your site looks this way'.
    Owner-gated read of the stored rationale behind the composed page.
    Returns nulls (not 404) when no compose/rationale exists yet."""
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{business_id}&select=owner_id&limit=1") or []
    if not rows:
        raise HTTPException(status_code=404, detail="business not found")
    if str(rows[0].get("owner_id")) != str(user.id):
        raise HTTPException(status_code=403, detail="not authorized for this business")

    site_rows = sb_clients.sb_get_as_service(
        f"/business_sites?business_id=eq.{business_id}"
        "&select=site_config&limit=1") or []
    cfg = (site_rows[0].get("site_config") or {}) if site_rows else {}

    rationale = None
    rid = cfg.get("design_rationale_id")
    if rid:
        dr_rows = sb_clients.sb_get_as_service(
            f"/design_rationales?id=eq.{rid}&select=id,dro,created_at&limit=1") or []
        if dr_rows:
            dro = dr_rows[0].get("dro") or {}
            rationale = {
                "id": dr_rows[0].get("id"),
                "created_at": dr_rows[0].get("created_at"),
                "signals": dro.get("signals"),           # each w/ verbatim evidence
                "decisions": dro.get("decisions"),       # each w/ because + from_signals
                "summary_for_practitioner": dro.get("summary_for_practitioner"),
            }
    return {"dro_status": cfg.get("dro_status"),
            "dro_summary": cfg.get("dro_summary"),
            "rationale": rationale}


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
