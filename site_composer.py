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

import hashlib
import hmac
import json
import logging
import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

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
_PREF_URL_CAP = 300
_IMAGERY_PRIORITIES = ("my_photos", "atmosphere", "typography")
_BOLDNESS_TO_INTENSITY = {1: "restrained", 2: "confident", 3: "bold"}
# Arc 5 "Design Depth" — v2 enums (frontend built to this exact contract).
_COLOR_DIRECTIONS = ("deep_dark", "soft_dark", "warm_light", "cool_light",
                     "paper_neutral")     # 1:1 with brand_dna._BASE_GROUNDS
_CTA_GOALS = ("book", "buy", "contact", "follow")
_AUDIENCE_CAP = 240
_MAX_INSPIRATION_URLS = 3
# Arc 6 "Creative Engine" — v3 creative brief enums/caps.
_LOUD_WHERE = ("motion", "type", "imagery", "layout")
_CREATIVE_CAPS = {"metaphor": 200, "surprise": 200, "remember": 160}
_TENSION_POLE_CAP = 80
# Arc 10 "offer clarity" — the owner's plain-words answer to "What exactly
# do you offer, and for whom?" (Kevin's rule: if the offer isn't clear,
# Chief asks in the interview; when answered, the site must make it
# unmistakable).
_OFFER_CAP = 600
# Site Arc 11 — explicit CONNECTIONS: the owner's yes/no answers to "what
# should this site plug into?". Every key optional; True forces the
# surface on (subject to real data), False forces it off, absent = the
# current auto behavior (byte-identical when the object is absent).
_CONNECTION_KEYS = ("booking", "store", "contact_form", "sms_updates",
                    "socials")


def _report_progress(cb, pct: int, stage: str) -> None:
    """Arc 10 — fail-soft progress ping for the compose loading bar.
    cb is the chief_jobs per-job reporter (or None on every non-job path:
    sync /compose, shuffle, refresh — those stay byte-identical). A cb
    error must NEVER break a compose."""
    if cb is None:
        return
    try:
        cb(pct, stage)
    except Exception as e:
        logger.debug(f"[composer] progress cb error (ignored): {e}")


def _sanitize_pref_url(u: Any) -> Optional[str]:
    """One inspiration URL: http/https only, hostname required + lowercased,
    fragments stripped. Lenient: a bare domain gets https:// prefixed.
    Returns None when nothing safe remains."""
    from urllib.parse import urlparse, urlunparse
    if not isinstance(u, str) or not u.strip():
        return None
    s = u.strip()[:_PREF_URL_CAP]
    if "://" not in s and not s.lower().startswith(("javascript:", "data:", "vbscript:", "file:", "ftp:")):
        s = "https://" + s
    try:
        p = urlparse(s)
    except ValueError:
        return None
    if p.scheme not in ("http", "https") or not p.hostname:
        return None
    host = p.hostname.lower()
    netloc = host + (f":{p.port}" if p.port else "")
    return urlunparse((p.scheme, netloc, p.path or "", p.params, p.query, ""))


def sanitize_design_prefs(raw: Any) -> Optional[Dict[str, Any]]:
    """Lenient shape validation for the Ask-the-Owner design_prefs object
    (v2, Arc 5 — every field optional, backward compatible with v1):
    unknown keys dropped, strings trimmed + capped, feel_words ≤ 3,
    inspiration_urls ≤ 3 (http/https only, hostnames lowercased),
    colors {use_brand, direction, love ≤ 4, avoid ≤ 4}, audience ≤ 240,
    cta_goal / imagery_priority / boldness clamped to their enums.
    Returns None when nothing usable remains — callers treat that as
    'no prefs given'."""
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

    # Arc 10 "offer clarity" — the owner's own words on what they offer
    # and for whom. Same leniency as the other free-text prefs, its own
    # (larger) cap; persisted with site_prefs like everything else.
    offer = raw.get("offer")
    if isinstance(offer, str) and offer.strip():
        out["offer"] = offer.strip()[:_OFFER_CAP]

    # v2 — inspiration_urls (validated; bad entries silently dropped)
    iu = raw.get("inspiration_urls")
    if isinstance(iu, (list, tuple)):
        urls: List[str] = []
        for u in iu:
            su = _sanitize_pref_url(u)
            if su and su not in urls:
                urls.append(su)
            if len(urls) >= _MAX_INSPIRATION_URLS:
                break
        if urls:
            out["inspiration_urls"] = urls

    # v2 — colors {use_brand, direction, love[≤4], avoid[≤4]}
    c = raw.get("colors")
    if isinstance(c, dict):
        cout: Dict[str, Any] = {}
        if isinstance(c.get("use_brand"), bool):
            cout["use_brand"] = c["use_brand"]
        d = c.get("direction")
        if isinstance(d, str) and d.strip().lower() in _COLOR_DIRECTIONS:
            cout["direction"] = d.strip().lower()
        for key in ("love", "avoid"):
            v = c.get(key)
            if isinstance(v, (list, tuple)):
                vals = [str(x).strip()[:40] for x in v
                        if isinstance(x, (str, int, float)) and str(x).strip()]
                if vals:
                    cout[key] = vals[:4]
        if cout:
            out["colors"] = cout

    # v2 — audience + cta_goal
    aud = raw.get("audience")
    if isinstance(aud, str) and aud.strip():
        out["audience"] = aud.strip()[:_AUDIENCE_CAP]
    goal = raw.get("cta_goal")
    if isinstance(goal, str) and goal.strip().lower() in _CTA_GOALS:
        out["cta_goal"] = goal.strip().lower()

    # Site Arc 11 — connections {booking, store, contact_form,
    # sms_updates, socials}: strict bools only (a truthy string is NOT
    # owner intent); unknown keys dropped; empty → omitted entirely so
    # absent stays byte-identical to the auto behavior.
    cn = raw.get("connections")
    if isinstance(cn, dict):
        cnout = {k: cn[k] for k in _CONNECTION_KEYS
                 if isinstance(cn.get(k), bool)}
        if cnout:
            out["connections"] = cnout

    ip = raw.get("imagery_priority")
    if isinstance(ip, str) and ip.strip().lower() in _IMAGERY_PRIORITIES:
        out["imagery_priority"] = ip.strip().lower()
    try:
        b = int(raw.get("boldness"))
    except (TypeError, ValueError):
        b = None
    if b in (1, 2, 3):
        out["boldness"] = b

    # v3 (Arc 6) — creative brief: metaphor/surprise/remember free text,
    # loud_where enum, tension {pole_a, pole_b, lean 1..5}. All optional;
    # bad entries silently dropped, same leniency as everything above.
    cr = raw.get("creative")
    if isinstance(cr, dict):
        cout: Dict[str, Any] = {}
        for key, cap in _CREATIVE_CAPS.items():
            v = cr.get(key)
            if isinstance(v, str) and v.strip():
                cout[key] = v.strip()[:cap]
        lw = cr.get("loud_where")
        if isinstance(lw, str) and lw.strip().lower() in _LOUD_WHERE:
            cout["loud_where"] = lw.strip().lower()
        tn = cr.get("tension")
        if isinstance(tn, dict):
            pa = str(tn.get("pole_a") or "").strip()[:_TENSION_POLE_CAP]
            pb = str(tn.get("pole_b") or "").strip()[:_TENSION_POLE_CAP]
            if pa and pb:
                tout: Dict[str, Any] = {"pole_a": pa, "pole_b": pb}
                try:
                    lean = int(tn.get("lean"))
                except (TypeError, ValueError):
                    lean = None
                if lean in (1, 2, 3, 4, 5):
                    tout["lean"] = lean
                cout["tension"] = tout
        if cout:
            out["creative"] = cout
    return out or None


def _persist_site_prefs(business_id: str, prefs: Dict[str, Any]) -> None:
    """Write sanitized prefs to businesses.settings.site_prefs via the
    read-modify-write settings idiom (same as rules_router.pause_all) so
    sibling settings keys survive. Called BEFORE gather_context so the
    compose that follows reads the fresh prefs back from settings.
    Arc 5: the stored reference_analysis rides along — compose_site
    re-runs it only when the inspiration_urls actually changed."""
    from datetime import datetime, timezone
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{business_id}&select=settings&limit=1") or []
    if not rows:
        raise HTTPException(404, "business not found")
    settings = dict(rows[0].get("settings") or {})
    prior = settings.get("site_prefs") if isinstance(settings.get("site_prefs"), dict) else {}
    fresh = {**prefs, "updated_at": datetime.now(timezone.utc).isoformat()}
    if isinstance(prior.get("reference_analysis"), dict):
        fresh["reference_analysis"] = prior["reference_analysis"]
    settings["site_prefs"] = fresh
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

    # Only real dict rows the owner left visible reach composed sites —
    # hidden quotes (show_on_website=False) must not render, inflate the
    # statband count, or pad the LLM prompt; legacy string entries are
    # dropped (modules also self-defend, but the context is the choke point).
    _testi_raw = ((settings.get("website_content") or {}).get("testimonials")) or []
    testimonials = [t for t in _testi_raw
                    if isinstance(t, dict) and t.get("show_on_website", True)]

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

    # Arc 5 "Design Depth": the owner's color language steers derivation
    # deterministically — colors.love/avoid/use_brand nudge the accent in
    # derive_palette; colors.direction is a HARD ground preference applied
    # here so no-DRO paths (fallback compose, shuffle, refresh) honor it
    # too. compose_site re-asserts it after apply_dro_palette (owner beats
    # model) and logs when the DRO's base was overridden.
    color_prefs = (site_prefs.get("colors")
                   if isinstance(site_prefs.get("colors"), dict) else None)
    dna = brand_dna.build_brand_dna(business_id, bundle, color_prefs=color_prefs)
    if (color_prefs or {}).get("direction"):
        dna = brand_dna.apply_owner_ground(dna, color_prefs["direction"])
    cta_goal = (site_prefs.get("cta_goal")
                if site_prefs.get("cta_goal") in _CTA_GOALS else None)

    # Site Arc 11 — explicit CONNECTIONS (sanitized at the door, persisted
    # with site_prefs). Hard OFF switches apply here at the choke point so
    # every downstream consumer (modules, cta ladders, header, specs)
    # honors them without local checks:
    #   booking=False → ctx.booking disabled (CTAs fall to #contact)
    #   store=False   → ctx.store disabled (section + buy-goal href gone)
    # ON switches are honored by the modules/_ensure_connections (they
    # need real data to act on). Absent object → connections is None and
    # every behavior is byte-identical to before.
    connections = (site_prefs.get("connections")
                   if isinstance(site_prefs.get("connections"), dict) else None)
    if connections:
        if connections.get("booking") is False:
            booking = {"enabled": False, "url": ""}
        if connections.get("store") is False:
            store = {**store, "enabled": False}
        # sms_updates=True → the footer's "Text {keyword} to connect"
        # line needs the practitioner's routing keyword (sms_keywords
        # table, OPERATE → Text/SMS). Fetched only when asked for;
        # fail-soft — no keyword, no line.
        if connections.get("sms_updates") is True:
            try:
                kw_rows = sb_clients.sb_get_as_service(
                    f"/sms_keywords?business_id=eq.{business_id}"
                    "&select=keyword&limit=1") or []
                if kw_rows and kw_rows[0].get("keyword"):
                    contact["sms_keyword"] = str(kw_rows[0]["keyword"])
            except Exception as e:
                logger.info(f"[composer] sms keyword lookup skipped: {e}")

    return {
        "site_prefs": site_prefs,
        "cta_goal": cta_goal,
        "connections": connections,
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

# Site Arc 9 — LLM markdown leaking into HTML: the live h1 rendered
# literal asterisks ('amplify your *impact*'). Spec copy is plain text;
# emphasis is the renderer's job (accent_headline). Strip *em*, **bold**,
# _em_, __bold__ and `code` wrappers everywhere, keeping the inner text.
_MD_STAR_RE = re.compile(r"\*{1,3}([^*\n]+)\*{1,3}")
_MD_UNDER_RE = re.compile(r"(?<![A-Za-z0-9])_{1,2}([^_\n]+)_{1,2}(?![A-Za-z0-9])")
_MD_TICK_RE = re.compile(r"`+([^`\n]+)`+")


def _strip_markdown_text(s: str) -> str:
    out = _MD_STAR_RE.sub(r"\1", s)
    out = _MD_UNDER_RE.sub(r"\1", out)
    out = _MD_TICK_RE.sub(r"\1", out)
    return out


def _strip_markdown_deep(value: Any) -> Any:
    """Recursively strip markdown emphasis from every string in a spec
    payload (dicts/lists walked; non-strings untouched)."""
    if isinstance(value, str):
        return _strip_markdown_text(value)
    if isinstance(value, list):
        return [_strip_markdown_deep(v) for v in value]
    if isinstance(value, dict):
        return {k: _strip_markdown_deep(v) for k, v in value.items()}
    return value


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
    # Site Arc 9 — markdown emphasis never reaches the HTML (recursive,
    # every string field in the spec).
    sections_in = _strip_markdown_deep(sections_in)
    out: List[Dict[str, Any]] = []
    seen = set()
    for sec in (sections_in or []):
        if not isinstance(sec, dict):
            continue
        mid = sec.get("module")
        spec = site_modules.MODULES.get(mid)
        # Site Arc 10: interstitials (the ceremony seams) legitimately
        # appear 1-3 times per page — exempt from the module dedupe so
        # stored-spec re-sanitizes (shuffle/refresh/choose) keep them.
        if not spec or (mid in seen and mid != "interstitial"):
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
    goal_label = _CTA_GOAL_LABELS.get(str(ctx.get("cta_goal") or ""),
                                      "Book a session")
    spec = [
        {"module": "hero", "variant": hero_variant,
         "content": {"headline": headline, "subheadline": subheadline,
                     "cta_label": goal_label}},
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
        # Site Arc 10: internal modules (interstitial ceremony seams) are
        # never offered to the composer LLM — the deterministic ceremony
        # pass owns their placement.
        if spec.get("internal"):
            continue
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

    ORDER MATTERS (Arc 7): detect_signals truncates this text at a fixed
    cap, so blocks are ordered by evidence priority — (1) the owner's own
    style words + creative brief, (2) the reference-site analysis, then
    (3) tagline/pitch/about/voice and (4) offerings/testimonials. The
    owner's freshest evidence must NEVER be the part that truncates
    (previously it was appended LAST — rich businesses lost exactly the
    new answers). When no prefs/reference analysis exist the output is
    byte-identical to the plain parts join.
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
    base_text = "\n".join(p for p in parts if p.split(": ", 1)[-1].strip())

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
    if prefs.get("inspiration_urls"):
        pref_lines.append("Sites I admire: "
                          + ", ".join(str(u) for u in prefs["inspiration_urls"][:3]))
    if prefs.get("avoid"):
        pref_lines.append(f"It should NOT feel: {prefs['avoid']}")
    # Arc 5 v2 — color language, audience, conversion goal.
    colors = prefs.get("colors") if isinstance(prefs.get("colors"), dict) else {}
    if colors:
        color_bits: List[str] = []
        direction = colors.get("direction")
        if direction:
            color_bits.append("overall ground: "
                              + str(direction).replace("_", " "))
        if colors.get("use_brand") is False:
            color_bits.append("do NOT use my existing brand colors")
        elif colors.get("use_brand") is True:
            color_bits.append("build on my brand colors")
        if colors.get("love"):
            color_bits.append("colors I love: "
                              + ", ".join(str(x) for x in colors["love"][:4]))
        if colors.get("avoid"):
            color_bits.append("colors to avoid: "
                              + ", ".join(str(x) for x in colors["avoid"][:4]))
        if color_bits:
            pref_lines.append("Color direction: " + "; ".join(color_bits) + ".")
    if prefs.get("audience"):
        pref_lines.append(f"Who it's for: {prefs['audience']}")
    if prefs.get("cta_goal"):
        goal_label = {"book": "book an appointment/session",
                      "buy": "buy from the store",
                      "contact": "reach out / get in touch",
                      "follow": "follow us on social",
                      }.get(prefs["cta_goal"], prefs["cta_goal"])
        pref_lines.append(f"The #1 thing a visitor should do: {goal_label}.")
    if prefs.get("imagery_priority"):
        label = {"my_photos": "lead with my own photos",
                 "atmosphere": "atmosphere / mood imagery",
                 "typography": "typography-led, minimal imagery",
                 }.get(prefs["imagery_priority"], prefs["imagery_priority"])
        pref_lines.append(f"Imagery: {label}.")
    if prefs.get("boldness") in (1, 2, 3):
        pref_lines.append(f"Boldness: {prefs['boldness']}/3.")
    # Arc 6 v3 — the creative brief also rides the intake so the signal
    # pass can quote it verbatim (the authoring pass ADDITIONALLY receives
    # it as a dedicated highest-priority block — see passes._creative_brief_block).
    creative = (prefs.get("creative")
                if isinstance(prefs.get("creative"), dict) else {})
    if creative.get("metaphor"):
        pref_lines.append(f"The business feels like: {creative['metaphor']}")
    if creative.get("surprise"):
        pref_lines.append("What people would never guess about us: "
                          f"{creative['surprise']}")
    if creative.get("remember"):
        pref_lines.append("Three seconds in, remember this: "
                          f"{creative['remember']}")
    if creative.get("loud_where"):
        pref_lines.append("The ONE loud design moment should live in: "
                          f"{creative['loud_where']}.")
    _tn = creative.get("tension") if isinstance(creative.get("tension"), dict) else {}
    if _tn.get("pole_a") and _tn.get("pole_b"):
        lean = _tn.get("lean")
        pref_lines.append(f"We are both '{_tn['pole_a']}' and '{_tn['pole_b']}'"
                          + (f" (lean {lean}/5 toward '{_tn['pole_b']}')"
                             if isinstance(lean, int) else "") + ".")
    if prefs.get("notes"):
        pref_lines.append(f"Notes: {prefs['notes']}")

    # Arc 7 — assemble in evidence-priority order: owner blocks FIRST so a
    # truncated transcript loses boilerplate, never the owner's answers.
    segments: List[str] = []
    if pref_lines:
        segments.append("THE OWNER'S OWN STYLE WORDS "
                        "(verbatim, highest priority evidence):\n"
                        + "\n".join(pref_lines))

    # Arc 10 "offer clarity" — the owner's offer statement leads right
    # after the style words: the single most important fact the page
    # must communicate. Absent → byte-identical to before.
    offer_stmt = str(prefs.get("offer") or "").strip()
    if offer_stmt:
        segments.append("WHAT THE BUSINESS OFFERS (the owner's own words — "
                        "the site MUST make this unmistakably clear): "
                        + offer_stmt)

    # Arc 5 — the platform's deterministic study of the reference sites the
    # owner named. DIRECTION EVIDENCE (mood/type-class/density), never a
    # copy source; the analyzer extracted these with no LLM involved.
    ra = prefs.get("reference_analysis") if isinstance(prefs.get("reference_analysis"), dict) else {}
    ok_results = [r for r in (ra.get("results") or [])
                  if isinstance(r, dict) and r.get("ok")]
    if ok_results:
        ref_lines: List[str] = []
        for r in ok_results[:3]:
            pal = r.get("palette") or {}
            fonts = r.get("fonts") or []
            classes = sorted({f.get("class") for f in fonts if f.get("class")})
            dens = (r.get("density") or {}).get("label") or ""
            bits = [f"palette reads '{pal.get('read') or 'unknown'}'"]
            if classes:
                bits.append("type is " + "/".join(classes))
            if dens:
                bits.append(f"layout feels {dens}")
            desc = (r.get("description") or r.get("title") or "").strip()
            if desc:
                bits.append(f'describes itself as "{desc[:160]}"')
            ref_lines.append(f"- {r.get('url')}: " + "; ".join(bits))
        segments.append("REFERENCE SITES THE OWNER ADMIRES (fetched + analyzed):\n"
                        + "\n".join(ref_lines)
                        + "\n(Direction evidence only — echo the mood, contrast, type "
                          "feel and pacing they imply. NEVER copy their content, "
                          "branding or exact colors.)")
    segments.append(base_text)
    return "\n\n".join(segments)


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


def _cta_goal_prompt_line(ctx: Dict[str, Any]) -> str:
    """Arc 5 — the owner's cta_goal steers the composer's CTA emphasis."""
    goal = str(ctx.get("cta_goal") or "")
    phrasing = {
        "book": "BOOK — every primary CTA drives to booking; hero + cta-band "
                "labels are booking phrasing (in the concept's voice).",
        "buy": "BUY — lead visitors to the store; the store section matters, "
               "CTA labels use shop/buy phrasing (in the concept's voice).",
        "contact": "CONTACT — CTAs invite a conversation (contact form), "
                   "not a transaction.",
        "follow": "FOLLOW — emphasize the social presence; frame the contact "
                  "section around following along, socials front and center.",
    }.get(goal)
    return (f"- THE OWNER'S #1 CONVERSION GOAL: {phrasing}\n" if phrasing else "")


def compose_spec_llm(ctx: Dict[str, Any], brief_notes: str = "",
                     dro: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    from studio_designer_agent import _call_claude, _extract_json

    bundle = ctx.get("bundle") or {}
    voice = bundle.get("voice") or {}
    intel = bundle.get("practitioner_intelligence") or {}
    biz = ctx["business"]
    off_names = ", ".join(o.get("name") or "" for o in (ctx.get("offerings") or [])[:8])
    n_testi = len(ctx.get("testimonials") or [])

    # Arc 10 "offer clarity" — the owner's own offer statement (site_prefs
    # rides ctx via gather_context) feeds the prompt directly + hardens
    # the 5-second rule below.
    _prefs = (ctx.get("site_prefs")
              if isinstance(ctx.get("site_prefs"), dict) else {})
    offer_stmt = str(_prefs.get("offer") or "").strip()
    offer_line = (f"\n- WHAT THE BUSINESS OFFERS (the owner's own words): {offer_stmt}"
                  if offer_stmt else "")

    dro_block = ("\n\n" + _dro_directive(dro) + "\n") if dro else ""

    prompt = f"""You are a creative director composing a one-page website. You do NOT write HTML or CSS — the platform renders everything. Your job: choose section modules + expression variants, and write the copy in the practitioner's voice.
{dro_block}
BUSINESS
- Name: {biz['name']}
- Type: {biz['type']}
- Tagline: {(bundle.get('business') or {}).get('tagline') or '(none)'}{offer_line}
- About (real, from the practitioner): {str(intel.get('about_business') or intel.get('about_me') or '')[:600] or '(none provided)'}
- Voice/tone: {voice.get('brand_voice') or ''} {voice.get('tone_words') or ''}
- Design vibe: {ctx['dna']['vibe']}, intensity: {ctx['dna']['intensity']}
- Real offerings on file: {off_names or '(none)'}
- Real testimonials on file: {n_testi}
- Public custom modules the business RUNS (surface via the "showcase" section): {', '.join((m.get('title') or '') + f" ({len(m.get('entries') or [])})" for m in (ctx.get('public_modules') or [])) or '(none)'}
- Contact wiring: a real contact form + {('hours, ' if (ctx.get('contact') or {}).get('hours') else '')}{('address, ' if (ctx.get('contact') or {}).get('address') else '')}{('phone, ' if (ctx.get('contact') or {}).get('phone') else '')}socials render automatically in the "contact" section — you only write its framing.
{_cta_goal_prompt_line(ctx)}{f'- Practitioner notes for this build: {brief_notes[:400]}' if brief_notes else ''}

AVAILABLE MODULES (use each at most once; order is yours except hero first, contact last):
{_module_menu()}

VARIANT GUIDE (when to reach for the expressive variants):
- hero "editorial": asymmetric offset split, oversized display type, one accent-italic word — personality-forward, editorial brands.
- hero "constructed": typographic statement over a generated ornament field, NO photo — when the concept is abstract/metaphorical or imagery is weak.
- hero "anchored": bottom-gravity film title — the headline rests on the FLOOR of a full-bleed photo under a baseline-deepening scrim and lands word by word — grounded, ceremonial, sanctuary-feel brands.
- offerings "menu": the engraved menu — hairline-ruled rows, italic serif names, whisper-caps prices right-aligned — when the price list itself is the craft object (salons, studios, ateliers).
- about "pullquote": magazine spread — one strong line pulled large + narrative column + framed portrait. Pick when the about copy has a quotable line.
- offerings "featured": the first offering as a flagship feature card (with image), the rest as numbered compact rows — when one offering clearly leads.
- "statband": 3-4 big real numbers (years in business, offerings, testimonials). Include for established businesses; it renders nothing when the numbers aren't there, so never lean copy on it.
- testimonials "marquee": one oversized hero quote + two supporting — when the best quote deserves a spotlight and 3+ exist.
- gallery "mosaic": varied-size image mosaic with soft fades — for visual businesses with strong imagery.

RULES
- If a DESIGN RATIONALE block appears above, it OVERRIDES generic instincts: concept-voice copy (in-concept headline/eyebrows/CTAs) and the section order it specifies are REQUIRED, not optional.
- Copy must sound like THIS practitioner, not a template. Specific beats generic.
- A stranger must know within 5 seconds what is offered and for whom — the hero
  subheadline and the offerings section carry this burden.{" Use the owner's offer statement verbatim-adjacent." if offer_stmt else ""}
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


def _dro_slot_brief(ctx: Dict[str, Any], dro: Optional[Dict[str, Any]],
                    spec: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Distill the DRO (+ business specifics) into the enriched_brief shape
    the slot pipeline's query/prompt composers already consume — so hero/
    atmosphere/gallery imagery derives from the DESIGN CONCEPT instead of
    a generic '{subject} interior {mood}' stock query. Pure composition.

    Site Arc 9: also carries the EMITTED palette (bg/accent/mode — mood +
    clash-rejection derive from the page's actual atmosphere, not DRO
    adjectives) and the rendered hero variant from `spec` (hero_main
    orientation follows the rendered crop, not the generic 16:9 slot).
    Neither key participates in _slot_concept_fingerprint."""
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
    brief: Dict[str, Any] = {
        "inferred_vibe": " ".join(b for b in vibe_bits if b).strip(),
        "brand_metaphor": concept,
        "content_archetype": str(biz.get("type") or ""),
        "concept_keywords": keywords,
    }
    pal = (ctx.get("dna") or {}).get("palette") or {}
    if pal.get("bg"):
        brief["palette"] = {"bg": pal.get("bg"), "accent": pal.get("accent"),
                            "mode": pal.get("mode")}
    hero_variant = next((s.get("variant") for s in (spec or [])
                         if isinstance(s, dict) and s.get("module") == "hero"),
                        None)
    if hero_variant:
        brief["hero_variant"] = str(hero_variant)
    return brief


def _slot_concept_fingerprint(slot_brief: Optional[Dict[str, Any]]) -> str:
    """Arc 7 — stable fingerprint of the imagery CONCEPT in a slot brief
    (concept_keywords + brand_metaphor, normalized: lowercased, keywords
    sorted as a set, metaphor whitespace-collapsed). Persisted on
    site_config.slot_concept at compose time; a later full recompose
    re-rolls the platform-default slot imagery ONLY when this fingerprint
    changed. Returns "" when the brief carries no concept at all (DRO
    fallback) — empty never triggers a re-roll, so a rationale-less
    recompose can't churn good concept imagery into generic stock."""
    sb = slot_brief or {}
    kws = sorted({str(k).strip().lower()
                  for k in (sb.get("concept_keywords") or [])
                  if str(k or "").strip()})
    metaphor = " ".join(str(sb.get("brand_metaphor") or "").lower().split())
    if not kws and not metaphor:
        return ""
    payload = json.dumps({"keywords": kws, "metaphor": metaphor},
                         sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


# ─── Arc 4 "Trust & Polish" — legacy-engine kill switch ──────────────

def legacy_site_engines_enabled() -> bool:
    """Env gate for the retired pre-composer build engines (Director
    build-with-loop, Smart Sites generate-html/multi-page/promote/
    smart-enable). Default OFF: the Module Composer is the canonical
    engine (ruled 2026-06-13). Set LEGACY_SITE_ENGINES=1 to re-open the
    old pipelines for debugging/forensics."""
    import os
    return (os.environ.get("LEGACY_SITE_ENGINES") or "").strip().lower() in (
        "1", "true", "yes", "on")


# ─── Arc 4 "Trust & Polish" — deterministic post-render quality gate ──
#
# Verifies the RENDERED DOCUMENT honors the decisions that were made
# (spec sections, fonts, palette vars, meta, alts, DRO wiring). Pure
# checks — no LLM, no network beyond what render already did. The gate
# REPORTS, it never rejects: publish always proceeds, the report lands
# in site_config.quality_report and failures log at WARNING. One
# self-heal re-render max for fixable SPEC issues (empty headline →
# refill from defaults; invalid variant → re-sanitize).

# module id → the stable DOM id its <section> carries (see site_modules).
_SECTION_DOM_IDS = {
    "hero": "top", "about": "about", "offerings": "offerings",
    "testimonials": "testimonials", "gallery": "gallery", "cta": "cta",
    "contact": "contact", "store": "store", "showcase": "showcase",
    "statband": "stats",
}

# Self-heal headline defaults — same voice as _default_spec (never
# invented facts, just the platform's neutral framing lines).
_HEAL_HEADLINES = {
    "about": "The practice", "offerings": "Ways to work together",
    "cta": "Ready when you are.", "contact": "Get in touch",
    "testimonials": "Kind words", "gallery": "The work",
    "store": "The shop", "showcase": "What we run",
    "statband": "By the numbers",
}

_TAG_STRIP_RE = re.compile(r"<[^>]+>")
_HEADLINE_TARGET_RE = re.compile(
    r'data-override-target="([a-z_]+)/(headline|eyebrow)"[^>]*>(.*?)</',
    re.IGNORECASE | re.DOTALL)
_SLOT_IMG_RE = re.compile(r"<img\b[^>]*\bdata-slot=\"([^\"]+)\"[^>]*>",
                          re.IGNORECASE)


def _visible_text(fragment: str) -> str:
    import html as _h
    return " ".join(_h.unescape(_TAG_STRIP_RE.sub(" ", str(fragment or ""))).split())


# ─── Site Arc 11 — TOTAL EDITABILITY coverage (report-only) ──────────
#
# Heuristic census of visible PRESENTATION-text nodes lacking a
# data-override-target: h1-h4/p/blockquote/figcaption elements with real
# innerText, no target on themselves or an ancestor, outside the known
# DATA-DRIVEN surfaces (business data is edited at the source — see the
# rule in site_modules/_base.py) and outside platform chrome. Pure
# stdlib parse; the gate reports the count, it never blocks publish.

_EDITABILITY_TAGS = frozenset({"h1", "h2", "h3", "h4", "p", "blockquote",
                               "figcaption"})
_EDITABILITY_VOID = frozenset({"img", "br", "hr", "input", "meta", "link",
                               "source", "wbr", "area", "base", "col",
                               "embed", "track"})
# Class PREFIXES whose subtree is data-driven or chrome (un-targeted by
# design — the _base.py editability rule): offering/product/testimonial/
# showcase records, contact logistics, SMS compliance copy, marquee tone
# words, header/footer chrome, runtime-only states.
_EDITABILITY_EXEMPT_PREFIXES = (
    "sxm-header", "sxm-footer",                       # structural chrome
    "sxm-testi", "sxm-mq",                            # testimonial records
    "sxm-sc-",                                        # showcase records
    "sxm-store",                                      # product records
    "sxm-off-desc", "sxm-off-head", "sxm-off-price",  # offering records
    "sxm-offmenu",
    "sxm-contact-logistics", "sxm-contact-social", "sxm-contact-mail",
    "sxm-sms-consent",                                # compliance copy
    "sxm-sent",                                       # runtime-only state
    "sxm-int-mq",                                     # marquee tone words
)


from html.parser import HTMLParser as _HTMLParserBase


class _EditabilityParser(_HTMLParserBase):
    """Tiny stack walk counting un-targeted presentation-text nodes.
    Exclusion (data-driven class prefix / aria-hidden) and targeting
    (data-override-target) both INHERIT down the subtree."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: List[list] = []   # rows: [tag, excluded, targeted, node|None]
        self.count = 0
        self.samples: List[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in _EDITABILITY_VOID:
            return
        a = {k.lower(): (v or "") for k, v in attrs}
        parent = self.stack[-1] if self.stack else None
        excluded = bool(parent and parent[1])
        targeted = bool(parent and parent[2])
        if a.get("aria-hidden") == "true":
            excluded = True
        cls = a.get("class", "")
        if any(c.startswith(_EDITABILITY_EXEMPT_PREFIXES)
               for c in cls.split()):
            excluded = True
        if "data-override-target" in a:
            targeted = True
        node = None
        if tag in _EDITABILITY_TAGS and not excluded and not targeted:
            node = {"tag": tag, "class": cls, "text": []}
        self.stack.append([tag, excluded, targeted, node])

    def handle_endtag(self, tag):
        if tag in _EDITABILITY_VOID:
            return
        while self.stack:                 # tolerant unwind to the open tag
            row = self.stack.pop()
            node = row[3]
            if node is not None:
                text = " ".join(" ".join(node["text"]).split())
                if text:
                    self.count += 1
                    label = node["tag"] + ("." + node["class"].split()[0]
                                           if node["class"] else "")
                    self.samples.append(f"{label}: {text[:60]}")
            if row[0] == tag:
                break

    def handle_data(self, data):
        if not data.strip():
            return
        for row in reversed(self.stack):
            if row[3] is not None:
                row[3]["text"].append(data)
                break


def _editability_coverage(html: str) -> tuple:
    """(count, samples) of visible presentation-text nodes lacking a
    data-override-target in the document body. Fail-soft: a parse error
    reports (0, ['parse skipped: …']) rather than failing the gate."""
    body = html
    m = re.search(r"<body\b[^>]*>(.*)</body>", str(html or ""),
                  re.IGNORECASE | re.DOTALL)
    if m:
        body = m.group(1)
    try:
        p = _EditabilityParser()
        p.feed(body)
        p.close()
        return p.count, p.samples[:8]
    except Exception as e:
        return 0, [f"parse skipped: {e}"]


def _heal_headline_default(module: str, ctx: Dict[str, Any]) -> str:
    if module == "hero":
        b = (ctx.get("bundle") or {}).get("business") or {}
        return (str(b.get("tagline") or "").strip()
                or (ctx.get("business") or {}).get("name") or "Welcome")
    return _HEAL_HEADLINES.get(module, "")


def _run_quality_gate(business_id: str, spec: List[Dict[str, Any]],
                      ctx: Dict[str, Any], html: str,
                      dro: Optional[Dict[str, Any]] = None,
                      dro_status: Optional[str] = None,
                      defaulted_modules: Optional[List[str]] = None,
                      previous_html: Optional[str] = None,
                      atelier_meta: Optional[Dict[str, Any]] = None,
                      ) -> tuple:
    """Conformance report over the final document. Returns
    (report_dict, fixes) where fixes is a list of fixable spec issues
    the ONE self-heal pass may apply ({"fix": "refill_headline",
    "module": mid} / {"fix": "resanitize"}).

    previous_html (Arc 7): the live document this render is about to
    replace — handed in on full recomposes only. Powers the
    'differs_from_previous' visible-change check (report-only, adds no
    fixes, never blocks publish)."""
    from datetime import datetime, timezone
    checks: List[Dict[str, Any]] = []
    fixes: List[Dict[str, Any]] = []

    # (a) every spec section produced non-empty HTML or was legitimately
    # dropped (renderer returned empty for lack of real data — logged).
    missing: List[str] = []
    dropped: List[str] = []
    needs_resanitize = False
    for s in spec:
        mid = s.get("module")
        mspec = site_modules.MODULES.get(mid)
        if not mspec:
            continue
        if mid == "interstitial":
            # Site Arc 10 — ceremony seams are chrome-like: no stable DOM
            # id, several per page, silence/thread render near-empty by
            # design. The gate treats them like the header (not checked).
            continue
        if s.get("variant") not in mspec["variants"]:
            needs_resanitize = True
        dom_id = _SECTION_DOM_IDS.get(mid)
        if dom_id and f'id="{dom_id}"' in html:
            continue
        # Not in the doc — legit only when the renderer yields nothing
        # for this data (e.g. testimonials with zero real rows).
        try:
            variant = (s.get("variant") if s.get("variant") in mspec["variants"]
                       else mspec["variants"][0])
            out, _css = mspec["render"](variant, s.get("content") or {}, ctx)
        except Exception:
            out = ""
        (dropped if not str(out or "").strip() else missing).append(mid)
    if dropped:
        logger.info(f"[composer.gate] sections legitimately dropped for "
                    f"{business_id[:8]} (no real data): {dropped}")
    checks.append({
        "name": "sections_rendered", "ok": not missing,
        "detail": (f"missing from document: {missing}; " if missing else "")
                  + (f"legitimately dropped (no data): {dropped}" if dropped
                     else ("all sections present" if not missing else ""))})
    if needs_resanitize:
        fixes.append({"fix": "resanitize"})

    # (b) the chosen font families actually reach the emitted CSS/links.
    typ = (ctx.get("dna") or {}).get("typography") or {}
    fonts_wanted = [f for f in {typ.get("heading"), typ.get("body")} if f]
    fonts_missing = [f for f in fonts_wanted if f not in html]
    checks.append({"name": "fonts_embedded", "ok": not fonts_missing,
                   "detail": (f"missing families: {fonts_missing}"
                              if fonts_missing else f"present: {fonts_wanted}")})

    # (c) --sx-* palette variables + head meta/OG block when data existed.
    pal_missing = [v for v in ("--sx-bg:", "--sx-accent:", "--sx-text:")
                   if v not in html]
    checks.append({"name": "palette_vars", "ok": not pal_missing,
                   "detail": (f"missing: {pal_missing}" if pal_missing
                              else "core --sx-* variables present")})
    try:
        meta = site_modules.build_page_meta(ctx)
    except Exception:
        meta = {}
    meta_problems: List[str] = []
    if meta.get("description") and '<meta name="description"' not in html:
        meta_problems.append("description")
    if meta.get("canonical") and 'rel="canonical"' not in html:
        meta_problems.append("canonical")
    if meta.get("og_title") and 'property="og:title"' not in html:
        meta_problems.append("og:title")
    if meta.get("jsonld") and "application/ld+json" not in html:
        meta_problems.append("jsonld")
    checks.append({"name": "meta_block", "ok": not meta_problems,
                   "detail": (f"data existed but tags missing: {meta_problems}"
                              if meta_problems else "meta/OG block consistent with data")})

    # (d) no empty alt on data-slot imagery.
    bad_alts: List[str] = []
    for m in _SLOT_IMG_RE.finditer(html):
        alt = re.search(r'\balt="([^"]*)"', m.group(0))
        if not alt or not alt.group(1).strip():
            bad_alts.append(m.group(1))
    checks.append({"name": "image_alts", "ok": not bad_alts,
                   "detail": (f'alt="" on slots: {bad_alts}' if bad_alts
                              else "all slot images carry alt text")})

    # (d2) Site Arc 11 — TOTAL EDITABILITY (report-only, adds no fixes):
    # count visible presentation-text nodes lacking data-override-target
    # (heuristic: h1-h4/p/blockquote/figcaption innerText outside the
    # data-driven exclusion classes — see _EDITABILITY_EXEMPT_PREFIXES).
    ed_count, ed_samples = _editability_coverage(html)
    checks.append({
        "name": "editability_coverage", "ok": ed_count == 0,
        "detail": (f"{ed_count} visible text node(s) lack an override "
                   f"target: {ed_samples}" if ed_count
                   else "every presentation-text node carries a target")})

    # (f) headline/eyebrow text non-empty for rendered sections. An
    # element that RENDERED but carries no visible text is a real defect
    # (spec hole or an override that blanked it).
    empty_texts: List[str] = []
    spec_by_module = {s.get("module"): s for s in spec}
    for m in _HEADLINE_TARGET_RE.finditer(html):
        mid, field, inner = m.group(1), m.group(2), m.group(3)
        if _visible_text(inner):
            continue
        empty_texts.append(f"{mid}/{field}")
        if field == "headline":
            sec = spec_by_module.get(mid)
            if sec is not None and not (sec.get("content") or {}).get("headline"):
                # Fixable: the spec itself lacks the headline — refill
                # from defaults. (If the spec HAS one and the doc is
                # empty, an override blanked it — not spec-fixable.)
                fixes.append({"fix": "refill_headline", "module": mid})
    checks.append({"name": "headlines_present", "ok": not empty_texts,
                   "detail": (f"rendered empty: {empty_texts}" if empty_texts
                              else "all rendered headlines/eyebrows carry text")})

    # (g) Arc 7 — visible-change check (full recompose only; caller hands
    # previous_html in). Report-only: an identical page never blocks
    # publish and adds no fixes, but the report now SAYS this compose
    # produced an identical page instead of silently shipping a no-op.
    if previous_html is not None and str(previous_html).strip():
        def _norm_hash(doc: str) -> str:
            return hashlib.sha256(
                re.sub(r"\s+", "", str(doc or "")).encode("utf-8")).hexdigest()
        identical = _norm_hash(html) == _norm_hash(previous_html)
        checks.append({
            "name": "differs_from_previous", "ok": not identical,
            "detail": ("this compose produced an identical page "
                       "(normalized hash unchanged from the previous document)"
                       if identical
                       else "document differs from the previous compose")})

    # (h) Arc 8 — atelier scoping check (REPORT-ONLY, adds no fixes):
    # every bespoke fragment that claims to be in the document has its
    # scoped .atl-{uid} CSS present and its root class in the body.
    frags = (atelier_meta or {}).get("fragments") or {}
    if frags:
        unscoped: List[str] = []
        for mid, f in frags.items():
            m_uid = re.search(r"atl-([0-9a-f]{6,12})",
                              str((f or {}).get("html") or ""))
            if not m_uid:
                unscoped.append(f"{mid}: no atl- uid on fragment")
                continue
            uid = m_uid.group(1)
            if f"atl-{uid}" not in html or f".atl-{uid}" not in html:
                unscoped.append(f"{mid}: atl-{uid} markup/css missing "
                                "from the document")
        checks.append({"name": "atelier_scoped", "ok": not unscoped,
                       "detail": ("; ".join(unscoped) if unscoped else
                                  f"{len(frags)} bespoke section(s) present "
                                  "+ css scoped")})

    # (e) DRO-honor checks — only when THIS render applied a fresh
    # rationale (dro_status 'applied'/'applied_thin'). Shuffle/refresh
    # re-renders skip these: a user shuffling the hero away from
    # 'constructed' is an explicit choice, not a conformance failure.
    if dro and dro_status in ("applied", "applied_thin"):
        decisions = dro.get("decisions") or {}
        # (e1) symmetry-preferred variants honored for DEFAULTED sections.
        pref = _symmetry_pref(decisions.get("layout"))
        if pref is not None and defaulted_modules is not None:
            viol: List[str] = []
            for s in spec:
                mid = s.get("module")
                if mid == "hero" or mid not in defaulted_modules:
                    continue  # hero is ruled by _apply_hero_direction
                want = pref.get(mid)
                if (want and want in site_modules.MODULES[mid]["variants"]
                        and s.get("variant") != want):
                    viol.append(f"{mid}={s.get('variant')}≠{want}")
            checks.append({"name": "dro_symmetry_honored", "ok": not viol,
                           "detail": (f"defaulted sections off-preference: {viol}"
                                      if viol else "symmetry preference honored")})
        # (e2) signature-move body class present when motion not subtle.
        try:
            from site_modules._base import signature_move_class
            expected_sig = signature_move_class(ctx.get("dna") or {}, decisions)
        except Exception:
            expected_sig = ""
        if expected_sig:
            checks.append({"name": "dro_signature_move",
                           "ok": expected_sig in html,
                           "detail": f"expected body class {expected_sig}"})
        # (e2b) Arc 6 — the authored rule-break's body class reached the
        # document (loud or reduced tier; presence is the contract).
        try:
            from site_modules._base import RULE_BREAK_CLASSES
            import brand_dna as _bd
            _rb_cls = RULE_BREAK_CLASSES.get(
                _bd.resolve_rule_break(decisions.get("rule_break")), "")
        except Exception:
            _rb_cls = ""
        if _rb_cls:
            checks.append({"name": "dro_rule_break",
                           "ok": _rb_cls in html,
                           "detail": f"expected body class {_rb_cls}"})
        # (e3) constructed hero present for visual_metaphor concepts.
        direction = ((decisions.get("hero_concept") or {}).get("direction") or "")
        if direction == "visual_metaphor":
            checks.append({"name": "dro_constructed_hero",
                           "ok": "sxm-hero-constructed" in html,
                           "detail": "visual_metaphor direction requires the constructed hero"})

    report = {"passed": all(c["ok"] for c in checks), "checks": checks,
              "generated_at": datetime.now(timezone.utc).isoformat()}
    return report, fixes


def _apply_quality_fixes(spec: List[Dict[str, Any]], ctx: Dict[str, Any],
                         fixes: List[Dict[str, Any]]) -> Optional[List[Dict[str, Any]]]:
    """Apply the gate's fixable spec issues. Returns the healed spec, or
    None when nothing actually changed (so the caller skips the re-render)."""
    changed = False
    new_spec = [{**s, "content": dict(s.get("content") or {})} for s in spec]
    for f in fixes:
        if f.get("fix") == "refill_headline":
            for s in new_spec:
                if (s.get("module") == f.get("module")
                        and not (s.get("content") or {}).get("headline")):
                    default = _heal_headline_default(s["module"], ctx)
                    if default:
                        s["content"]["headline"] = default
                        changed = True
    if any(f.get("fix") == "resanitize" for f in fixes):
        new_spec = sanitize_spec({"sections": new_spec}, ctx)
        changed = True
    return new_spec if changed else None


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


def _apply_dro_design(ctx: Dict[str, Any], dro: Dict[str, Any],
                      business_id: str) -> None:
    """Apply a DRO's design decisions onto ctx IN PLACE — the single
    application block shared by compose_site (fresh rationale) and
    render_and_persist (stored rationale on shuffle/refresh/override
    re-renders, so an inline edit never re-skins the site).

    Order matters and is preserved exactly: ctx["design"] → palette →
    style (practitioner-pinned fonts stay supreme) → the OWNER's color
    direction re-assert LAST (Arc 5: owner beats model)."""
    decisions = dict(dro.get("decisions") or {})
    # Arc 6 — the owner's loud_where (creative brief) rides the decisions
    # dict so page_shell can arbitrate the restraint budget (signature
    # move vs. rule-break) without a new plumbing channel.
    _creative = (((ctx.get("site_prefs") or {}).get("creative"))
                 if isinstance((ctx.get("site_prefs") or {}).get("creative"), dict)
                 else {})
    if _creative.get("loud_where"):
        decisions["_owner_loud_where"] = _creative["loud_where"]
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
    # Arc 5 — the OWNER's color direction is a HARD preference:
    # when it conflicts with the DRO's palette.base, the owner
    # wins (gather_context already grounded the no-DRO paths).
    _own_dir = (((ctx.get("site_prefs") or {}).get("colors") or {})
                .get("direction"))
    if _own_dir:
        _dro_base = (decisions.get("palette") or {}).get("base")
        if _dro_base and _dro_base != _own_dir:
            logger.info(
                f"[composer] owner color direction '{_own_dir}' "
                f"overrides DRO palette base '{_dro_base}' for "
                f"{business_id[:8]} (owner beats model)")
        ctx["dna"] = brand_dna.apply_owner_ground(ctx["dna"], _own_dir)


def _ensure_site_row(business_id: str, ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Ensure a business_sites row exists (slug drives the live URL and
    the canonical/og:url tags). Shared by render_and_persist and the
    directions engine (drafts persist onto site_config). Mutates ctx."""
    site = ctx.get("site")
    if site:
        return site
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
    return site


def render_and_persist(business_id: str, spec: List[Dict[str, Any]],
                       ctx: Optional[Dict[str, Any]] = None,
                       dro_id: Optional[str] = None,
                       dro: Optional[Dict[str, Any]] = None,
                       dro_status: Optional[str] = None,
                       dro_summary: Optional[str] = None,
                       defaulted_modules: Optional[List[str]] = None,
                       full_recompose: bool = False,
                       progress_cb=None,
                       dro_failure: Optional[Dict[str, Any]] = None,
                       _heal_attempted: bool = False,
                       _recon: Optional[Dict[str, Any]] = None,
                       _atelier: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    # Arc 4: `full_recompose` is True ONLY from compose_site (a fresh
    # spec) — it triggers override reconciliation. Shuffle/refresh/
    # override-triggered re-renders keep it False so a practitioner's
    # edits are never staled by a re-render of the SAME composition.
    # `defaulted_modules` feeds the gate's symmetry-honored check;
    # _heal_attempted/_recon are internal recursion state for the single
    # self-heal pass.
    ctx = ctx or gather_context(business_id)
    title = ctx["business"]["name"] or "Welcome"

    # Ensure a business_sites row exists BEFORE rendering — the slug
    # drives the live URL and the page's canonical/og:url tags.
    site = _ensure_site_row(business_id, ctx)

    # No DRO handed in (shuffle/refresh/override-save paths) → load the
    # stored one BEFORE rendering. Fetched once here and reused for both
    # the design re-application below and the slot briefs further down.
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

    # Re-apply the stored design when ctx doesn't already carry one
    # (compose_site applies it pre-call and sets ctx["design"]). Without
    # this, every re-render path dropped the DRO — one inline edit
    # re-skinned the site back to default fonts/palette and lost the
    # signature-move class + constructed-hero seed.
    if dro and not ctx.get("design"):
        _apply_dro_design(ctx, dro, business_id)

    # Arc 8 — THE ATELIER: 2-3 bespoke LLM-written sections where eyes
    # land (always the hero + the DRO's rule-break section), replacing
    # their module renders BEFORE slot population / override resolution /
    # the quality gate — so slots, edits and conformance checks treat
    # bespoke sections exactly like module ones. Full composes generate;
    # shuffle/refresh/override re-renders REUSE the fragments stored on
    # site_config.atelier; the self-heal recursion reuses the first
    # pass's fragments (never pays twice). ATELIER_ENABLED=0 → markers
    # off, no calls: byte-identical to the Arc 7 pipeline.
    _stored_atelier = (((site or {}).get("site_config") or {}).get("atelier")
                       if isinstance(((site or {}).get("site_config") or {})
                                     .get("atelier"), dict) else {})
    atelier_active = False
    atelier_meta: Optional[Dict[str, Any]] = None
    try:
        import atelier as _atelier_mod
        atelier_active = _atelier_mod.atelier_enabled() and bool(
            (full_recompose and dro)
            or (_atelier or {}).get("fragments")
            or (not full_recompose and (_stored_atelier.get("fragments") or {})))
    except Exception as e:
        logger.warning(f"[composer] atelier unavailable (non-fatal): {e}")

    html = _mark(site_modules.render_page(spec, ctx, title,
                                          fragment_markers=atelier_active))
    if atelier_active:
        _report_progress(progress_cb, 55, "Drafting bespoke sections")
        try:
            html, atelier_meta = _atelier_mod.run_atelier(
                html, spec, ctx, dro, business_id,
                regenerate=bool(full_recompose and not _heal_attempted
                                and _atelier is None),
                # A full recompose NEVER reuses the previous compose's
                # stored fragments (stale copy would mask the fresh
                # composition) — only the heal recursion's precomputed
                # set or a fresh generation apply here.
                stored=({} if full_recompose else _stored_atelier),
                precomputed=_atelier,
                progress_cb=progress_cb)
        except Exception as e:
            logger.warning(f"[composer] atelier failed (non-fatal): {e}")
            atelier_meta = None

    # Slot population (existing pipeline) then resolution into the HTML.
    # The enriched_brief threads the DRO's design concept into the
    # Unsplash/DALL-E query composers (params existed, were never passed).
    #
    # Arc 7 — CONCEPT-KEYED IMAGE RE-ROLL: a full recompose whose design
    # concept actually changed (fingerprint of concept_keywords +
    # brand_metaphor vs the stored site_config.slot_concept) re-rolls the
    # platform-default slot imagery. Custom uploads are never touched,
    # placeholder-strategy slots (portraits) stay placeholder, DALL-E
    # budget caps still apply inside the pipeline, and the self-heal
    # recursion never re-rolls twice (slots persisted on the first pass).
    slots_meta: Dict[str, Any] = {}
    slot_brief = _dro_slot_brief(ctx, dro, spec)
    new_concept_fp = _slot_concept_fingerprint(slot_brief)
    stored_concept_fp = str((((site or {}).get("site_config")) or {})
                            .get("slot_concept") or "")
    reroll_defaults = bool(full_recompose and not _heal_attempted
                           and new_concept_fp
                           and new_concept_fp != stored_concept_fp)
    _report_progress(progress_cb, 85, "Choosing photography")
    try:
        from agents.slot_system.builder_post_process import populate_slots_for_site
        slots_meta = populate_slots_for_site(
            html=html, business_id=business_id,
            enriched_brief=slot_brief,
            business=(ctx.get("bundle") or {}).get("business") or {},
            reroll_defaults=reroll_defaults,
        ) or {}
        if full_recompose:
            _pop = slots_meta.get("slots_populated") or []
            _skip = slots_meta.get("slots_skipped") or []
            _rerolled = sum(1 for p in _pop if p.get("rerolled"))
            _kept_custom = sum(1 for s in _skip
                               if s.get("reason") == "kept_custom")
            _kept_same = (0 if reroll_defaults else
                          sum(1 for s in _skip
                              if s.get("reason") == "already_set"))
            logger.info(
                f"[composer.slots] {business_id[:8]} "
                f"concept_changed={reroll_defaults} rerolled={_rerolled} "
                f"kept_custom={_kept_custom} kept_same_concept={_kept_same}")
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

    # Arc 4 — OVERRIDE RECONCILIATION (full recompose only): before the
    # stored text overrides re-stamp themselves onto the FRESH composer
    # copy, diff each one against what the composer just wrote at its
    # target path. Composer wrote NEW text there (≠ the override's
    # original_value) → the override is marked stale and NOT applied
    # (no silent masking). Orphaned paths → stale too, never deleted —
    # the stale list rides GET /composer/spec so a future UI can offer
    # re-apply. Legacy rows without original_value keep applying
    # (provenance unknown; staling them would visibly revert edits).
    overrides_reconciled = _recon
    if full_recompose and overrides_reconciled is None:
        try:
            from agents.override_system.override_resolver import reconcile_text_overrides
            overrides_reconciled = reconcile_text_overrides(business_id, final_html)
            if overrides_reconciled.get("stale"):
                logger.warning(
                    f"[composer] recompose staled {overrides_reconciled['stale']} "
                    f"text override(s) for {business_id[:8]}: "
                    f"{overrides_reconciled.get('stale_paths')}")
        except Exception as e:
            logger.warning(f"[composer] override reconciliation failed (non-fatal): {e}")

    # DETERMINISTIC INLINE EDITS (no API): apply the practitioner's text +
    # color overrides onto the rendered HTML. Edits made in the editor
    # (words, colors) persist as overrides and show on re-render WITHOUT any
    # LLM call — the cost-reduction goal. Image swaps ride the slot system
    # above. A re-render is triggered on every override save (see the
    # override router → refresh_if_composed_async). Stale overrides are
    # skipped inside resolve_html_overrides (Arc 4).
    try:
        from agents.override_system.override_resolver import resolve_html_overrides
        final_html = resolve_html_overrides(final_html, business_id)   # text
    except Exception as e:
        logger.warning(f"[composer] text override resolution failed (non-fatal): {e}")
    final_html = _inject_color_overrides(final_html, business_id)       # color

    # Arc 4 — QUALITY GATE: deterministic conformance report over the
    # final document. ONE self-heal re-render for fixable spec issues,
    # then whatever the second pass yields is persisted. Never blocks
    # publish. Wrapped so a gate bug can never take down a render.
    quality_report: Dict[str, Any] = {"passed": True, "checks": []}
    # Arc 7 — read the PREVIOUS live document before it's overwritten so
    # the gate can say whether this compose visibly changed anything.
    # Full recomposes only; the DB isn't written until the persist block
    # below, so the self-heal recursion still reads the pre-compose page.
    prev_html: Optional[str] = None
    if full_recompose:
        try:
            _prev_rows = sb_clients.sb_get_as_service(
                f"/business_sites?id=eq.{site['id']}"
                "&select=html_content&limit=1") or []
            _prev = ((_prev_rows[0].get("html_content") if _prev_rows else "")
                     or "")
            prev_html = _prev if _prev.strip() else None
        except Exception as e:
            logger.info(f"[composer] previous-html read skipped: {e}")
    _report_progress(progress_cb, 93, "Inspecting quality")
    try:
        quality_report, fixes = _run_quality_gate(
            business_id, spec, ctx, final_html, dro=dro,
            dro_status=dro_status, defaulted_modules=defaulted_modules,
            previous_html=prev_html, atelier_meta=atelier_meta)
        if not quality_report["passed"] and fixes and not _heal_attempted:
            healed = _apply_quality_fixes(spec, ctx, fixes)
            if healed is not None:
                failed = [c["name"] for c in quality_report["checks"] if not c["ok"]]
                logger.warning(f"[composer] quality gate failed ({failed}) for "
                               f"{business_id[:8]} — applying one self-heal re-render")
                return render_and_persist(
                    business_id, healed, ctx, dro_id=dro_id, dro=dro,
                    dro_status=dro_status, dro_summary=dro_summary,
                    defaulted_modules=defaulted_modules,
                    full_recompose=full_recompose,
                    dro_failure=dro_failure,
                    # progress_cb rides the recursion; the chief_jobs
                    # reporter is monotonic, so re-hit stages never walk
                    # the bar backwards.
                    progress_cb=progress_cb,
                    _heal_attempted=True, _recon=overrides_reconciled,
                    _atelier=atelier_meta)
        quality_report["self_healed"] = _heal_attempted
        if not quality_report["passed"]:
            logger.warning(
                f"[composer] quality gate FAILED (publish proceeds) for "
                f"{business_id}: " + "; ".join(
                    f"{c['name']}: {c['detail']}"
                    for c in quality_report["checks"] if not c["ok"]))
    except Exception as e:
        logger.warning(f"[composer] quality gate crashed (non-fatal): {e}")
        quality_report = {"passed": False, "self_healed": _heal_attempted,
                          "checks": [{"name": "gate_error", "ok": False,
                                      "detail": str(e)}]}

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
        "quality_report": quality_report,   # Arc 4 — surfaced on /composer/spec
    })
    if dro_id:
        # powers the "why your site looks this way" view — served by
        # GET /composer/rationale, rendered by DesignRationalePanel.tsx.
        cfg["design_rationale_id"] = dro_id
    # Arc 8 — persist which sections went bespoke + the validated
    # fragments themselves (html/css keyed by module) so shuffle/refresh/
    # override re-renders reuse them without an LLM call. A full
    # recompose that produced no bespoke output (fell back everywhere, or
    # the atelier is disabled) clears the stored set — stale fragments
    # must never mask a fresh composition.
    if atelier_meta and (atelier_meta.get("fragments") or {}):
        cfg["atelier"] = atelier_meta
    elif full_recompose:
        cfg.pop("atelier", None)
    # Arc 7 — persist the imagery-concept fingerprint so the NEXT full
    # recompose can tell whether the concept actually changed (and only
    # then re-roll the default slot imagery). Never clobbered by an
    # empty fingerprint (DRO-fallback composes keep the stored concept).
    if full_recompose and new_concept_fp:
        cfg["slot_concept"] = new_concept_fp
    # Arc 2: surface whether the rationale actually drove THIS compose.
    # Only compose_site sets these (shuffle/refresh re-renders pass None and
    # leave the stored status untouched — they reuse the composed spec).
    # Arc 7: 'applied_thin' = a real rationale ran on a thin brief (<3
    # consumable signals) — it keeps its summary like 'applied'.
    if dro_status:
        cfg["dro_status"] = dro_status
        if dro_status in ("applied", "applied_thin") and dro_summary:
            cfg["dro_summary"] = dro_summary
        else:
            cfg.pop("dro_summary", None)   # never show a stale summary on fallback
        # Failure forensics (never lose the reason again): fallback persists
        # WHY — {stage: signals|authoring|validation|exception|skipped,
        # detail, at} — served by GET /composer/spec; an applied compose
        # clears it (stale blame must never outlive a successful rationale).
        if dro_status in ("applied", "applied_thin"):
            cfg.pop("dro_failure", None)
        else:
            df = dro_failure if isinstance(dro_failure, dict) else {}
            cfg["dro_failure"] = {
                "stage": str(df.get("stage") or "authoring"),
                "detail": str(df.get("detail") or "unknown")[:300],
                "at": datetime.now(timezone.utc).isoformat(),
            }
    sb_clients.sb_patch_as_service(
        f"/business_sites?id=eq.{site['id']}",
        {"html_content": final_html, "site_config": cfg, "status": "published"})

    result = {"site_id": site["id"], "slug": ctx["business"]["slug"],
              "sections": [{"module": s["module"], "variant": s["variant"]} for s in spec],
              "slots": {"found": slots_meta.get("slots_found", []),
                        "populated": len(slots_meta.get("slots_populated") or [])},
              "quality_report": quality_report,
              "url": f"https://{ctx['business']['slug']}.mysolutionist.app" if ctx["business"]["slug"] else None}
    if overrides_reconciled is not None:
        result["overrides_reconciled"] = {
            "applied": overrides_reconciled.get("applied", 0),
            "stale": overrides_reconciled.get("stale", 0)}
    if atelier_meta and (atelier_meta.get("fragments") or {}):
        result["atelier"] = {"sections": sorted(atelier_meta["fragments"])}
    return result


# DRO hero_concept.direction → hero module variant. Cinematic (full-bleed,
# art-directed) for image-led concepts; statement (oversized type, no photo)
# for typographic concepts; constructed (Arc 3) for visual metaphors — a
# generated ornament field built FROM the concept words, no stock photo.
_HERO_DIRECTION_VARIANT = {
    # Site Arc 10: environment_mood → "anchored" (exemplar e5 — the
    # environment IS the subject; bottom-gravity words defer to it under
    # a baseline-deepening scrim). Was "cinematic", which stays the home
    # of the art-directed low-left crop for artifact/portrait concepts.
    "environment_mood": "anchored",
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


def _symmetry_pref(layout: Optional[Dict[str, Any]]) -> Optional[Dict[str, str]]:
    """DRO layout.symmetry (prose-ish) → variant-preference map, or None
    when unrecognized. Shared by _apply_symmetry_preference and the Arc 4
    quality gate so the check verifies exactly what the wiring intended."""
    sym = str((layout or {}).get("symmetry") or "").lower()
    if "asym" in sym or "tension" in sym or "editorial" in sym:
        return _SYMMETRY_ASYM
    if "center" in sym or "formal" in sym or "symmetr" in sym:
        return _SYMMETRY_CENTERED
    if "grid" in sym or "modular" in sym:
        return _SYMMETRY_MODULAR
    return None


def _apply_symmetry_preference(spec: List[Dict[str, Any]],
                               layout: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Wire the DRO's layout.symmetry to the pixels (previously a no-op):
    asymmetric leans → offset/editorial variants, symmetric → centered
    ones. Tolerant matching (DRO values are prose-ish); always strips the
    internal `_variant_defaulted` markers, DRO or not."""
    pref = _symmetry_pref(layout)
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
    sanitize_spec. Sections insert before contact so it stays last.

    Site Arc 11 — the owner's EXPLICIT connections outrank the data
    heuristics: connections.booking=True forces the offerings section
    (the thing a booking CTA sells); connections.store=True forces the
    store section (the module render applies the relaxed 1-real-product
    floor). Hard OFF switches were already applied by gather_context
    (ctx.booking/ctx.store disabled), so the conditions below naturally
    skip forced-off surfaces. Absent connections → identical to before."""
    conn = (ctx.get("connections")
            if isinstance(ctx.get("connections"), dict) else {})
    present = {s.get("module") for s in spec}
    additions: List[Dict[str, Any]] = []
    # Additions are by definition not an explicit LLM pick — mark them so
    # the DRO symmetry preference (Arc 3) may steer their variant; the
    # marker is stripped in _apply_symmetry_preference.
    if ctx.get("public_modules") and "showcase" not in present:
        additions.append({"module": "showcase", "variant": "cards", "content": {},
                          "_variant_defaulted": True})
    if ((ctx.get("offerings") or conn.get("booking") is True)
            and "offerings" not in present):
        additions.append({"module": "offerings", "variant": "cards", "content": {},
                          "_variant_defaulted": True})
    # store: gather_context already disabled ctx.store on an explicit
    # False, so enabled-here means auto or forced-on; forced-on ALSO gets
    # the relaxed 1-real-product floor inside the store module render.
    if (ctx.get("store") or {}).get("enabled") and "store" not in present:
        additions.append({"module": "store", "variant": "featured", "content": {},
                          "_variant_defaulted": True})
    if not additions:
        return spec
    contact_idx = next((i for i, s in enumerate(spec) if s.get("module") == "contact"), len(spec))
    return spec[:contact_idx] + additions + spec[contact_idx:]


# ─── Arc 5 — reference-site study (the marquee feature) ──────────────

_REFERENCE_BUDGET_S = 20.0     # overall wall-clock budget per compose


def _maybe_analyze_references(business_id: str,
                              ctx: Dict[str, Any]) -> Optional[List[Dict[str, Any]]]:
    """Run reference_analyzer over site_prefs.inspiration_urls when the
    stored analysis is missing or the URLs changed; persist the result to
    settings.site_prefs.reference_analysis and mirror it onto ctx so the
    intake text sees it. Overall budget 20s (asyncio.wait_for around a
    worker thread) — on timeout/error the compose proceeds with whatever
    analysis (if any) already existed. Never raises."""
    prefs = ctx.get("site_prefs") if isinstance(ctx.get("site_prefs"), dict) else {}
    urls = [str(u) for u in (prefs.get("inspiration_urls") or [])
            if isinstance(u, str) and u.strip()][:_MAX_INSPIRATION_URLS]
    stored = (prefs.get("reference_analysis")
              if isinstance(prefs.get("reference_analysis"), dict) else {})
    if not urls:
        return None
    if stored.get("urls") == urls and isinstance(stored.get("results"), list):
        return stored["results"]      # fresh enough — same URLs already studied

    results: Optional[List[Dict[str, Any]]] = None
    try:
        import asyncio
        from reference_analyzer import analyze_references

        async def _run() -> List[Dict[str, Any]]:
            return await asyncio.wait_for(
                asyncio.to_thread(analyze_references, urls),
                timeout=_REFERENCE_BUDGET_S)

        results = asyncio.run(_run())
    except Exception as e:
        # TimeoutError, event-loop conflicts, analyzer bugs — all soft.
        logger.warning(f"[composer] reference analysis skipped for "
                       f"{business_id[:8]} (non-fatal): {e}")
        return stored.get("results") if isinstance(stored.get("results"), list) else None

    from datetime import datetime, timezone
    record = {"analyzed_at": datetime.now(timezone.utc).isoformat(),
              "urls": urls, "results": results}
    try:
        rows = sb_clients.sb_get_as_service(
            f"/businesses?id=eq.{business_id}&select=settings&limit=1") or []
        if rows:
            settings = dict(rows[0].get("settings") or {})
            sp = dict(settings.get("site_prefs")
                      if isinstance(settings.get("site_prefs"), dict) else {})
            sp["reference_analysis"] = record
            settings["site_prefs"] = sp
            sb_clients.sb_patch_as_service(
                f"/businesses?id=eq.{business_id}", {"settings": settings})
    except Exception as e:
        logger.warning(f"[composer] reference-analysis persist failed "
                       f"(non-fatal): {e}")
    # Mirror onto ctx so _assemble_intake_text reads the fresh study.
    if isinstance(ctx.get("site_prefs"), dict):
        ctx["site_prefs"]["reference_analysis"] = record
    else:
        ctx["site_prefs"] = {"reference_analysis": record}
    ok_n = sum(1 for r in (results or []) if isinstance(r, dict) and r.get("ok"))
    logger.info(f"[composer] studied {ok_n}/{len(urls)} reference site(s) "
                f"for {business_id[:8]}")
    return results


# Arc 5 — cta_goal → deterministic hero/cta-band label defaults. Applied
# only when the composer left cta_label empty, so an in-concept CTA the
# LLM wrote ("Book Your Throne") always survives.
_CTA_GOAL_LABELS = {"book": "Book a session", "buy": "Shop the store",
                    "contact": "Get in touch", "follow": "Follow along"}


def _apply_cta_goal(spec: List[Dict[str, Any]], ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
    label = _CTA_GOAL_LABELS.get(str(ctx.get("cta_goal") or ""))
    if not label:
        return spec
    for s in spec:
        if s.get("module") in ("hero", "cta"):
            content = s.setdefault("content", {})
            if not str(content.get("cta_label") or "").strip():
                content["cta_label"] = label
    return spec


# ─── Site Arc 10 "wow" — the CEREMONY PASS ────────────────────────────
#
# "The page is a ceremony, not a stack" (exemplars e5/e6): two chapters
# never simply abut — the seam between them carries something deliberate.
# This pass deterministically inserts 1-3 interstitial seams (module
# "interstitial": silence / thread / statement / marquee) between major
# sections, driven by the DRO and seeded by design_rationale_id so a
# recompose varies its seams. NEVER LLM-picked; runs after sanitize/
# symmetry/hero-direction, before render — inside the existing 45-55%
# progress window (no new stage). No DRO or <4 sections → no seams.

_CEREMONY_MIN_SECTIONS = 4
_CEREMONY_MAX = 3
_GENEROUS_WHITESPACE = ("editorial_rhythm", "confidence_air")
_STATEMENT_COPY_SOURCES = (("about", "pull_quote"), ("hero", "subheadline"),
                           ("offerings", "intro"), ("cta", "subheadline"))
# Site Arc 11b: with exactly 3 tone words the marquee's repeat is visibly
# obvious (the live-page thin-loop defect) — 4+ real words or no marquee.
_MARQUEE_MIN_WORDS = 4


def _ceremony_tone_words(ctx: Dict[str, Any]) -> List[str]:
    """The brand's REAL tone/value words from the ctx bundle (voice.
    tone_words — list or free string; the owner's feel_words already
    ride this via gather_context). Never invented; empty when absent."""
    voice = ((ctx.get("bundle") or {}).get("voice")
             if isinstance((ctx.get("bundle") or {}).get("voice"), dict) else {})
    raw = voice.get("tone_words")
    if isinstance(raw, (list, tuple)):
        words = [str(w) for w in raw]
    elif isinstance(raw, str):
        words = re.split(r"[,/|•·]+|\s+", raw)
    else:
        words = []
    out: List[str] = []
    seen = set()
    for w in words:
        w = " ".join(w.split()).strip(".,;:")
        if 2 <= len(w) <= 24 and w.lower() not in seen and w.isascii():
            seen.add(w.lower())
            out.append(w[:1].upper() + w[1:])
    return out[:6]


def _norm_copy_line(v: Any) -> str:
    """Normalize a copy line for verbatim-duplication checks: collapse
    whitespace, lowercase, strip wrapping quotes/terminal punctuation."""
    return " ".join(str(v or "").split()).lower().strip(" .!?……\"'“”‘’")


def _spec_copy_corpus(spec: List[Dict[str, Any]]) -> List[str]:
    """Every normalized copy string the page's SECTIONS carry (all spec
    content fields, interstitials excluded) — the rendered-copy proxy
    the statement dedupe filters against."""
    out: List[str] = []
    for s in spec:
        if s.get("module") == "interstitial":
            continue
        for v in (s.get("content") or {}).values():
            n = _norm_copy_line(v)
            if n:
                out.append(n)
    return out


def _ceremony_statement_line(spec: List[Dict[str, Any]],
                             dro: Optional[Dict[str, Any]] = None,
                             ) -> Tuple[str, bool]:
    """(line, had_candidates) for the statement bar.

    Site Arc 11b (dedupe): the title card must never REPEAT the page —
    the live defect was the about pull-quote rendered twice, once in
    the section and again on the adjacent statement bar. A candidate
    whose normalized text appears verbatim inside (or containing) ANY
    section's copy field is filtered out; when candidates existed but
    none survive, the caller renders a quiet 'thread' seam instead of
    a statement (the pause stays, the words don't repeat).

    Candidate order matters: the DRO's OWN lines come first — the
    concept statement and the first-impression 'remember' line are
    the page's thesis and are normally NOT rendered by any section,
    so they survive the dedupe naturally. Spec copy fields are the
    fallback. (Without this, every spec-sourced candidate is by
    definition already on the page and statements would always fall
    back to threads.)"""
    by_module: Dict[str, Dict[str, Any]] = {}
    for s in spec:
        mid = s.get("module")
        if isinstance(mid, str) and mid not in by_module:
            by_module[mid] = s.get("content") or {}
    corpus = _spec_copy_corpus(spec)
    had_candidates = False

    candidates: List[str] = []
    d = (dro or {}).get("decisions") or {}
    for raw in (
        ((d.get("hero_concept") or {}).get("concept_statement")),
        ((d.get("first_impression") or {}).get("remember")),
        ((d.get("tension") or {}).get("expression")),
    ):
        if isinstance(raw, str) and raw.strip():
            candidates.append(raw)
    for mod, field in _STATEMENT_COPY_SOURCES:
        candidates.append(str((by_module.get(mod) or {}).get(field) or ""))

    for raw in candidates:
        v = " ".join(str(raw).split())
        if not (12 <= len(v) <= 200):
            continue
        had_candidates = True
        n = _norm_copy_line(v)
        if any(n in c or c in n for c in corpus):
            continue  # the page already says this line — never repeat it
        return v, True
    return "", had_candidates


def _apply_ceremony_pass(spec: List[Dict[str, Any]], ctx: Dict[str, Any],
                         dro: Optional[Dict[str, Any]],
                         seed: Optional[str] = None) -> List[Dict[str, Any]]:
    """Insert the ceremony seams. Rules (all deterministic):
      - no DRO or fewer than 4 sections → no seams (a short page has no
        chapters to pause between);
      - whitespace philosophy generous (editorial_rhythm/confidence_air,
        or airy density) → silences earn a second seat; otherwise the
        filler seam is the transition thread;
      - tension authored → ONE statement bar quoting the page's copy —
        but (Site Arc 11b) never a line the sections already render
        verbatim; all candidates duplicated → a thread seam instead;
      - marquee only when the brand has >=4 real tone words AND the page
        isn't stilled (dna motion != subtle) — the one loud accent spend,
        on values rather than services;
      - seats capped at 3 and by the available gaps (never directly
        after the hero, never directly before contact);
      - placement + order seeded by design_rationale_id so recomposes
        vary their seams while any single rationale renders stably."""
    if not dro or len(spec) < _CEREMONY_MIN_SECTIONS:
        return spec
    d = (dro.get("decisions") or {})

    seed_src = str(seed or dro.get("id")
                   or ((d.get("hero_concept") or {}).get("concept_statement"))
                   or (ctx.get("business") or {}).get("id") or "ceremony")
    h = int(hashlib.sha256(seed_src.encode("utf-8")).hexdigest()[:12], 16)

    ws = str((d.get("whitespace") or {}).get("philosophy") or "").lower()
    density = str((d.get("layout") or {}).get("density") or "").lower()
    generous = (ws in _GENEROUS_WHITESPACE or "generous" in ws
                or density == "airy")
    tn = d.get("tension") if isinstance(d.get("tension"), dict) else {}
    tension_present = bool(tn.get("pole_a") and tn.get("pole_b"))
    statement_line, statement_had_candidates = ("", False)
    if tension_present:
        statement_line, statement_had_candidates = _ceremony_statement_line(spec, dro)
    # Site Arc 11b: a warranted statement whose every candidate line
    # already appears in the page's copy falls back to a THREAD seam —
    # never a duplicated title card.
    statement_dup_fallback = (not statement_line) and statement_had_candidates
    tone_words = _ceremony_tone_words(ctx)
    dna_motion = (ctx.get("dna") or {}).get("motion", "standard")
    marquee_ok = (len(tone_words) >= _MARQUEE_MIN_WORDS
                  and dna_motion != "subtle")

    # The wish-list, priority-ordered: the statement bar (the loud
    # moment's title card), the values marquee, then quiet fillers.
    wishes: List[Dict[str, Any]] = []
    if statement_line:
        wishes.append({"module": "interstitial", "variant": "statement",
                       "content": {"text": statement_line}})
    elif statement_dup_fallback:
        # The statement's seat stays, its voice changes: a thread seam
        # (Site Arc 11b dedupe — smoke: dup line → thread fallback).
        wishes.append({"module": "interstitial", "variant": "thread",
                       "content": {}})
    if marquee_ok:
        wishes.append({"module": "interstitial", "variant": "marquee",
                       "content": {"words": " • ".join(tone_words)}})
    filler = "silence" if generous else "thread"
    while len(wishes) < _CEREMONY_MAX:
        wishes.append({"module": "interstitial", "variant": filler,
                       "content": {}})

    n_want = 1 + (1 if generous else 0) + (1 if (statement_line or statement_dup_fallback
                                                 or marquee_ok) else 0)
    n_want = min(n_want, _CEREMONY_MAX)

    # Gaps: after spec[i] for i in 1..len-3 — a seam never lands directly
    # after the hero or directly before the contact exit. Chosen gaps are
    # DISTINCT spec indices, so two seams are always separated by at
    # least one section — interstitials can never abut each other.
    gaps = list(range(1, len(spec) - 2))
    if not gaps:
        return spec
    n = min(n_want, len(gaps))
    start = h % len(gaps)
    rotated = gaps[start:] + gaps[:start]
    chosen = sorted(rotated[:n])
    # A seeded rotation of the wish order varies WHICH seam lands where
    # across recomposes (statement/marquee still always make the cut).
    picks = wishes[:n]
    if len(picks) > 1:
        r = (h >> 12) % len(picks)
        picks = picks[r:] + picks[:r]

    out = list(spec)
    for pos, seam in sorted(zip(chosen, picks), reverse=True):
        out.insert(pos + 1, seam)
    logger.info(f"[composer.ceremony] inserted {n} seam(s) "
                f"({[p['variant'] for p in picks]}) for "
                f"{str((ctx.get('business') or {}).get('id') or '')[:8]} "
                f"(seed {seed_src[:24]!r})")
    return out


def compose_site(business_id: str, brief_notes: str = "",
                 use_llm: bool = True,
                 design_prefs: Optional[Dict[str, Any]] = None,
                 progress_cb=None) -> Dict[str, Any]:
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

    # Arc 10 — progress_cb (chief_jobs loading bar) pings at real stage
    # boundaries with honest labels; None on every non-job path.
    _report_progress(progress_cb, 5, "Reading your business")
    ctx = gather_context(business_id)
    dro: Optional[Dict[str, Any]] = None
    dro_id: Optional[str] = None
    source = "llm"
    dro_fail_reason: Optional[str] = None

    # Arc 5 — ACTUALLY STUDY the reference sites the owner named (cached
    # by URL set; ≤20s budget; fail-soft). Runs before intake assembly so
    # both the DRL signal pass and the DRO author see the evidence.
    _report_progress(progress_cb, 15, "Listening to your style words")
    ref_analysis = _maybe_analyze_references(business_id, ctx)

    # Arc 6 — the owner's creative brief flows into DRO authoring on the
    # SINGLE compose path too (directions are opt-in, not a prerequisite).
    creative = ((ctx.get("site_prefs") or {}).get("creative")
                if isinstance((ctx.get("site_prefs") or {}).get("creative"), dict)
                else None)

    dro_failure: Optional[Dict[str, Any]] = None   # forensics → site_config.dro_failure
    if use_llm:
        # 1) Author the rationale from the practitioner's own words.
        _report_progress(progress_cb, 30, "Authoring the design brief")
        try:
            from agents.composer.drl.passes import produce_dro
            intake = _assemble_intake_text(ctx)
            dro, dro_failure = produce_dro(
                business_id, intake, reference_analysis=ref_analysis,
                creative=creative)
            if dro is None:
                # One retry — cheap insurance against a transient LLM/parse
                # hiccup before accepting a rationale-less compose.
                logger.info(f"[composer] DRO production returned None for "
                            f"{business_id[:8]} — retrying once")
                dro, dro_failure = produce_dro(
                    business_id, intake, reference_analysis=ref_analysis,
                    creative=creative)
            if dro:
                dro_id = dro.get("id")
                dro_failure = None
            else:
                dro_fail_reason = ((dro_failure or {}).get("detail")
                                   or "produce_dro returned None after retry")
        except Exception as e:
            dro_fail_reason = f"DRO production raised: {e}"
            dro_failure = {"stage": "exception",
                           "detail": str(dro_fail_reason)[:300]}
            logger.warning(f"[composer] DRO production failed (non-fatal): {e}")
        # 1b) DRO-driven DESIGN: the palette base (dark stage / light room) +
        # accent scarcity flow into the render via ctx; copy obeys it next.
        if dro:
            _apply_dro_design(ctx, dro, business_id)
        # 2) Compose copy that obeys the rationale.
        _report_progress(progress_cb, 45, "Writing your copy")
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
        # 'skipped' (not one of the failure stages): a deliberate
        # deterministic compose, not a DRL breakage.
        dro_failure = {"stage": "skipped", "detail": dro_fail_reason}

    # Arc 2: surface the DRO outcome — no more silent skips. "applied" means
    # this compose's design + copy were driven by a fresh rationale;
    # "fallback" means it composed without one (reason logged below).
    # Arc 7: "applied_thin" = the rationale succeeded but ran on a thin
    # brief (fewer than THIN_BRIEF_MIN_SIGNALS consumable signals actually
    # fed author_dro) — honest status instead of a confident 'applied'.
    # Downstream that treats != 'fallback' as applied keeps working; the
    # frontend renders the new value separately.
    dro_status = "applied" if dro else "fallback"
    if dro:
        try:
            from agents.composer.drl.passes import THIN_BRIEF_MIN_SIGNALS
            _n_consumable = dro.get("consumable_signal_count")
            if (isinstance(_n_consumable, int)
                    and _n_consumable < THIN_BRIEF_MIN_SIGNALS):
                dro_status = "applied_thin"
                logger.info(
                    f"[composer] thin-brief compose for {business_id[:8]}: "
                    f"only {_n_consumable} consumable signal(s) drove the "
                    f"rationale (threshold {THIN_BRIEF_MIN_SIGNALS})")
            # Resilience ladder: a minimal-mode DRO is honest 'applied_thin'
            # REGARDLESS of signal count — a bland-but-valid rationale ran,
            # not the full creative engine.
            if (dro.get("meta") or {}).get("authored_minimal"):
                dro_status = "applied_thin"
                logger.info(
                    f"[composer] minimal-mode rationale for {business_id[:8]} "
                    "— reporting applied_thin")
        except Exception as e:
            logger.info(f"[composer] thin-brief status check skipped: {e}")
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

    # Arc 5 — cta_goal fills hero/cta labels the composer left empty
    # (explicit in-concept labels always survive; hrefs are steered
    # deterministically inside site_modules.cta_button via ctx.cta_goal).
    spec = _apply_cta_goal(spec, ctx)

    # Arc 3 — wire the DRO's layout.symmetry to variant selection where the
    # LLM didn't explicitly pick (also strips the internal markers), then let
    # the hero-concept direction have the final word on the hero (constructed
    # for visual_metaphor, cinematic for image-led, statement for typographic).
    # Arc 4: the defaulted set is captured FIRST (the markers are stripped
    # inside _apply_symmetry_preference) so the quality gate can verify the
    # symmetry preference was honored on exactly those sections.
    defaulted_modules = [s["module"] for s in spec if s.get("_variant_defaulted")]
    decisions = (dro or {}).get("decisions") or {}
    spec = _apply_symmetry_preference(spec, decisions.get("layout"))
    if dro:
        _apply_hero_direction(spec, decisions.get("hero_concept"))

    # Site Arc 10 — the ceremony pass: deterministic interstitial seams
    # between the chapters (after sanitize/symmetry, before render;
    # inside the existing 45-55% progress window — no new stage).
    spec = _apply_ceremony_pass(spec, ctx, dro, seed=dro_id)

    result = render_and_persist(business_id, spec, ctx, dro_id=dro_id, dro=dro,
                                dro_status=dro_status, dro_summary=dro_summary,
                                defaulted_modules=defaulted_modules,
                                full_recompose=True, progress_cb=progress_cb,
                                dro_failure=dro_failure)
    _report_progress(progress_cb, 100, "Done")
    return {"composition_source": source, "design_rationale_id": dro_id,
            "dro_status": dro_status, "dro_summary": dro_summary, **result}


# ─── Arc 6 "Creative Engine" — the directions engine ─────────────────
#
# Taste is CHOSEN, not described: one directions run authors THREE
# candidate DROs with distinct creative stances, composes copy for each,
# renders each deterministically (no slot population — previews use
# placeholder-safe imagery), and stores the drafts on
# site_config.direction_drafts. The owner previews all three and CHOOSES;
# choose runs the full normal publish path (slots, override reconcile,
# quality gate, rationale persistence). Directions run as a
# 'compose_directions' chief_jobs job (6-7 LLM calls ≈ 60-120s — too
# long for a sync request).

DIRECTION_STANCES: Dict[str, str] = {
    "concept-literal": (
        "CONCEPT-LITERAL — design the metaphor as literally as craft "
        "allows. The organizing idea must be VISIBLE in the decisions "
        "(hero direction, metaphor elements, palette temperature), not "
        "just described in copy. If the owner gave a metaphor, build the "
        "site AS that place/material/song. Spend the rule-break where the "
        "metaphor lands hardest."),
    "tension-led": (
        "TENSION-LED — let the two poles fight visibly. decisions.tension "
        "is MANDATORY for this candidate: pick decisions that hold both "
        "poles at once (one pole carries structure/typography, the other "
        "carries energy/accent), and place the ONE rule-break exactly at "
        "their collision point."),
    "quiet-editorial": (
        "QUIET-EDITORIAL — maximum restraint; whitespace is the luxury. "
        "Airy density, quiet scale contrast, motion none or subtle. "
        "Exactly ONE perfect loud moment (the rule-break) — it is the "
        "only raised voice on the page; everything else whispers."),
}

_PREVIEW_TOKEN_TTL_S = 30 * 60      # 30 minutes


def _preview_secret() -> bytes:
    """HMAC key for direction-preview tokens, derived from an existing
    server secret (same idiom family as customer_token/meta_oauth —
    stateless signed+expiring tokens). CUSTOMER_TOKEN_SECRET when set,
    else the Supabase service key; domain-separated by prefix so this
    key can never be replayed against those surfaces."""
    base = (os.environ.get("CUSTOMER_TOKEN_SECRET", "").strip()
            or os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip())
    if not base:
        raise HTTPException(500, "no server secret available for preview tokens")
    return hashlib.sha256(f"composer-direction-preview:{base}".encode()).digest()


def mint_preview_token(business_id: str, draft_id: str,
                       ttl_s: int = _PREVIEW_TOKEN_TTL_S) -> str:
    """`<exp>.<hexsig>` — HMAC-SHA256 over business_id + draft_id + expiry.
    business_id/draft_id ride the preview URL path, so the token only
    carries the expiry + signature (an iframe can't send auth headers)."""
    exp = int(time.time()) + int(ttl_s)
    sig = hmac.new(_preview_secret(),
                   f"{business_id}.{draft_id}.{exp}".encode(),
                   hashlib.sha256).hexdigest()
    return f"{exp}.{sig}"


def verify_preview_token(business_id: str, draft_id: str, token: str) -> bool:
    try:
        exp_s, sig = str(token or "").split(".", 1)
        exp = int(exp_s)
    except (ValueError, AttributeError):
        return False
    if exp < time.time():
        return False
    expected = hmac.new(_preview_secret(),
                        f"{business_id}.{draft_id}.{exp}".encode(),
                        hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, sig)


_LABEL_STOP = _CONCEPT_STOP | {"business", "brand", "site", "place",
                               "space", "room", "feel", "feeling"}
_STANCE_FALLBACK_LABELS = {"concept-literal": "The Concept",
                           "tension-led": "The Tension",
                           "quiet-editorial": "The Quiet One"}


def _direction_label(dro: Dict[str, Any], taken: List[str],
                     stance_key: str) -> str:
    """Deterministic human title from the DRO's concept words — 'The
    Coronation' from a coronation concept. Metaphor elements first (already
    distilled), then significant concept-statement words; stance fallback
    when nothing usable remains. Never repeats a sibling's label."""
    hero_c = ((dro.get("decisions") or {}).get("hero_concept") or {})
    words: List[str] = [str(w) for w in (hero_c.get("metaphor_elements") or [])
                        if str(w or "").strip()]
    words += re.findall(r"[A-Za-z]+", str(hero_c.get("concept_statement") or ""))
    used = {t.lower() for t in taken}
    for w in words:
        lw = w.strip().lower()
        if len(lw) > 3 and lw not in _LABEL_STOP:
            label = "The " + lw.title()
            if label.lower() not in used:
                return label
    fallback = _STANCE_FALLBACK_LABELS.get(stance_key, "The Direction")
    return fallback if fallback.lower() not in used else fallback + " II"


# Preview-only <head> style: empty data-slot images get a soft brand-
# toned gradient placeholder (previews render with NO slot population —
# they must still look intentional).
_PREVIEW_PLACEHOLDER_CSS = (
    "<style>/* directions preview — placeholder-safe slot imagery */\n"
    'img[data-slot][src=""], img[data-slot]:not([src]), img[data-slot][src="#"] {'
    " min-height: 260px; color: transparent; font-size: 0;"
    " background: linear-gradient(135deg, var(--sx-surface-2) 0%,"
    " var(--sx-accent-soft) 78%, var(--sx-surface) 100%); }\n"
    "</style>")


def _preview_html(html: str) -> str:
    return (html.replace("</head>", _PREVIEW_PLACEHOLDER_CSS + "\n</head>", 1)
            if "</head>" in html else html + _PREVIEW_PLACEHOLDER_CSS)


def _load_direction_drafts(business_id: str) -> tuple:
    """(site_row, drafts_dict) — drafts_dict is {} when none stored."""
    rows = sb_clients.sb_get_as_service(
        f"/business_sites?business_id=eq.{business_id}"
        "&select=id,slug,site_config&limit=1") or []
    site = rows[0] if rows else None
    cfg = ((site or {}).get("site_config") or {})
    drafts = cfg.get("direction_drafts")
    return site, (drafts if isinstance(drafts, dict) else {})


def _store_direction_drafts(business_id: str, ctx: Dict[str, Any],
                            items: List[Dict[str, Any]]) -> None:
    """Overwrite site_config.direction_drafts WHOLESALE (that is the cap —
    one drafts set per business; a new run replaces the old)."""
    from datetime import datetime, timezone
    site = _ensure_site_row(business_id, ctx)
    fresh = sb_clients.sb_get_as_service(
        f"/business_sites?id=eq.{site['id']}&select=site_config&limit=1") or []
    cfg = dict((fresh[0].get("site_config") or {}) if fresh else {})
    cfg["direction_drafts"] = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "items": items,
    }
    sb_clients.sb_patch_as_service(
        f"/business_sites?id=eq.{site['id']}", {"site_config": cfg})


def _direction_pipeline(business_id: str, ctx: Dict[str, Any],
                        dro: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The spec half of the normal compose pipeline for ONE direction:
    copy pass (fallback to the deterministic default spec), connection
    guarantees, cta_goal fill, symmetry steering, hero direction."""
    try:
        spec = compose_spec_llm(ctx, "", dro=dro)
    except Exception as e:
        logger.warning(f"[composer.directions] copy pass failed for "
                       f"{business_id[:8]} — using default spec: {e}")
        spec = _default_spec(ctx)
        for s in spec:
            s["_variant_defaulted"] = True
    spec = _ensure_connections(spec, ctx)
    spec = _apply_cta_goal(spec, ctx)
    decisions = dro.get("decisions") or {}
    spec = _apply_symmetry_preference(spec, decisions.get("layout"))
    _apply_hero_direction(spec, decisions.get("hero_concept"))
    # Site Arc 10 — candidate DROs have no persisted id yet; the ceremony
    # seeds off the concept statement instead (stable per draft, distinct
    # across the three stances). Draft specs carry their seams through
    # choose_direction (sanitize_spec keeps interstitials).
    spec = _apply_ceremony_pass(spec, ctx, dro)
    return spec


def compose_directions(business_id: str,
                       design_prefs: Optional[Dict[str, Any]] = None,
                       progress_cb=None) -> Dict[str, Any]:
    """Author THREE candidate directions (distinct stances), compose copy
    for each, deterministically render each as a smoke check, and store
    the drafts. Runs SEQUENTIALLY with a per-direction try — one failed
    direction returns the ones that worked; fewer than 2 → 502.

    Distinctiveness: each candidate is authored with the ACCEPTED sibling
    candidates prepended to the recent-DRO cohort, so author_dro's
    existing _collides check enforces separation across the three drafts
    as well as against history. Candidate DROs are NOT persisted to
    design_rationales here — the chosen one is persisted at choose time."""
    prefs = sanitize_design_prefs(design_prefs)
    if prefs:
        _persist_site_prefs(business_id, prefs)

    # Arc 10 — progress pings for the directions loading bar (per-candidate
    # steps below); None everywhere but the chief_jobs runner.
    _report_progress(progress_cb, 5, "Reading your business")
    ctx = gather_context(business_id)
    ref_analysis = _maybe_analyze_references(business_id, ctx)
    intake = _assemble_intake_text(ctx)
    creative = ((ctx.get("site_prefs") or {}).get("creative")
                if isinstance((ctx.get("site_prefs") or {}).get("creative"), dict)
                else None)

    from agents.composer.drl import passes as drl_passes
    # ONE signal pass shared by all three candidates (same intake).
    _report_progress(progress_cb, 15, "Listening to your style words")
    signals = drl_passes.detect_signals(business_id, intake)
    recent = drl_passes.fetch_recent_dros(business_id)

    import copy as _copy
    items: List[Dict[str, Any]] = []
    errors: List[str] = []
    _n_stances = max(len(DIRECTION_STANCES), 1)
    for _idx, (stance_key, stance_text) in enumerate(DIRECTION_STANCES.items()):
        # 20 → 70 stepped across the candidates (20/45/70 for three).
        _report_progress(progress_cb,
                         20 + int(50 * _idx / max(_n_stances - 1, 1)),
                         f"Designing direction {_idx + 1} of {_n_stances}")
        try:
            sibling_dros = [it["dro"] for it in items]
            dro = drl_passes.author_dro(
                business_id, signals, sibling_dros + recent,
                reference_analysis=ref_analysis,
                creative=creative, stance=stance_text)
            if not dro:
                errors.append(f"{stance_key}: DRO authoring failed")
                continue
            dctx = _copy.deepcopy(ctx)
            _apply_dro_design(dctx, dro, business_id)
            spec = _direction_pipeline(business_id, dctx, dro)
            # Deterministic render smoke — previews re-render from the
            # stored dro+spec, so prove it renders NOW.
            html = site_modules.render_page(
                spec, dctx, dctx["business"]["name"] or "Preview")
            if "<body" not in (html or ""):
                raise ValueError("render produced no document")
            label = _direction_label(dro, [it["label"] for it in items],
                                     stance_key)
            hero_sec = next((s for s in spec if s.get("module") == "hero"), {})
            tagline = str((hero_sec.get("content") or {}).get("headline") or "")
            concept = str((((dro.get("decisions") or {}).get("hero_concept")
                            or {}).get("concept_statement")) or "")
            summary = concept or str(dro.get("summary_for_practitioner") or "")
            items.append({
                "draft_id": uuid4().hex[:12],
                "stance": stance_key,
                "label": label,
                "dro": dro,
                "spec": spec,
                "dro_summary": summary[:400],
                "tagline": tagline,
            })
            logger.info(f"[composer.directions] '{stance_key}' authored for "
                        f"{business_id[:8]}: {label}")
        except Exception as e:
            errors.append(f"{stance_key}: {e}")
            logger.warning(f"[composer.directions] '{stance_key}' failed for "
                           f"{business_id[:8]} (continuing): {e}")

    if len(items) < 2:
        raise HTTPException(502, "could not author enough directions "
                                 f"({len(items)}/3 succeeded): "
                                 + ("; ".join(errors) or "unknown"))

    _report_progress(progress_cb, 95, "Saving your directions")
    _store_direction_drafts(business_id, ctx, items)
    _report_progress(progress_cb, 100, "Done")
    return {"ok": True, "count": len(items),
            "directions": [{k: it[k] for k in
                            ("draft_id", "stance", "label", "dro_summary",
                             "tagline")} for it in items],
            "errors": errors}


# ─── Endpoints ────────────────────────────────────────────────────────

def _require_owner(business_id: str, user_id: str) -> None:
    """Owner gate shared by every composer endpoint (the exact check
    /composer/rationale shipped with): 404 for an unknown business,
    403 when the verified caller isn't its owner. Session-only auth is
    NOT enough here — these endpoints do service-role writes."""
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{business_id}&select=owner_id&limit=1") or []
    if not rows:
        raise HTTPException(status_code=404, detail="business not found")
    if str(rows[0].get("owner_id")) != str(user_id):
        raise HTTPException(status_code=403, detail="not authorized for this business")


class ComposeBody(BaseModel):
    business_id: str
    brief_notes: Optional[str] = None
    use_llm: bool = True
    design_prefs: Optional[Dict[str, Any]] = None   # Arc 2 "Ask the Owner"


@router.post("/compose")
def compose(body: ComposeBody,
            session: UserSession = Depends(sb_clients.authed_request)) -> Dict[str, Any]:
    _require_owner(body.business_id, session.user.id)
    result = compose_site(body.business_id, body.brief_notes or "", body.use_llm,
                          design_prefs=body.design_prefs)
    return {"ok": True, **result}


@router.get("/rationale/{business_id}")
def get_rationale(business_id: str,
                  user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """Arc 2 (feeds Arc 4's panel) — 'why your site looks this way'.
    Owner-gated read of the stored rationale behind the composed page.
    Returns nulls (not 404) when no compose/rationale exists yet."""
    _require_owner(business_id, user.id)

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
            "dro_failure": cfg.get("dro_failure"),
            "rationale": rationale}


@router.get("/prefill-signals/{business_id}")
def prefill_signals(business_id: str,
                    user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """Arc 5 — intake awareness for the adaptive design interview: what the
    platform ALREADY knows, so the frontend skips questions the strategy
    track / brand intake answered (Kevin's rule: never re-ask). Cheap —
    one get_bundle read, zero LLM."""
    _require_owner(business_id, user.id)

    import brand_engine
    bundle = brand_engine.get_bundle(business_id) or {}
    intel = bundle.get("practitioner_intelligence") or {}
    voice = bundle.get("voice") if isinstance(bundle.get("voice"), dict) else {}
    design = bundle.get("design") if isinstance(bundle.get("design"), dict) else {}

    # Non-trivial about text (>80 chars) — the interview can skip "tell
    # us about your business".
    has_about = len(str(intel.get("about_business") or "").strip()) > 80

    # >=2 colors that differ from the platform defaults = a real brand
    # kit choice (bundle design merges DEFAULT_DESIGN for missing slots).
    defaults = getattr(brand_engine, "DEFAULT_DESIGN", {}) or {}
    custom_colors = 0
    for key in ("primary_color", "secondary_color", "accent_color",
                "background_color", "text_color"):
        v = str(design.get(key) or "").strip().lower()
        if v and v != str(defaults.get(key) or "").strip().lower():
            custom_colors += 1
    has_brand_colors = custom_colors >= 2

    # Tone words: brand-kit tone_words ride the design section; the voice
    # section's tones list is the fallback.
    tone_words = design.get("tone_words")
    if not (isinstance(tone_words, list) and tone_words):
        tone_words = voice.get("tones") if isinstance(voice.get("tones"), list) else []
    known_feel_words = [str(w).strip() for w in (tone_words or [])
                        if str(w or "").strip()][:6]

    strategy = intel.get("strategy_track") if isinstance(intel.get("strategy_track"), dict) else {}
    audience_known = bool(str(voice.get("audience") or "").strip()
                          or str((strategy or {}).get("target_audience") or "").strip())

    # Arc 10 "offer clarity" (Kevin's rule: what is being offered must be
    # clear — if it isn't, Chief asks in the interview). Same source
    # gather_context composes from: active offerings rows. Clear = at
    # least one offering with a name AND a price AND a real description
    # (>= 40 chars).
    offerings = sb_clients.sb_get_as_service(
        f"/offerings?business_id=eq.{business_id}&is_active=eq.true"
        "&select=id,name,price,description&limit=50") or []
    offerings = [o for o in offerings if isinstance(o, dict)]
    offer_clear = any(
        str(o.get("name") or "").strip()
        and o.get("price") is not None and str(o.get("price")).strip() != ""
        and len(str(o.get("description") or "").strip()) >= 40
        for o in offerings)

    # Site Arc 11 — DETECTED connections: what the business ACTUALLY has
    # wired today, so the interview can pre-check the connections toggles
    # instead of asking cold (never re-ask what the platform knows).
    settings_rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{business_id}&select=settings&limit=1") or []
    b_settings = (settings_rows[0].get("settings") or {}) if settings_rows else {}
    booking_cfg = (b_settings.get("booking")
                   if isinstance(b_settings.get("booking"), dict) else {})
    hours_cfg = (booking_cfg.get("hours")
                 if isinstance(booking_cfg.get("hours"), dict) else {})
    booking_configured = bool(booking_cfg.get("enabled")
                              or (hours_cfg.get("start") and hours_cfg.get("end")))
    try:
        from store_router import _sellable_offerings
        store_has_products = len(_sellable_offerings(business_id) or []) > 0
    except Exception:
        store_has_products = False
    link_page = (b_settings.get("link_page")
                 if isinstance(b_settings.get("link_page"), dict) else {})
    socials_connected = any(
        str(v or "").strip()
        for v in (link_page.get("social_profiles") or {}).values())

    return {"has_about": has_about,
            "has_brand_colors": has_brand_colors,
            "has_voice": bool(known_feel_words),
            "known_feel_words": known_feel_words,
            "audience_known": audience_known,
            "offer_clear": offer_clear,
            "offer_count": len(offerings),
            "detected": {"booking_configured": booking_configured,
                         "store_has_products": store_has_products,
                         "sms_capable": _platform_sms_capable(),
                         "socials_connected": socials_connected}}


class ShuffleBody(BaseModel):
    business_id: str
    section_index: int


@router.post("/shuffle")
def shuffle(body: ShuffleBody,
            session: UserSession = Depends(sb_clients.authed_request)) -> Dict[str, Any]:
    """Cycle one section to its next expression variant and re-render.
    Deterministic + instant — no LLM call."""
    _require_owner(body.business_id, session.user.id)
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
             session: UserSession = Depends(sb_clients.authed_request)) -> Dict[str, Any]:
    _require_owner(business_id, session.user.id)
    ctx = gather_context(business_id)
    cfg = ((ctx.get("site") or {}).get("site_config") or {})
    # Arc 4 — stale text overrides (reconciliation marked them; never
    # deleted) ride along so the editor can offer re-apply later.
    stale_overrides: List[Dict[str, Any]] = []
    try:
        from agents.override_system.override_storage import list_overrides
        stale_overrides = [
            {"id": r.get("id"), "target_path": r.get("target_path"),
             "override_value": r.get("override_value"),
             "original_value": r.get("original_value")}
            for r in list_overrides(business_id, "text")
            if (r.get("status") or "active") == "stale"]
    except Exception as e:
        logger.info(f"[composer] stale-override lookup skipped: {e}")
    return {"ok": True,
            "has_composition": bool(cfg.get("page_spec")),
            "page_spec": cfg.get("page_spec"),
            "html_source": cfg.get("html_source"),
            # Arc 4 trust surfaces: rationale status + conformance report.
            "dro_status": cfg.get("dro_status"),
            "dro_summary": cfg.get("dro_summary"),
            # Failure forensics — {stage, detail, at} for the last fallback
            # compose; absent/None once a rationale applies again.
            "dro_failure": cfg.get("dro_failure"),
            "quality_report": cfg.get("quality_report"),
            "stale_overrides": stale_overrides,
            "dna": {k: ctx["dna"][k] for k in ("vibe", "intensity", "accent_style", "palette")},
            "modules": {mid: {"variants": list(s["variants"]), "fields": list(s["fields"])}
                        for mid, s in site_modules.MODULES.items()}}


class DroSelftestBody(BaseModel):
    business_id: str


@router.post("/dro-selftest")
def dro_selftest(body: DroSelftestBody,
                 session: UserSession = Depends(sb_clients.authed_request)
                 ) -> Dict[str, Any]:
    """DRO resilience — owner-only production diagnostic. Runs the two
    live DRL passes (detect_signals + author_dro) against the business's
    REAL intake, with NO compose and NO persistence (author_dro never
    writes; persist happens only inside produce_dro, which this endpoint
    deliberately does not call). One authenticated call answers 'why is
    my compose running dro_status=fallback?' with the stage, the specific
    reason, and per-stage timings. Costs ~2 Sonnet calls."""
    _require_owner(body.business_id, session.user.id)
    from agents.composer.drl import passes as drl_passes
    from agents.composer.drl import signals as drl_signals

    t_start = time.monotonic()
    ctx = gather_context(body.business_id)
    intake = _assemble_intake_text(ctx)
    creative = ((ctx.get("site_prefs") or {}).get("creative")
                if isinstance((ctx.get("site_prefs") or {}).get("creative"), dict)
                else None)

    sig_fail: Dict[str, str] = {}
    t0 = time.monotonic()
    signals = drl_passes.detect_signals(body.business_id, intake,
                                        failure_out=sig_fail)
    t1 = time.monotonic()
    consumable = sum(
        1 for s in signals
        if isinstance(s.get("confidence"), (int, float))
        and drl_signals.is_consumable(s["confidence"]))

    recent = drl_passes.fetch_recent_dros(body.business_id)
    auth_fail: Dict[str, str] = {}
    t2 = time.monotonic()
    dro = drl_passes.author_dro(body.business_id, signals, recent,
                                creative=creative, failure_out=auth_fail)
    t3 = time.monotonic()

    # failure_reason: the decisive one when the DRO failed outright;
    # otherwise whatever degraded along the way (signals starved / full
    # authoring mode failed but minimal mode rescued it) — or None.
    failure_reason: Optional[Dict[str, str]] = None
    if dro is None:
        failure_reason = {"stage": auth_fail.get("stage") or "authoring",
                          "detail": auth_fail.get("detail") or "author_dro returned None"}
        if sig_fail.get("detail"):
            failure_reason["detail"] = (f"signals: {sig_fail['detail']} | "
                                        f"{failure_reason['detail']}")[:300]
    elif auth_fail or sig_fail:
        degraded = auth_fail or sig_fail
        failure_reason = {"stage": degraded.get("stage") or "signals",
                          "detail": ("degraded (DRO still produced): "
                                     + str(degraded.get("detail") or ""))[:300]}

    return {
        "ok": True,
        "business_id": body.business_id,
        "intake_chars": len(intake),
        "signals_count": len(signals),
        "consumable": consumable,
        "dro_ok": dro is not None,
        "authored_minimal": bool(((dro or {}).get("meta") or {})
                                 .get("authored_minimal")),
        "failure_reason": failure_reason,
        "elapsed_ms": {
            "context": int((t0 - t_start) * 1000),
            "signals": int((t1 - t0) * 1000),
            "author": int((t3 - t2) * 1000),
            "total": int((t3 - t_start) * 1000),
        },
    }


# ─── Arc 6 — directions endpoints ─────────────────────────────────────

class DirectionsBody(BaseModel):
    business_id: str
    design_prefs: Optional[Dict[str, Any]] = None   # v3 (incl. creative)


@router.post("/directions")
async def start_directions(body: DirectionsBody,
                           session: UserSession = Depends(sb_clients.authed_request)) -> Dict[str, Any]:
    """Enqueue a 'compose_directions' job (6-7 LLM calls ≈ 60-120s — never
    sync). Returns {ok, job_id}; the frontend polls /agents/chief/jobs as
    usual, then GETs /composer/directions/{business_id} for the drafts +
    preview tokens. Reuses the chief_jobs enqueue/dedupe/stale-sweep rail."""
    import asyncio
    import httpx
    import chief_jobs
    uid = session.user.id
    await asyncio.to_thread(_require_owner, body.business_id, uid)
    params: Dict[str, Any] = {}
    prefs = sanitize_design_prefs(body.design_prefs)
    if prefs:
        params["design_prefs"] = prefs
    async with httpx.AsyncClient() as client:
        job = await chief_jobs.enqueue(client, user_id=uid,
                                       business_id=body.business_id,
                                       kind="compose_directions",
                                       params=params, source="desktop")
    if not job:
        raise HTTPException(500, "could not enqueue directions job")
    out = {"ok": True, "job_id": job.get("id")}
    if job.get("deduped"):
        out["deduped"] = True
    return out


@router.get("/directions/{business_id}")
def list_directions(business_id: str,
                    user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """Stored direction drafts + short-lived preview tokens (30 min HMAC —
    minted fresh on every list, so re-opening the picker re-arms expired
    iframes). Lightweight: no LLM, no render."""
    _require_owner(business_id, user.id)
    _site, drafts = _load_direction_drafts(business_id)
    items = drafts.get("items") or []
    directions = []
    for it in items:
        if not isinstance(it, dict) or not it.get("draft_id"):
            continue
        did = str(it["draft_id"])
        token = mint_preview_token(business_id, did)
        directions.append({
            "draft_id": did,
            "stance": it.get("stance"),
            "label": it.get("label"),
            "dro_summary": it.get("dro_summary"),
            "tagline": it.get("tagline"),
            "preview_token": token,
            "preview_url": (f"{RAILWAY_BASE}/composer/directions/"
                            f"{business_id}/{did}/preview?t={token}"),
        })
    return {"ok": True, "created_at": drafts.get("created_at"),
            "directions": directions}


@router.get("/directions/{business_id}/{draft_id}/preview")
def preview_direction(business_id: str, draft_id: str, t: str = ""):
    """text/html deterministic re-render of one stored draft (dro+spec →
    render_page; NO LLM, NO slot population — placeholder gradients keep
    previews intentional). Auth = the signed ?t= token (an iframe cannot
    send Authorization headers); minted owner-side by GET /directions."""
    from fastapi.responses import HTMLResponse
    if not verify_preview_token(business_id, draft_id, t):
        raise HTTPException(401, "invalid or expired preview token")
    _site, drafts = _load_direction_drafts(business_id)
    draft = next((it for it in (drafts.get("items") or [])
                  if isinstance(it, dict) and it.get("draft_id") == draft_id),
                 None)
    if not draft:
        raise HTTPException(404, "draft not found (a newer directions run "
                                 "may have replaced it)")
    ctx = gather_context(business_id)
    dro = draft.get("dro") or {}
    _apply_dro_design(ctx, dro, business_id)
    spec = sanitize_spec({"sections": draft.get("spec") or []}, ctx)
    html = site_modules.render_page(spec, ctx,
                                    ctx["business"]["name"] or "Preview")
    return HTMLResponse(_preview_html(html))


class ChooseDirectionBody(BaseModel):
    business_id: str
    draft_id: str


@router.post("/directions/choose")
def choose_direction(body: ChooseDirectionBody,
                     session: UserSession = Depends(sb_clients.authed_request)) -> Dict[str, Any]:
    """Publish the chosen draft as the LIVE site through the full normal
    pipeline: rationale persisted to design_rationales NOW (candidates
    never were), slots populated, overrides reconciled (full_recompose
    semantics — this IS a fresh composition), quality gate, dro_status
    applied, drafts cleared. Returns {ok, url}."""
    _require_owner(body.business_id, session.user.id)
    _site, drafts = _load_direction_drafts(body.business_id)
    draft = next((it for it in (drafts.get("items") or [])
                  if isinstance(it, dict) and it.get("draft_id") == body.draft_id),
                 None)
    if not draft:
        raise HTTPException(404, "draft not found — run directions again")

    ctx = gather_context(body.business_id)
    dro = dict(draft.get("dro") or {})
    from agents.composer.drl.passes import persist_dro
    dro_id = persist_dro(body.business_id, dro)
    if dro_id:
        dro["id"] = dro_id
    _apply_dro_design(ctx, dro, body.business_id)
    spec = sanitize_spec({"sections": draft.get("spec") or []}, ctx)
    concept = str((((dro.get("decisions") or {}).get("hero_concept") or {})
                   .get("concept_statement")) or "")
    dro_summary = concept or str(dro.get("summary_for_practitioner") or "") or None

    result = render_and_persist(
        body.business_id, spec, ctx, dro_id=dro_id, dro=dro,
        dro_status="applied", dro_summary=dro_summary,
        defaulted_modules=[], full_recompose=True)

    # Clear the drafts + record the choice (provenance for the rationale
    # panel). Read-modify-write AFTER render_and_persist so its own
    # site_config update isn't clobbered.
    try:
        from datetime import datetime, timezone
        fresh = sb_clients.sb_get_as_service(
            f"/business_sites?id=eq.{result['site_id']}&select=site_config&limit=1") or []
        cfg = dict((fresh[0].get("site_config") or {}) if fresh else {})
        cfg.pop("direction_drafts", None)
        cfg["direction_choice"] = {
            "draft_id": body.draft_id, "stance": draft.get("stance"),
            "label": draft.get("label"),
            "chosen_at": datetime.now(timezone.utc).isoformat(),
        }
        sb_clients.sb_patch_as_service(
            f"/business_sites?id=eq.{result['site_id']}",
            {"site_config": cfg})
    except Exception as e:
        logger.warning(f"[composer.directions] draft cleanup failed "
                       f"(non-fatal): {e}")

    return {"ok": True, "url": result.get("url"),
            "chosen": {"draft_id": body.draft_id,
                       "stance": draft.get("stance"),
                       "label": draft.get("label")},
            "design_rationale_id": dro_id,
            "quality_report": result.get("quality_report")}


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


# ─── Site Arc 11 — REFINE-SECTION (the resident creator, v1) ─────────
#
# "Creator-quality iteration on demand": the owner points at ONE section
# and says how it should change ('make it moodier', 'more space',
# 'bolder type'). One atelier-style authoring call revises that section
# — the CURRENT html+css (bespoke fragment if one exists, else the
# module render), the DRO brief, the section's real data, and the
# owner's instruction — under the exact bespoke contract (validator,
# one repair). On success the revised fragment replaces (or creates)
# that section's entry in site_config.atelier.fragments — module
# sections BECOME bespoke fragments here — and the page re-renders via
# the stored-fragment path (slots + overrides + quality gate).
# Runs as a 'refine_section' chief_jobs background job (one Opus call).

_REFINE_INSTRUCTION_CAP = 300
_REFINE_FAIL_MSG = "couldn't refine — try different words"


def refine_section(business_id: str, section: str, instruction: str,
                   progress_cb=None) -> Dict[str, Any]:
    """The refine job body (sync; runs in the chief_jobs worker thread).
    Returns {ok: True, section, url, ...} or {ok: False, error} — an
    unrefinable ask is an HONEST result, never a crashed job."""
    import atelier as _atl

    instruction = str(instruction or "").strip()[:_REFINE_INSTRUCTION_CAP]
    if not instruction:
        return {"ok": False, "error": "tell me how the section should change"}
    if not _atl.atelier_enabled():
        return {"ok": False, "error": "refine is disabled on this server "
                                      "(ATELIER_ENABLED=0)"}

    _report_progress(progress_cb, 10, "Reading the section")
    ctx = gather_context(business_id)
    site = ctx.get("site")
    cfg = ((site or {}).get("site_config") or {})
    spec_raw = cfg.get("page_spec")
    if not spec_raw:
        return {"ok": False, "error": "no composed page yet — compose first"}
    spec = sanitize_spec(spec_raw, ctx)

    # Resolve the target: a module key from the page spec ('hero',
    # 'about', …) or a section index.
    sec_key = str(section or "").strip().lower()
    idx: Optional[int] = None
    if sec_key.isdigit():
        i = int(sec_key)
        if 0 <= i < len(spec):
            idx = i
    else:
        idx = next((i for i, s in enumerate(spec)
                    if s.get("module") == sec_key), None)
    if idx is None:
        return {"ok": False,
                "error": f"section '{section}' isn't on the page"}
    sec = spec[idx]
    mid = str(sec.get("module") or "")
    # Data-dense sections stay modular (live records, working forms) —
    # same _NEVER_BESPOKE principle the atelier planner enforces.
    if mid in _atl._NEVER_BESPOKE:
        return {"ok": False,
                "error": f"the {mid} section renders live data and can't be "
                         "restyled this way — try the hero, about, "
                         "offerings, gallery, testimonials or cta section"}

    # Stored DRO (design law of the page) — same load as re-render paths.
    dro: Optional[Dict[str, Any]] = None
    stored_id = cfg.get("design_rationale_id")
    if stored_id:
        try:
            rows = sb_clients.sb_get_as_service(
                f"/design_rationales?id=eq.{stored_id}&select=dro&limit=1") or []
            dro = (rows[0] or {}).get("dro") if rows else None
        except Exception as e:
            logger.info(f"[composer.refine] stored DRO fetch skipped: {e}")
    if dro and not ctx.get("design"):
        _apply_dro_design(ctx, dro, business_id)

    # The CURRENT section: the stored bespoke fragment when one exists,
    # else this render's module output — what the owner is looking at.
    stored_atl = (cfg.get("atelier")
                  if isinstance(cfg.get("atelier"), dict) else {})
    fragments: Dict[str, Any] = {
        m: f for m, f in (stored_atl.get("fragments") or {}).items()
        if isinstance(f, dict)}
    cur = fragments.get(mid)
    if cur and str(cur.get("html") or "").strip():
        cur_html, cur_css = str(cur.get("html") or ""), str(cur.get("css") or "")
    else:
        mspec = site_modules.MODULES.get(mid)
        if not mspec:
            return {"ok": False, "error": f"unknown section '{mid}'"}
        variant = (sec.get("variant") if sec.get("variant") in mspec["variants"]
                   else mspec["variants"][0])
        cur_html, cur_css = mspec["render"](variant, sec.get("content") or {},
                                            ctx)
        if not str(cur_html or "").strip():
            return {"ok": False,
                    "error": f"the {mid} section isn't rendering right now "
                             "(no real data behind it)"}

    _report_progress(progress_cb, 40, "Reworking it")
    out = _atl.generate_refined_section(
        mid, cur_html, cur_css, instruction, dro or {}, ctx,
        sec.get("content") or {}, business_id=business_id)
    if out is None:
        return {"ok": False, "error": _REFINE_FAIL_MSG}

    _report_progress(progress_cb, 80, "Inspecting")
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    fragments[mid] = {"html": out[0], "css": out[1], "index": idx,
                      "variant": sec.get("variant"),
                      "refined_at": now, "instruction": instruction}
    atelier_meta = dict(stored_atl)
    atelier_meta["fragments"] = fragments
    atelier_meta["sections"] = [
        {"index": f.get("index"), "module": m}
        for m, f in fragments.items() if isinstance(f, dict)]
    atelier_meta["model"] = _atl._model()
    atelier_meta["refined_at"] = now

    # Re-render through the stored-fragment path: precomputed fragments
    # (never a second LLM call), slot resolution, override re-stamp,
    # quality gate, persist — render_and_persist persists the updated
    # fragment set onto site_config.atelier. The refine job owns the
    # 10/40/80 stages; render's early full-compose pings (e.g. 55
    # "Drafting bespoke sections" — it's REUSING here, not drafting)
    # are dropped below the 80 floor so the bar stays honest.
    def _render_cb(pct: Any, stage: Any) -> None:
        try:
            if int(pct) >= 80:
                _report_progress(progress_cb, int(pct), stage)
        except (TypeError, ValueError):
            pass

    result = render_and_persist(business_id, spec, ctx,
                                _atelier=atelier_meta,
                                progress_cb=_render_cb)
    _report_progress(progress_cb, 100, "Done")
    return {"ok": True, "section": mid, "instruction": instruction,
            "site_id": result.get("site_id"), "slug": result.get("slug"),
            "url": result.get("url"),
            "quality_report": result.get("quality_report")}


class RefineSectionBody(BaseModel):
    business_id: str
    section: str
    instruction: str


@router.post("/refine-section")
async def start_refine_section(body: RefineSectionBody,
                               session: UserSession = Depends(sb_clients.authed_request)
                               ) -> Dict[str, Any]:
    """Enqueue a 'refine_section' job (ONE atelier call ≈ 30-90s — never
    sync). Owner-gated; returns {ok, job_id}. The frontend polls
    /agents/chief/jobs; the job result carries ok/error per the honest-
    failure contract (a failed refine is a DONE job with ok:false)."""
    import asyncio
    import httpx
    import chief_jobs
    uid = session.user.id
    await asyncio.to_thread(_require_owner, body.business_id, uid)
    section = str(body.section or "").strip()[:40]
    instruction = str(body.instruction or "").strip()[:_REFINE_INSTRUCTION_CAP]
    if not section:
        raise HTTPException(400, "section required")
    if not instruction:
        raise HTTPException(400, "instruction required")
    async with httpx.AsyncClient() as client:
        job = await chief_jobs.enqueue(
            client, user_id=uid, business_id=body.business_id,
            kind="refine_section",
            params={"section": section, "instruction": instruction},
            source="desktop")
    if not job:
        raise HTTPException(500, "could not enqueue refine job")
    out = {"ok": True, "job_id": job.get("id")}
    if job.get("deduped"):
        out["deduped"] = True
    return out
