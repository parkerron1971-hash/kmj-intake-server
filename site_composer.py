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
import llm_call
import logging
import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

from fastapi import (APIRouter, Depends, File, HTTPException, UploadFile,
                     Form as FormField)
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
              "pull_quote": 260, "headline": 120, "eyebrow": 60, "cta_label": 40,
              "statement_1": 90, "statement_2": 90, "statement_3": 90}


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
# Interview v3 (B1) — the owner's three verbs (hero material: the hand-built
# KMJ hero "BUILD. / BRAND. / GROW." came from exactly this data) and the
# "what specifically do you love" inspiration answer. R1: fields and their
# allowlist entries ship in the same arc.
_MAX_HERO_VERBS = 3
_HERO_VERB_CAP = 24
# inspiration_notes reuses _PREF_STR_CAP (400).
# Arc 6 "Creative Engine" — v3 creative brief enums/caps.
_LOUD_WHERE = ("motion", "type", "imagery", "layout")
_CREATIVE_CAPS = {"metaphor": 200, "surprise": 200, "remember": 160}
_TENSION_POLE_CAP = 80
# Arc 10 "offer clarity" — the owner's plain-words answer to "What exactly
# do you offer, and for whom?" (Kevin's rule: if the offer isn't clear,
# Chief asks in the interview; when answered, the site must make it
# unmistakable).
_OFFER_CAP = 600
_STORY_FIELD_CAP = 500  # Arc 12 — per-answer cap, story walkthrough
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
    hero_verbs ≤ 3 (≤24 chars each), inspiration_notes ≤ 400,
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

    # Arc 12 — the STORY walkthrough (the material creativity feeds on):
    # five optional free-text answers from Chief's story interview.
    story_raw = raw.get("story")
    if isinstance(story_raw, dict):
        story: Dict[str, str] = {}
        for k in ("origin", "craft", "proof", "voice", "atmosphere"):
            v = story_raw.get(k)
            if isinstance(v, str) and v.strip():
                story[k] = v.strip()[:_STORY_FIELD_CAP]
        if story:
            out["story"] = story

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

    # Interview v3 (B1) — hero_verbs (≤3, each ≤24 chars, trimmed, empties
    # dropped) + inspiration_notes (≤400, trimmed). Same leniency as
    # feel_words / notes above.
    hv = raw.get("hero_verbs")
    if isinstance(hv, (list, tuple)):
        verbs = [str(w).strip()[:_HERO_VERB_CAP] for w in hv
                 if isinstance(w, (str, int, float)) and str(w).strip()]
        if verbs:
            out["hero_verbs"] = verbs[:_MAX_HERO_VERBS]
    inotes = raw.get("inspiration_notes")
    if isinstance(inotes, str) and inotes.strip():
        out["inspiration_notes"] = inotes.strip()[:_PREF_STR_CAP]

    # VISUAL STYLE, CONFIRMED AT INTAKE (2026-08-03). The sentence lives in
    # the Brand Room, but taste moves — the owner may have written it months
    # ago, and the designer may since have found a better look. So it gets
    # OFFERED BACK at beat 6, and the value that reaches the build is the one
    # they just confirmed, never the stale stored one. Same leniency and cap
    # as the other free-text prefs. _persist_site_prefs mirrors a CHANGED
    # sentence back to the brand kit; an unchanged confirm writes nothing.
    vstyle = raw.get("visual_style")
    if isinstance(vstyle, str) and vstyle.strip():
        out["visual_style"] = vstyle.strip()[:_PREF_STR_CAP]

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
        # Colors as SEEDS (2026-07-23, Studio adoption): the owner may
        # describe colors in words ("navy and gold", "warm and earthy")
        # instead of picking swatches.
        w = c.get("words")
        if isinstance(w, str) and w.strip():
            cout["words"] = w.strip()[:120]
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
    # ── Interview v2 (design-quality audit fix R1, 2026-07-18): these
    # fields were collected by the interview and silently dropped here —
    # their downstream consumers (atelier REAL DATA, gallery-by-intent,
    # type pairing) read keys that never existed. THE RULE: every new
    # SitePrefs field ships with its allowlist entry, same arc.
    # Slogan / key statement (Kevin's ruling 2026-07-22): the owner gives
    # EITHER a slogan OR their three verbs — Chief forges the page's key
    # statements from whichever exists.
    sl = raw.get("slogan")
    if isinstance(sl, str) and sl.strip():
        out["slogan"] = sl.strip()[:120]
    tp = raw.get("type_personality")
    if isinstance(tp, str) and tp.strip().lower() in (
            "statement", "editorial", "modern_minimal", "classic",
            "handcrafted", "brand_fonts"):
        out["type_personality"] = tp.strip().lower()
    st = raw.get("structure")
    if isinstance(st, str) and st.strip().lower() in ("one_page", "multi_page"):
        out["structure"] = st.strip().lower()
    if isinstance(raw.get("wants_gallery"), bool):
        out["wants_gallery"] = raw["wants_gallery"]
    ps = raw.get("proof_stats")
    if isinstance(ps, list):
        stats = []
        for item in ps[:3]:
            if not isinstance(item, dict):
                continue
            label = str(item.get("label") or "").strip()[:40]
            value = str(item.get("value") or "").strip()[:20]
            if label and value:
                stats.append({"label": label, "value": value})
        if stats:
            out["proof_stats"] = stats
    pr = raw.get("process_steps")
    if isinstance(pr, list):
        steps = []
        for item in pr[:5]:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "").strip()[:60]
            if not title:
                continue
            blurb = str(item.get("blurb") or "").strip()[:200]
            steps.append({"title": title, **({"blurb": blurb} if blurb else {})})
        if steps:
            out["process_steps"] = steps
    return out or None


def _persist_site_prefs(business_id: str, prefs: Dict[str, Any]) -> None:
    """Write sanitized prefs to businesses.settings.site_prefs via the
    read-modify-write settings idiom (same as rules_router.pause_all) so
    sibling settings keys survive. Called BEFORE gather_context so the
    compose that follows reads the fresh prefs back from settings.
    Arc 5: the stored reference_analysis rides along — compose_site
    re-runs it only when the inspiration_urls actually changed.

    Visual style write-back (2026-08-03): when the owner CHANGED the
    sentence at beat 6, the Brand Room's copy is updated in the same PATCH
    — settings is already in hand, so it costs no extra round-trip. Only a
    real change writes: tapping "still right" produces an identical string
    and touches nothing. Surgical (the one key, no brand-kit history
    snapshot) for the same reason persist_creative_expression is surgical —
    history is for practitioner-driven kit edits in the Brand Room, not for
    every intake that re-affirms what was already there."""
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

    confirmed_style = str(fresh.get("visual_style") or "").strip()
    if confirmed_style:
        kit = settings.get("brand_kit")
        kit = dict(kit) if isinstance(kit, dict) else {}
        if str(kit.get("visual_style") or "").strip() != confirmed_style:
            kit["visual_style"] = confirmed_style
            settings["brand_kit"] = kit
            logger.info(f"[composer.prefs] {business_id}: visual_style "
                        f"changed at intake → mirrored to brand kit")

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
    # Booking detection fix (2026-07-10): recognize the REAL system —
    # active booking_calendar module + published booking page — not
    # just the legacy settings.booking.enabled flag nothing writes.
    # One-calendar pass (same day): the URL now uses the CANONICAL
    # hosted page (https://{slug}.<domain>/book — the D.2 resolver the
    # Embed tab advertises). The old /public/booking/{slug} Railway
    # path is the LEGACY page and 404s for module-based businesses —
    # every composed CTA was pointing visitors at it.
    from booking_widget_router import booking_is_live
    from business_sites_helpers import booking_url_for_site
    booking = {
        "enabled": booking_is_live(business_id, settings) and bool(slug),
        "url": booking_url_for_site(site) if (site and slug) else "",
    }

    # Online giving — same connection pattern as booking: composed sites
    # for ministries/nonprofits link the hosted give page. Enabled only
    # when the give surface is actually live (nonprofit family + operator
    # enabled + Stripe connected) so no composed CTA can dead-end.
    giving = {"enabled": False, "url": ""}
    try:
        from giving_router import give_url_for_site, giving_is_active
        if site and slug and giving_is_active(biz):
            giving = {"enabled": True, "url": give_url_for_site(site)}
    except Exception as e:
        logger.info(f"[composer] giving connection skipped: {e}")

    # Only real dict rows the owner left visible reach composed sites —
    # hidden quotes (show_on_website=False) must not render, inflate the
    # statband count, or pad the LLM prompt; legacy string entries are
    # dropped (modules also self-defend, but the context is the choke point).
    _testi_raw = ((settings.get("website_content") or {}).get("testimonials")) or []
    testimonials = [t for t in _testi_raw
                    if isinstance(t, dict) and t.get("show_on_website", True)]

    # Real gallery/portfolio photos (settings.media_library.gallery) — the
    # practitioner's OWN pictures of products / finished work / results. Only
    # visible ones, in their chosen order. THIS is what the gallery module
    # renders now (composed sites used to show stock-only galleries and never
    # touched these). Empty → the gallery self-drops.
    _gal_raw = ((settings.get("media_library") or {}).get("gallery")) or []
    gallery_imgs = sorted(
        [g for g in _gal_raw
         if isinstance(g, dict) and str(g.get("url") or "").strip()
         and g.get("show_on_website", True)],
        key=lambda g: g.get("sort_order", 0))

    # Arc S "Business Picture" (2026-07-10, Kevin's insight: "they have
    # to have rules of engagement for their business") — policies + FAQ
    # gathered by Chief (set_business_policy / add_faq) into
    # settings.business_picture. Policies become their natural questions;
    # explicit Q&As follow. The faq module renders these records
    # directly; nothing is ever invented.
    business_picture = settings.get("business_picture") or {}
    _POLICY_QUESTIONS = (
        ("cancellation", "What is your cancellation policy?"),
        ("deposit", "Do you require a deposit?"),
        ("lateness", "What if I'm running late?"),
        ("refunds", "What is your refund policy?"),
        ("no_show", "What happens if I miss my appointment?"),
    )
    faq_rows: List[Dict[str, str]] = []
    _seen_q: set = set()

    def _norm_q(q: str) -> str:
        return " ".join(str(q or "").lower().split()).strip("?.! ")

    _pol = (business_picture.get("policies")
            if isinstance(business_picture.get("policies"), dict) else {})
    for _k, _q in _POLICY_QUESTIONS:
        _a = str(_pol.get(_k) or "").strip()
        if _a:
            faq_rows.append({"q": _q, "a": _a[:600]})
            _seen_q.add(_norm_q(_q))
    # Dedupe fix (2026-07-10, Kevin's screenshot): an explicit FAQ entry
    # matching a policy-derived question (or an earlier entry) rendered
    # the same question twice — the explicit entry's ANSWER wins when it
    # collides with a policy question (the owner wrote it deliberately).
    for _r in (business_picture.get("faq") or []):
        if (isinstance(_r, dict) and str(_r.get("q") or "").strip()
                and str(_r.get("a") or "").strip()):
            _nq = _norm_q(_r["q"])
            if _nq in _seen_q:
                for _row in faq_rows:
                    if _norm_q(_row["q"]) == _nq:
                        _row["a"] = str(_r["a"]).strip()[:600]
                        break
                continue
            _seen_q.add(_nq)
            faq_rows.append({"q": str(_r["q"]).strip()[:200],
                             "a": str(_r["a"]).strip()[:600]})
    faq_rows = faq_rows[:10]

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

    # "Teach the rubric, not the cases": REASON the owner's style words into
    # the best-fit vibe instead of keyword-matching a table — so a descriptor
    # nobody coded ("trustworthy", "serene", "modern law firm") still lands
    # sensibly. Decided ONCE here at compose time and persisted onto
    # design.vibe_family, so the deterministic pipeline (build_brand_dna /
    # _infer_vibe) just consumes it and the render path never calls a model.
    # Precedence: an explicit vibe_family enum always wins; fail-open →
    # the downstream keyword matcher still runs. See design_intent.py.
    try:
        import design_intent
        _dcfg = bundle.get("design") if isinstance(bundle.get("design"), dict) else {}
        if (_dcfg.get("vibe_family") or "").strip().lower() not in design_intent.VIBE_FAMILIES:
            _voice = bundle.get("voice") if isinstance(bundle.get("voice"), dict) else {}
            _read = design_intent.interpret(
                _voice.get("tone_words"),
                business_type=(bundle.get("business") or {}).get("type"))
            if _read:
                _dcfg["vibe_family"] = _read["vibe"]
                _dcfg["vibe_rationale"] = _read.get("rationale")  # inspectable
                _expr = (_dcfg.get("creative_expression")
                         if isinstance(_dcfg.get("creative_expression"), dict) else {})
                _expr.setdefault("intensity", _read["intensity"])
                _dcfg["creative_expression"] = _expr
                bundle["design"] = _dcfg
    except Exception:
        pass

    # Arc 5 "Design Depth": the owner's color language steers derivation
    # deterministically — colors.love/avoid/use_brand nudge the accent in
    # derive_palette; colors.direction is a HARD ground preference applied
    # here so no-DRO paths (fallback compose, shuffle, refresh) honor it
    # too. compose_site re-asserts it after apply_dro_palette (owner beats
    # model) and logs when the DRO's base was overridden.
    color_prefs = (site_prefs.get("colors")
                   if isinstance(site_prefs.get("colors"), dict) else None)
    # COLOR SEEDS + PROVENANCE (2026-07-23, Studio adoption): words like
    # "navy and gold" become love-anchors when no explicit picks exist,
    # and color_source records where the palette's anchors came from —
    # ending the "where is this green from" forensics class.
    color_source = "owner_hex" if (color_prefs or {}).get("love") else None
    if (color_prefs and not color_prefs.get("love")
            and color_prefs.get("words")):
        _seeds = brand_dna.interpret_color_words(color_prefs["words"])
        if _seeds:
            color_prefs = {**color_prefs, "love": _seeds}
            color_source = "interpreted_words"
    if color_source is None:
        color_source = ("brand_kit" if (color_prefs or {}).get("use_brand") is not False
                        else "model")
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

    # Phase 2 (spec Stage C): deterministic motion + rhythm tokens from
    # the boldness dial — consumed by renderers (Phase 3) and graded by
    # the invariants. Motion stops being a renderer constant.
    try:
        from design_tokens import boldness_from_prefs, motion_tokens, rhythm_scale
        _b = boldness_from_prefs(site_prefs)
        _motion = motion_tokens(_b)
        _rhythm = rhythm_scale(_b)
    except Exception:
        _motion, _rhythm = {}, {}

    # Phase 3 (spec 5): authored hero + motion specs — the nav pattern
    # applied again. TTL-cached; None on any failure -> deterministic
    # fallback (today's rendering, byte-identical).
    try:
        from design_specs import author_hero_spec, author_motion_spec
        _dsbiz = {"name": biz.get("name") or "", "type": biz.get("type") or ""}
        _hero_spec = author_hero_spec(business_id, _dsbiz,
                                      dna if isinstance(dna, dict) else {},
                                      site_prefs if isinstance(site_prefs, dict) else {})
        _motion_spec = author_motion_spec(business_id, _dsbiz,
                                          dna if isinstance(dna, dict) else {},
                                          site_prefs if isinstance(site_prefs, dict) else {})
    except Exception:
        _hero_spec, _motion_spec = None, None

    # Creative-capture arc (2026-07-18) — the model AUTHORS the menu spec
    # (nav_spec.py; TTL-cached so multi-page composes share one menu and
    # previews are free). None on any failure/env-off → header falls back
    # to the DNA-variant bars.
    try:
        from nav_spec import author_nav_spec
        nav_spec = author_nav_spec(
            business_id,
            {"name": biz.get("name") or "", "type": biz.get("type") or ""},
            dna if isinstance(dna, dict) else {},
            site_prefs if isinstance(site_prefs, dict) else {},
            voice_profile=biz.get("voice_profile") if isinstance(biz.get("voice_profile"), dict) else {},
        )
    except Exception:
        nav_spec = None

    return {
        "nav_spec": nav_spec,
        "hero_spec": _hero_spec,
        "motion_spec": _motion_spec,
        "motion_tokens": _motion,
        "rhythm_scale": _rhythm,
        "site_prefs": site_prefs,
        "color_source": color_source,
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
        "gallery": gallery_imgs,
        "faq": faq_rows,
        "business_picture": business_picture,
        "booking": booking,
        "giving": giving,
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
    # B5 (2026-07-18) — the no-LLM floor rotates OFF the old centered-hero
    # + cards + CTA-band skeleton (doctrine D11's banned template). Every
    # pick stays inside what the modules render safely with real data:
    # bold gets the bottom-gravity film title ("anchored" — "banner" was a
    # near-duplicate of the cinematic skeleton); formal gets the engraved
    # menu when prices exist (the price list as craft object); warm gets
    # the flagship-and-index hierarchy (D9: prominence follows weight).
    hero_variant = {"warm": "split", "formal": "statement", "bold": "anchored"}[dna["vibe"]]
    b = (ctx.get("bundle") or {}).get("business") or {}
    tagline = str(b.get("tagline") or "").strip()
    pitch = str(b.get("elevator_pitch") or "").strip()
    headline = tagline or biz["name"]
    subheadline = pitch if pitch and pitch != headline else (tagline if tagline != headline else "")
    goal_label = _CTA_GOAL_LABELS.get(str(ctx.get("cta_goal") or ""),
                                      "Book a session")
    _offerings = ctx.get("offerings") or []
    _has_prices = any(o.get("price") not in (None, "") for o in _offerings)
    if dna["vibe"] == "formal":
        offerings_variant = "menu" if _has_prices else "list"
    elif dna["vibe"] == "warm" and len(_offerings) >= 3:
        offerings_variant = "featured"
    else:
        offerings_variant = "cards"
    spec = [
        {"module": "hero", "variant": hero_variant,
         "content": {"headline": headline, "subheadline": subheadline,
                     "cta_label": goal_label}},
        # about body left empty on purpose: the about module backfills it
        # from practitioner_intelligence.about_business (real data) and
        # DROPS the section when nothing real exists.
        {"module": "about", "variant": "portrait" if dna["vibe"] != "formal" else "narrative",
         "content": {"headline": _stock_headline("about", ctx)}},
        {"module": "offerings", "variant": offerings_variant,
         "content": {"headline": _stock_headline("offerings", ctx)}},
        {"module": "testimonials",
         "variant": "spotlight" if len(ctx.get("testimonials") or []) < 3 else "grid",
         "content": {}},
        {"module": "cta", "variant": "band",
         "content": {"headline": _stock_headline("cta", ctx)}},
        {"module": "contact", "variant": "standard",
         "content": {"headline": _stock_headline("contact", ctx)}},
    ]
    # Gallery: ANY business that uploaded real photos gets one now (their
    # products / finished work / results) — not just bold/creative vibes.
    # The module self-drops if there are none, so this is safe either way.
    # Image-forward businesses lead with the editorial mosaic; others get the
    # clean uniform grid.
    if ctx.get("gallery"):
        _gal_variant = ("mosaic" if (dna["vibe"] == "bold"
                                     or "creative" in (biz.get("type") or "")) else "grid")
        spec.insert(3, {"module": "gallery", "variant": _gal_variant, "content": {}})
    if (ctx.get("store") or {}).get("enabled"):
        spec.insert(-2, {"module": "store", "variant": "featured", "content": {}})
    # Arc S — the rules-of-engagement ledger, when the business has one.
    if ctx.get("faq"):
        spec.insert(-2, {"module": "faq", "variant": "ledger",
                         "content": {"headline": "Good to know"}})
    return spec


# ─── LLM composition ─────────────────────────────────────────────────

def _creative_plus_story(ctx: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Design audit P3 (2026-07-18): the story walkthrough — the richest
    creative material the interview collects — previously reached only
    the DRL signal pass (as intake text). Now it rides the creative
    brief into DRO authoring verbatim. Absent story -> the creative
    dict passes through unchanged (byte-identical prompts)."""
    prefs = ctx.get("site_prefs") if isinstance(ctx.get("site_prefs"), dict) else {}
    creative = prefs.get("creative") if isinstance(prefs.get("creative"), dict) else None
    story = prefs.get("story") if isinstance(prefs.get("story"), dict) else None
    if not story:
        return creative
    out = dict(creative or {})
    out["story"] = story
    return out


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
    # The visual-style sentence the owner CONFIRMED at intake (beat 6) —
    # first-person, freshly re-affirmed, so it sits at the top of the
    # evidence block with feel_words rather than in the older bundle text
    # below (which the fixed cap can truncate). Absent when they never ran
    # the interview; the stored brand-kit sentence alone never lands here,
    # by design — unconfirmed taste is not evidence.
    if prefs.get("visual_style"):
        pref_lines.append(f"How it should look, in their words: "
                          f"\"{prefs['visual_style']}\"")
    if prefs.get("inspiration"):
        pref_lines.append(f"Inspiration: {prefs['inspiration']}")
    if prefs.get("type_personality"):
        pref_lines.append(f"Type voice the owner chose: {prefs['type_personality']}")
    if prefs.get("inspiration_urls"):
        pref_lines.append("Sites I admire: "
                          + ", ".join(str(u) for u in prefs["inspiration_urls"][:3]))
    # Interview v3 (B1) — the verbs can literally become the hero headline;
    # the inspiration "what specifically" rides verbatim so the signal pass
    # sees it (never appended into `notes`).
    if prefs.get("hero_verbs"):
        pref_lines.append("Owner's three verbs (hero material): "
                          + ", ".join(str(v) for v in prefs["hero_verbs"][:3]))
    if prefs.get("slogan"):
        pref_lines.append(
            f"Owner's slogan / key statement: \"{prefs['slogan']}\" — this is "
            "LOAD-BEARING copy: the hero subheadline or a gallery statement "
            "board must carry it (verbatim or lightly polished), and every "
            "other key statement should rhyme with its voice.")
    if prefs.get("inspiration_notes"):
        pref_lines.append("What the owner loves about their inspiration "
                          f"sites: {prefs['inspiration_notes']}")
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

    # Arc 12 — the STORY walkthrough: the richest signal material there
    # is. Verbatim, labeled, right after the offer so the DRL reads the
    # owner's story before any derived/base facts. Absent → byte-identical.
    story = prefs.get("story") if isinstance(prefs.get("story"), dict) else {}
    if story:
        _labels = (("origin", "How it started"),
                   ("craft", "What people never guess it takes"),
                   ("proof", "Proudest work"),
                   ("voice", "What clients say"),
                   ("atmosphere", "What walking in feels like"))
        lines = [f"{label}: {str(story[k]).strip()}"
                 for k, label in _labels if str(story.get(k) or "").strip()]
        if lines:
            segments.append(
                "THE OWNER'S STORY (their own words — mine it for copy, "
                "metaphor, and evidence; quote it as signal evidence):\n"
                + "\n".join(lines))

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
- Gallery statement boards: fill gallery statement_1/statement_2/statement_3 — three SHORT craft-manifesto lines (3-8 words each) in the concept's voice, mounted as accent plates between the photos. They are convictions about how the work is made ("Faith, worn boldly", "Built for the called"), NEVER captions, never generic ("Quality you can trust" is a failure). If the owner gave verbs or a metaphor, forge the lines from those.
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


# ─── Spec/copy stage LLM call (A3, 2026-07-18) ───────────────────────
# The spec stage writes ALL page copy and picks every module — it is a
# creative stage, so it gets what the DRL passes and the atelier already
# had: the doctrine as system prompt (Symmetry Rule: identical content
# for both providers), provider routing through site_llm, the full model
# ladder, and usage metering. Before this, it was a raw httpx call to a
# hardcoded model at max_tokens=1600 with no doctrine and no telemetry —
# untreated LLM-default prose on every build, and "Kimi builds" whose
# copy was silently always Claude.

SPEC_MAX_TOKENS = 4000  # was 1600 — truncated rich page specs mid-JSON


def _spec_model() -> str:
    return (os.environ.get("SITE_SPEC_MODEL") or "").strip() or "claude-opus-4-7"


def _call_spec_stage(*, system: str, user: str, business_id: str) -> str:
    """Mirror of the DRL passes' _call: moonshot via site_llm (fail-open
    to the FULL Claude ladder, not one brittle call), anthropic via the
    ladder directly. Usage logged to /composer/spec."""
    import model_ladder
    import site_llm

    def _do(model: str, max_tokens: int, timeout: float):
        from anthropic import Anthropic
        client = llm_call.sdk_client(key=os.environ.get("ANTHROPIC_API_KEY"))
        return client.messages.create(
            model=model, max_tokens=max_tokens,
            system=system, messages=[{"role": "user", "content": user}],
            timeout=timeout,
            **model_ladder.sampling_kwargs(model, None))

    if site_llm.provider() == "moonshot":
        try:
            msg = site_llm.create_message(
                model=_spec_model(), max_tokens=SPEC_MAX_TOKENS,
                system=system, user_content=user,
                timeout=model_ladder.timeout_for("spec", _spec_model()) + 120.0,
                task="composer/spec")
            used_model = getattr(msg, "model", "moonshot")
        except Exception as _ms_err:
            logger.warning(f"[composer] moonshot spec call failed "
                           f"({type(_ms_err).__name__}) — full ladder fallback")
            msg, used_model = model_ladder.call_with_ladder(
                _do, model=_spec_model(), task="spec",
                business_id=business_id, max_tokens=SPEC_MAX_TOKENS)
    else:
        msg, used_model = model_ladder.call_with_ladder(
            _do, model=_spec_model(), task="spec",
            business_id=business_id, max_tokens=SPEC_MAX_TOKENS)
    try:
        from api_usage_logger import log_api_usage_sync
        u = getattr(msg, "usage", None)
        log_api_usage_sync(
            endpoint="/composer/spec", model=used_model,
            input_tokens=getattr(u, "input_tokens", 0) or 0,
            output_tokens=getattr(u, "output_tokens", 0) or 0,
            business_id=business_id, task_type="composer")
    except Exception:
        pass
    return "".join(b.text for b in msg.content if getattr(b, "type", None) == "text")


def compose_spec_llm(ctx: Dict[str, Any], brief_notes: str = "",
                     dro: Optional[Dict[str, Any]] = None,
                     feedback: str = "") -> List[Dict[str, Any]]:
    from studio_designer_agent import _extract_json
    from design_doctrine import DOCTRINE, DIVERSITY_LINE

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
    # Interview v3 (B1) — the owner's three verbs are hero-headline material.
    _hero_verbs = [str(v).strip() for v in (_prefs.get("hero_verbs") or [])
                   if str(v or "").strip()][:3]
    hero_verbs_line = (f"\n- THE OWNER'S THREE VERBS: {', '.join(_hero_verbs)} — "
                       "the hero headline should consider the owner's verbs verbatim."
                       if _hero_verbs else "")

    dro_block = ("\n\n" + _dro_directive(dro) + "\n") if dro else ""
    _p3_prefs = ctx.get("site_prefs") if isinstance(ctx.get("site_prefs"), dict) else {}
    _owner_stats_n = len(_p3_prefs.get("proof_stats") or [])
    _owner_steps_n = len(_p3_prefs.get("process_steps") or [])
    _owner_stats_note = (f" The owner supplied {_owner_stats_n} proof points of "
                         "their own — statband renders them first; INCLUDE it."
                         if _owner_stats_n else "")
    _owner_steps_line = (f'\n- "process": the owner wrote their own '
                         f"{_owner_steps_n}-step process — the module renders "
                         "those real steps (numbered); you write only eyebrow/"
                         "headline/intro. INCLUDE it, between the offer and the proof."
                         if _owner_steps_n else "")
    # A2 — the bounded quality regen injects the vision grader's notes
    # here so the second copy pass fixes what the grader flagged.
    _feedback_line = ("\n- GRADER FEEDBACK FROM THE PREVIOUS RENDER — the last "
                      "version of this page FAILED design grading. Address EVERY "
                      "point with materially different choices, not small tweaks:\n"
                      + feedback.strip()[:900]
                      if (feedback or "").strip() else "")

    # A3: doctrine-fronted system prompt (identical for both providers —
    # Symmetry Rule). The role line used to ride the user message with no
    # doctrine at all.
    system = (DOCTRINE + "\n\n"
              "You are a creative director composing a one-page website. "
              "You do NOT write HTML or CSS — the platform renders "
              "everything. Your job: choose section modules + expression "
              "variants, and write the copy in the practitioner's voice.\n\n"
              + DIVERSITY_LINE)
    user_prompt = f"""{dro_block}
BUSINESS
- Name: {biz['name']}
- Type: {biz['type']}
- Tagline: {(bundle.get('business') or {}).get('tagline') or '(none)'}{offer_line}{hero_verbs_line}
- About (real, from the practitioner): {str(intel.get('about_business') or intel.get('about_me') or '')[:600] or '(none provided)'}
- Voice/tone: {voice.get('brand_voice') or ''} {voice.get('tone_words') or ''}
- Design vibe: {ctx['dna']['vibe']}, intensity: {ctx['dna']['intensity']}
- Real offerings on file: {off_names or '(none)'}
- Real testimonials on file: {n_testi}
- Public custom modules the business RUNS (surface via the "showcase" section): {', '.join((m.get('title') or '') + f" ({len(m.get('entries') or [])})" for m in (ctx.get('public_modules') or [])) or '(none)'}
- Contact wiring: a real contact form + {('hours, ' if (ctx.get('contact') or {}).get('hours') else '')}{('address, ' if (ctx.get('contact') or {}).get('address') else '')}{('phone, ' if (ctx.get('contact') or {}).get('phone') else '')}socials render automatically in the "contact" section — you only write its framing.
{_cta_goal_prompt_line(ctx)}{f'- Practitioner notes for this build: {brief_notes[:400]}' if brief_notes else ''}{_feedback_line}

AVAILABLE MODULES (use each at most once; order is yours except hero first, contact last):
{_module_menu()}

VARIANT GUIDE (when to reach for the expressive variants):
- hero "editorial": asymmetric offset split, oversized display type, one accent-italic word — personality-forward, editorial brands.
- hero "constructed": typographic statement over a generated ornament field, NO photo — when the concept is abstract/metaphorical or imagery is weak.
- hero "anchored": bottom-gravity film title — the headline rests on the FLOOR of a full-bleed photo under a baseline-deepening scrim and lands word by word — grounded, ceremonial, sanctuary-feel brands.
- offerings "menu": the engraved menu — hairline-ruled rows, italic serif names, whisper-caps prices right-aligned — when the price list itself is the craft object (salons, studios, ateliers).
- about "pullquote": magazine spread — one strong line pulled large + narrative column + framed portrait. Pick when the about copy has a quotable line.
- offerings "featured": the first offering as a flagship feature card (with image), the rest as numbered compact rows — when one offering clearly leads.
- "statband": 3-4 big real numbers (years in business, offerings, testimonials). Include for established businesses; it renders nothing when the numbers aren't there, so never lean copy on it.{_owner_stats_note}{_owner_steps_line}
- testimonials "marquee": one oversized hero quote + two supporting — when the best quote deserves a spotlight and 3+ exist.
- gallery "mosaic": varied-size image mosaic with soft fades — for visual businesses with strong imagery.
- cta "editorial": the quiet close — hairline seam, oversized display line, text-link CTA whose underline draws on hover — when the page already has a loud band elsewhere or the concept is restrained/formal.
- statband "ledger": the quiet proof — hairline-ruled rows, display numeral left, whisper label right — editorial/restrained concepts where a full gold band would shout.
- store "shelf": unboxed products on one shared baseline hairline — image, name, whisper price — studio/atelier retail with strong product photography.
- contact "centered": one centered column, the form card beneath the ask — a ceremonial close for centered-formal layouts.

RULES
- If a DESIGN RATIONALE block appears above, it OVERRIDES generic instincts: concept-voice copy (in-concept headline/eyebrows/CTAs) and the section order it specifies are REQUIRED, not optional.
- THE SELLING LAW (2026-07-23, Kevin's ruling — the site's JOB): a visitor must leave every section knowing WHAT this business does, WHO it serves, and WHY to act — the copy is the practitioner's best salesperson, not a mood board. Every body/intro/subheadline field is FULL SENTENCES rich with the real facts you were given (offerings, prices, process, stats, story) — never bare fragments. A stylish fragment ("Kept quiet and kept honest.") may open a section ONLY when a complete, concrete selling sentence follows it. If you know a fact a buyer would want (what's included, how long, what it costs, what changes for them), it belongs in the copy. Thin copy is a failed section.
- Copy must sound like THIS practitioner, not a template. Specific beats generic.
- A stranger must know within 5 seconds what is offered and for whom — the hero
  subheadline and the offerings section carry this burden.{" Use the owner's offer statement verbatim-adjacent." if offer_stmt else ""}
- NEVER invent facts, testimonials, credentials, or offerings. The offerings and
  testimonials modules render the real records automatically — you only write the
  section framing (eyebrow/headline/intro).
- Include "offerings" only if offerings exist; "testimonials" only if testimonials exist;
  "store" only if sellable products exist ({(ctx.get('store') or {}).get('enabled') and len((ctx.get('store') or {}).get('items') or []) or 0} on file).
- Include "faq" only when the business has policies/Q&As on file ({len(ctx.get('faq') or [])} on file) — it renders the real records automatically; you only write eyebrow/headline. Place it late (before or after the CTA, never before the offer is made).
- Include "showcase" whenever public custom modules exist (listed above) — it surfaces the real tools/programs the business runs; frame its eyebrow/headline/intro in-concept.
- headline ≤ 9 words. subheadline/intro: 1-2 sentences. about body: 2-4 sentences,
  first person where natural.
- Choose variants for contrast and rhythm — don't pick the first variant of everything.

Respond with ONLY this JSON:
{{"sections": [{{"module": "hero", "variant": "...", "content": {{"headline": "...", ...}}}}, ...]}}"""

    business_id = str((biz or {}).get("id") or "")
    raw = _call_spec_stage(system=system, user=user_prompt,
                           business_id=business_id)
    parsed = _extract_json(raw)
    if not parsed:
        # One parse-repair retry (same pattern as the DRL passes) before
        # giving up to the deterministic default spec.
        logger.warning("[composer] spec JSON parse failed — repair retry")
        raw = _call_spec_stage(
            system=system,
            user=user_prompt + "\n\nREMINDER: your previous reply was not "
                               "parseable JSON. Respond with ONLY the JSON "
                               "object — no prose, no code fences.",
            business_id=business_id)
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
        # AUDIT FIX (2026-07-24, the contamination audit): stale rows
        # were applied forever — color overrides had NO reconciliation,
        # so tweaks made against an OLD design repainted every NEW
        # design (!important, every render, positional key collisions).
        if str((row or {}).get("status") or "active") == "stale":
            continue
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
    "statband": "stats", "process": "process",
}

# Self-heal headline defaults — same voice as _default_spec (never
# invented facts, just the platform's neutral framing lines).
# B5 (2026-07-18): the fallback floor no longer speaks one platform-wide
# stock voice — heal/default headlines are keyed by the build's vibe.
# Still deterministic, still generic-safe; just not identical on every
# fallback page (doctrine D1: restating the brief back is failure —
# and so is every fallback site reading as the same template).
_STOCK_HEADLINES: Dict[str, Dict[str, str]] = {
    "about":        {"warm": "The practice", "formal": "The practice", "bold": "The work, up close"},
    "offerings":    {"warm": "Ways to work together", "formal": "Services", "bold": "What we do best"},
    "cta":          {"warm": "Ready when you are.", "formal": "Begin the conversation.", "bold": "Let's make it happen."},
    "contact":      {"warm": "Get in touch", "formal": "Contact the practice", "bold": "Say hello"},
    "testimonials": {"warm": "Kind words", "formal": "What clients say", "bold": "Word of mouth"},
    "gallery":      {"warm": "The work", "formal": "Selected work", "bold": "The proof"},
    "store":        {"warm": "The shop", "formal": "The shop", "bold": "The goods"},
    "showcase":     {"warm": "What we run", "formal": "Programs", "bold": "What we're building"},
    "statband":     {"warm": "By the numbers", "formal": "By the numbers", "bold": "The receipts"},
    "process":      {"warm": "How it works", "formal": "The process", "bold": "How it gets done"},
}


def _stock_headline(module: str, ctx: Dict[str, Any]) -> str:
    vibe = str((ctx.get("dna") or {}).get("vibe") or "formal")
    per_vibe = _STOCK_HEADLINES.get(module) or {}
    return per_vibe.get(vibe) or per_vibe.get("formal") or ""

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
# The census machinery lives in site_modules/_base.py (F4, 2026-07-18)
# so the atelier validator enforces the same rule at the source; the
# gate keeps its advisory page-level call via this alias.
from site_modules._base import editability_coverage as _editability_coverage


def _heal_headline_default(module: str, ctx: Dict[str, Any]) -> str:
    if module == "hero":
        b = (ctx.get("bundle") or {}).get("business") or {}
        return (str(b.get("tagline") or "").strip()
                or (ctx.get("business") or {}).get("name") or "Welcome")
    return _stock_headline(module, ctx)


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

    # (g2) Arc M — slop-lint pack (report-only; the field study's finding
    # is that explicit ban-lists shift LLM output while adjectives don't,
    # so the same bans live in prompts AND get verified here on the
    # rendered page).
    # g2a: the emitted DISPLAY face must not be a generic tell
    # (Montserrat/Open Sans/Roboto/... as heading = the #1 AI-generated
    # marker). Owner-locked kits legitimately fail this check — the
    # detail says so rather than hiding it.
    m_face = re.search(r"--sx-font-heading:\s*'([^']+)'", html)
    _face = m_face.group(1) if m_face else ""
    _face_generic = brand_dna.is_generic_display(_face)
    checks.append({
        "name": "display_font_not_generic", "ok": not _face_generic,
        "detail": (f"heading face '{_face}' is a generic-display tell "
                   f"(acceptable ONLY if the owner locked it)" if _face_generic
                   else f"heading face '{_face or 'unknown'}' passes")})
    # g2b: vague-aspirational headline grammar (banned openers +
    # abstract-two-noun clichés). Regexes from the published slop
    # checklists; the atelier/DRO voice rules should make this never
    # fire — this catches regressions.
    _slop_re = re.compile(
        r"^(?:empower|unlock|transform|elevate|discover|revolutioniz)"
        r"|seamless(?:ly)?\b|world-class|cutting-edge|next-level"
        r"|welcome to our website", re.IGNORECASE)
    _sloppy: List[str] = []
    for hm in re.finditer(r"<h[12][^>]*>([\s\S]*?)</h[12]>", html):
        txt = _visible_text(hm.group(1))
        if txt and _slop_re.search(txt.strip()):
            _sloppy.append(txt.strip()[:60])
    checks.append({
        "name": "headline_slop_grammar", "ok": not _sloppy,
        "detail": (f"vague-marketing headline(s): {_sloppy}" if _sloppy
                   else "no banned headline grammar")})
    # g2c: dressed silence (report-only) — every quiet seam must carry
    # its ghost occupant; a bare hairline band on a solid ground reads
    # as "the creative part forgot to create something" (Kevin,
    # 2026-07-10). Ghost words come from the ceremony's tone words, so
    # a bare silence means the feed broke, not that quiet was chosen.
    _n_sil = html.count('sxm-int-silence"')
    _n_ghost = html.count("sxm-int-ghostword")
    checks.append({
        "name": "silences_dressed",
        "ok": _n_sil == 0 or _n_ghost >= _n_sil,
        "detail": (f"{_n_sil} silence seam(s) but only {_n_ghost} ghost "
                   f"occupant(s) — bare silence reads as a forgotten gap"
                   if _n_sil and _n_ghost < _n_sil
                   else f"{_n_sil} silence seam(s), every one carries its occupant")})

    # g2e: CTA LINK COHERENCE (Kevin's ruling, 2026-07-10) — creative
    # button copy is welcome, but a button that TALKS like contact must
    # not route to booking, and a booking-worded button must not
    # dead-end at #contact. Covers module AND atelier CTAs (both emit
    # class sxm-cta) plus offering Book buttons.
    from site_modules._base import _cta_label_intent
    # F4 (2026-07-18): a booking-worded button pointing at #contact is a
    # mismatch only when booking ACTUALLY exists — with no booking
    # connected, the contact form IS the booking path (the cta_button
    # ladder falls to it by design), and flagging it just punishes
    # businesses that haven't connected a scheduler yet.
    _bk = ctx.get("booking") or {}
    _booking_available = bool(_bk.get("enabled") and _bk.get("url"))
    _cta_mismatch: List[str] = []
    for am in re.finditer(
            r'<a[^>]*class="[^"]*(?:sxm-cta|sxm-off-book)[^"]*"[^>]*'
            r'href="([^"]+)"[^>]*>([\s\S]*?)</a>', html):
        _href, _label = am.group(1), _visible_text(am.group(2))
        _intent = _cta_label_intent(_label)
        _to_booking = ("/book" in _href or "/public/booking/" in _href)
        if _intent == "contact" and _to_booking:
            _cta_mismatch.append(f'"{_label[:40]}" → booking page')
        elif (_intent == "booking" and _href.startswith("#contact")
              and _booking_available):
            _cta_mismatch.append(f'"{_label[:40]}" → #contact')
    checks.append({
        "name": "cta_link_coherence",
        "ok": not _cta_mismatch,
        "detail": (f"label/destination mismatch: {_cta_mismatch}"
                   if _cta_mismatch
                   else "every CTA's destination matches its label's intent")})

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
    # B1 (2026-07-18): the DRO's palette.temperature now nudges the neutral
    # ground family itself (was: image grade only). Owner direction still
    # beats it via apply_owner_ground below, same precedence as palette.base.
    ctx["dna"] = brand_dna.apply_dro_temperature(
        ctx["dna"], (decisions.get("palette") or {}).get("temperature"))
    # Quality pass (2026-07-03): the rest of the DRO reaches the
    # pixels too — typography personality, whitespace/density,
    # motion temperature. Practitioner-pinned fonts stay supreme.
    _design_cfg = ((ctx.get("bundle") or {}).get("design") or {})
    _expr = (_design_cfg.get("creative_expression") or {})
    # Arc M (2026-07-10) — THE typography bug: brand_engine._compose_design
    # ALWAYS fills font_heading (kit value or DEFAULT_DESIGN fallback), so
    # the old truthiness test made _fonts_pinned permanently True and the
    # 11-pairing type system (Arc 3) never ran on ANY compose — every site
    # shipped in its brand-kit default faces (the live page's
    # Montserrat/Open Sans). A pin now requires OWNER INTENT:
    #   1. the kit actually stores fonts (fonts_owner_set), AND
    #   2. the heading face isn't a generic-display tell — unless the kit
    #      says fonts_locked (the explicit "yes, I really want Montserrat"
    #      escape hatch). Generic faces in kits are seeded defaults far
    #      more often than choices, and they're the field study's #1
    #      AI-slop marker.
    # An explicit hero_font creative expression still pins, as before.
    _owner_fonts = bool(_design_cfg.get("fonts_owner_set"))
    _heading_face = str(_design_cfg.get("font_heading") or "")
    if (_owner_fonts and not _design_cfg.get("fonts_locked")
            and brand_dna.is_generic_display(_heading_face)):
        logger.info(
            f"[composer] generic display face '{_heading_face}' demoted for "
            f"{business_id[:8]} — type director takes over (brand kit "
            f"fonts_locked=true keeps it)")
        _owner_fonts = False
    # Design audit P2 — the HYBRID font contract (Kevin's ruling):
    #   • type_personality="brand_fonts" is an EXPLICIT pin — it
    #     beats the generic-face demotion (no more silent overrides
    #     of a choice the practitioner actually made).
    #   • any other type_personality constrains the pairing FAMILY;
    #     the DRO still applies taste within it.
    _tp = str(((ctx.get("site_prefs") or {}).get("type_personality")) or "").strip().lower()
    if _tp == "brand_fonts" and _design_cfg.get("fonts_owner_set"):
        _owner_fonts = True
    _owner_pairings = brand_dna.TYPE_PERSONALITY_PAIRINGS.get(_tp)
    # ANTON TRACE (2026-07-22): creative_expression.hero_font — an old
    # brand-engine artifact — counted as a permanent pin, silently
    # blocking every pairing override on every rebuild regardless of the
    # interview ("the design never changes"). A pin now requires the
    # owner's EXPLICIT brand-fonts choice; a stored hero_font is just the
    # starting default the DRO's taste may dress.
    _fonts_pinned = _owner_fonts
    # Vocabulary decoupling (2026-07-21): the design vocabulary is
    # direction evidence that survives a thin DRO — Sovereign Authority
    # keeps its refined chroma/type guards even when the rationale is
    # starved.
    _site_cfg_v = (((ctx.get("site") or {}).get("site_config") or {})
                   if isinstance(((ctx.get("site") or {}).get("site_config")
                                  or {}), dict) else {})
    _vocab_evidence = " ".join(str(v or "") for v in (
        _site_cfg_v.get("vocabulary_override"),
        (_site_cfg_v.get("build_inputs") or {}).get("vocab_id")
        if isinstance(_site_cfg_v.get("build_inputs"), dict) else "",
    ))
    ctx["dna"] = brand_dna.apply_dro_style(
        ctx["dna"], decisions, owner_pairings=_owner_pairings,
        fonts_pinned=_fonts_pinned,
        extra_direction_evidence=_vocab_evidence)
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


# Everything a restore must swap alongside html_content — the page and
# its self-description travel together (spec, bespoke fragments, the
# rationale pointer, concept fingerprint, gate report).
_RESTORE_KEYS = ("page_spec", "atelier", "design_rationale_id", "dro_status",
                 "dro_summary", "dro_failure", "slot_concept",
                 "quality_report", "generated_html", "html_generated_at",
                 # Canvas Pass: the keep-better restore must reinstate the
                 # canvas document + report with everything else.
                 "canvas", "canvas_report")


def restore_previous_compose(business_id: str) -> Dict[str, Any]:
    """Swap the live page with the previous_compose slot (a full
    recompose banks exactly one). The swap is SYMMETRIC — the page you
    were on lands in the slot, so restoring twice returns you to where
    you started. No LLM calls, no cost, instant."""
    from datetime import datetime, timezone
    rows = sb_clients.sb_get_as_service(
        f"/business_sites?business_id=eq.{business_id}"
        "&select=id,site_config,html_content&limit=1") or []
    if not rows:
        return {"ok": False, "error": "no site found for this business"}
    site = rows[0]
    cfg = dict(site.get("site_config") or {})
    prev = cfg.get("previous_compose")
    if not isinstance(prev, dict) or not str(prev.get("html_content") or "").strip():
        return {"ok": False,
                "error": ("no previous design banked yet — the restore slot "
                          "fills automatically on the next full recompose")}
    cur_snapshot = {
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "html_content": site.get("html_content") or "",
        "keys": {k: cfg.get(k) for k in _RESTORE_KEYS if k in cfg},
    }
    for k in _RESTORE_KEYS:
        cfg.pop(k, None)
    for k, v in (prev.get("keys") or {}).items():
        if k in _RESTORE_KEYS:
            cfg[k] = v
    cfg["previous_compose"] = cur_snapshot
    sb_clients.sb_patch_as_service(
        f"/business_sites?id=eq.{site['id']}",
        {"html_content": prev.get("html_content"), "site_config": cfg,
         "status": "published"})
    logger.info(f"[composer] restore-previous swap for {business_id[:8]} "
                f"(banked page from {prev.get('saved_at')})")
    return {"ok": True, "restored_from": prev.get("saved_at"),
            "note": "swap is symmetric — restore again to switch back"}


class _SkipJudge(Exception):
    """Cost diet: cheap re-renders skip the vision pass entirely (the
    stored verdict stays; caught by the vision block's generic guard)."""


def _quality_regen_enabled() -> bool:
    """COST DIET (2026-07-22): the bounded quality regen re-runs the
    ENTIRE build (atelier + judge included) on a gate fail — doubling
    the spend automatically. Default OFF; QUALITY_REGEN=on re-arms it."""
    return (os.environ.get("QUALITY_REGEN") or "off").strip().lower() in (
        "on", "1", "true")


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
                       _atelier: Optional[Dict[str, Any]] = None,
                       _regen_allowed: bool = False,
                       _regen_attempted: bool = False,
                       _regen_notes: str = "",
                       _prior_verdict: Optional[Dict[str, Any]] = None,
                       _canvas_html: Optional[str] = None,
                       _canvas_report: Optional[Dict[str, Any]] = None
                       ) -> Dict[str, Any]:
    # Arc 4: `full_recompose` is True ONLY from compose_site (a fresh
    # spec) — it triggers override reconciliation. Shuffle/refresh/
    # override-triggered re-renders keep it False so a practitioner's
    # edits are never staled by a re-render of the SAME composition.
    # `defaulted_modules` feeds the gate's symmetry-honored check;
    # _heal_attempted/_recon are internal recursion state for the single
    # self-heal pass.
    # A2 (2026-07-18): _regen_allowed marks compose_site's FIRST pass
    # (a failing vision verdict defers the SHIP_GATE=enforce raise to
    # compose_site's bounded regen instead of raising here);
    # _regen_attempted marks the SECOND pass (regen notes ride into the
    # atelier, enforce raises again, and _prior_verdict is persisted
    # alongside the new verdict so both grades survive).
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

    # Canvas Pass (Phase 1, docs/CANVAS_PASS.md §3.5): a canvas-composed
    # page arrives fully assembled (immutable blocks + authored chunks,
    # fact-checked) and JOINS the flow here, at slot population —
    # render_page/run_atelier are skipped, everything downstream (slot
    # populate, overrides, quality gate, invariants, vision grader,
    # persist) is today's flow, untouched. Non-full re-renders
    # (shuffle/refresh/override saves) reuse the stored canvas document
    # instead of re-authoring (spec §8 — the same stored semantics as
    # atelier fragments).
    if _canvas_html is None and not full_recompose:
        _stored_canvas = (((site or {}).get("site_config") or {}).get("canvas")
                          if isinstance(((site or {}).get("site_config") or {})
                                        .get("canvas"), dict) else {})
        if str((_stored_canvas or {}).get("html") or "").strip():
            _canvas_html = str(_stored_canvas["html"])
            logger.info(f"[composer] canvas reused (stored document) for "
                        f"{business_id[:8]}")

    atelier_active = False
    atelier_meta: Optional[Dict[str, Any]] = None
    if _canvas_html:
        html = _mark(_canvas_html)
        # AUDIT FIX (2026-07-24): canvas/v2 documents bypass page_shell,
        # which is the ONLY place the Studio select-to-talk bridge was
        # emitted — so every v2 page shipped with Edit Mode's tap-to-
        # select dead. Inject the platform bridge here when the document
        # doesn't already carry one. Inert on the public site (the
        # script exits unless framed with ?studio=).
        # BRIDGE UPGRADE (2026-07-25): the bridge is BAKED at persist,
        # so a page carrying an older generation would never gain new
        # powers — the "studio-select present → skip" check froze
        # Kevin's page on the select-only script and Edit Mode looked
        # dead. Detect the CURRENT generation instead, strip any older
        # bridge first (both generations share the same opening
        # signature), then inject fresh. Idempotent.
        if "studio-edit-mode" not in html and "</body>" in html:
            try:
                from site_modules._base import STUDIO_BRIDGE as _sx_bridge
                html = re.sub(
                    r"<script>\(function \(\) \{\s*"
                    r"if \(window\.parent === window\) return;.*?</script>",
                    "", html, flags=re.DOTALL)
                html = html.replace("</body>", _sx_bridge + "\n</body>", 1)
            except Exception as _sb_e:
                logger.warning(f"[composer] studio bridge injection "
                               f"skipped (non-fatal): {_sb_e}")
    else:
        try:
            import atelier as _atelier_mod
            atelier_active = _atelier_mod.atelier_enabled() and bool(
                (full_recompose and dro)
                or (_atelier or {}).get("fragments")
                or (not full_recompose and (_stored_atelier.get("fragments") or {})))
        except Exception as e:
            logger.warning(f"[composer] atelier unavailable (non-fatal): {e}")

        # DESIGN LANGUAGES (2026-07-22): the brain's pick (DRO `language`
        # block, rubric fallback) resolves ONCE here, before render — the
        # renderer applies the language's CSS floor + body class, and the
        # atelier/AD prompts receive its brief. Fail-open throughout.
        # Per-build seed (2026-07-23, Kevin: "menu still the same"): the
        # rotation seeds (menu architecture, gallery shape, AD cache)
        # read ctx["design_rationale_id"] — which was persisted to the
        # config but never placed on ctx, so every rotation collapsed to
        # the business-id constant. One line ends the sameness.
        if dro_id:
            ctx["design_rationale_id"] = dro_id
        try:
            import design_languages as _dl
            _lk, _lwhy, _lby = _dl.resolve(ctx, dro)
            if _lk:
                ctx["language_key"] = _lk
                ctx["language_because"] = _lwhy
                logger.info(f"[languages] {business_id[:8]} → {_lk} "
                            f"(by {_lby}): {_lwhy[:120]}")
        except Exception:
            pass

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
                    progress_cb=progress_cb,
                    # A2 — the bounded quality regen's grader notes ride into
                    # every bespoke fragment prompt (empty on normal passes).
                    feedback=_regen_notes)
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
    # the stale list rides GET /composer/composition so a future UI can offer
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
            # AUDIT FIX (2026-07-24): color overrides had NO
            # reconciliation at all — tweaks made against the OLD
            # design repainted every NEW design (!important, every
            # render, and v2's positional keys collide across
            # designs). A full recompose is a redesign: every stored
            # color tweak was made against a page that no longer
            # exists, so ALL of them go stale here. The practitioner
            # re-tints the new design if they want to — Edit Mode
            # writes fresh active rows.
            try:
                from agents.override_system.override_storage import (
                    list_overrides, mark_overrides_status)
                _crows = list_overrides(business_id, "color_role") or []
                _cids = [r.get("id") for r in _crows
                         if r.get("id")
                         and str(r.get("status") or "active") != "stale"]
                if _cids:
                    mark_overrides_status(_cids, "stale")
                    logger.warning(
                        f"[composer] recompose staled {len(_cids)} color "
                        f"override(s) for {business_id[:8]} — a redesign "
                        f"invalidates old-design color tweaks")
            except Exception as _ce:
                logger.warning(f"[composer] color-override reconciliation "
                               f"failed (non-fatal): {_ce}")
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
    # THE SPEC TOKEN BRIDGE (2026-07-24, "old design living inside"):
    # an approved spec names its palette/fonts, but the page's tokens
    # came from the stored brand DNA — the spec's look physically could
    # not reach the page, and every canvas fallback re-dressed the site
    # in the old regime (Anton + old accent + sig-underline). The spec's
    # declared --sx-* roles now override the tokens LAST on EVERY path,
    # so the approved look survives even a fallback build.
    try:
        # AUDIT FIX (2026-07-24): the bridge exists to rescue MODULE
        # pages whose tokens fossilized from old brand DNA. A builder-v2
        # document was authored FROM the spec — its colors/fonts already
        # ARE the spec — so re-injecting a late-cascade :root block +
        # a foreign Google-fonts link into its finished head is pure
        # risk (it can silently re-skin any --sx-* the author bound).
        # v2 documents are identified by their v2/ override namespace.
        _is_v2_doc = 'data-override-target="v2/' in final_html \
            or "data-override-target='v2/" in final_html
        if _is_v2_doc:
            logger.info(f"[composer] spec token bridge skipped for "
                        f"{business_id[:8]} — builder-v2 document is "
                        f"already spec-authored")
        else:
            import spec_author as _sa_over
            _spec_txt = (ctx.get("design_spec_text") or "").strip()
            if not _spec_txt:
                # Re-render paths (shuffle/refresh/override saves) bypass
                # compose_site — load the approved spec here so a re-render
                # never strips the approved look back to the old tokens.
                _spec_txt = _sa_over.approved_spec_text(business_id)
            if _spec_txt:
                final_html = _sa_over.apply_spec_overrides(final_html, _spec_txt)
                logger.info(f"[composer] spec token bridge applied for "
                            f"{business_id[:8]}")
    except Exception as _so_e:
        logger.warning(f"[composer] spec token bridge skipped: {_so_e}")

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
        # Canvas Pass: the heal re-render rebuilds from the SPEC (module
        # path), which would destroy a canvas-authored page — the canvas
        # already ran its own fact-check + corrective retry upstream, so
        # the gate stays report-only on canvas pages.
        if not quality_report["passed"] and fixes and not _heal_attempted \
                and not _canvas_html:
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

    # A1 (2026-07-18) — DESIGN INVARIANTS ON THE LIVE PATH. MOTIF-1 /
    # RHYTHM-1 / CONTRAST-1 used to run only inside the retired Director
    # build loop, which the default endpoint reroutes around — they were
    # dead code on every real build. They run HERE now, on the final
    # document: findings persist into the quality report and (on full
    # recomposes) feed compose_site's bounded quality regen. Severity
    # stays advisory unless DESIGN_INVARIANTS=enforce.
    try:
        from design_invariants import check_design_invariants as _cdi
        _inv_css = "\n".join(re.findall(r"<style[^>]*>(.*?)</style>",
                                        final_html, re.DOTALL | re.IGNORECASE))
        _inv_findings = _cdi(final_html, _inv_css,
                             {"site_prefs": ctx.get("site_prefs") or {},
                              # Canvas Pass §10.3 — IMAGERY-1 needs to know
                              # whether the business HAS gallery photos.
                              "gallery": ctx.get("gallery") or []})
        if isinstance(quality_report, dict):
            quality_report["design_invariants"] = _inv_findings
        if _inv_findings:
            logger.info(f"[composer] design invariants for {business_id[:8]}: "
                        + "; ".join(f"{f['rule_id']} ({f['severity']})"
                                    for f in _inv_findings))
    except Exception as _inv_err:
        logger.warning(f"[composer] design invariants skipped (non-fatal): "
                       f"{type(_inv_err).__name__}: {_inv_err}")

    # Persist: html_content serves live; site_config carries the spec.
    fresh = sb_clients.sb_get_as_service(
        f"/business_sites?id=eq.{site['id']}&select=site_config,html_content&limit=1") or []
    cfg = dict((fresh[0].get("site_config") or {}) if fresh else {})
    from datetime import datetime, timezone
    # Compose safety net (2026-07-10, Kevin's bad roll): a full recompose
    # used to OVERWRITE the only copy of a page the owner may have loved
    # — and the variance machinery deliberately rolls each compose away
    # from the last, so a worse roll destroyed a better one with no way
    # back. One restore slot: the outgoing page + its restore-critical
    # config, swapped back by restore_previous_compose(). Never nests
    # (previous_compose is not in _RESTORE_KEYS).
    if full_recompose:
        _out_html = ((fresh[0].get("html_content") if fresh else "") or "")
        if _out_html.strip():
            cfg["previous_compose"] = {
                "saved_at": datetime.now(timezone.utc).isoformat(),
                "html_content": _out_html,
                "keys": {k: cfg.get(k) for k in _RESTORE_KEYS if k in cfg},
            }
    # ── Design-quality audit fix R2 (2026-07-18): the vision grader /
    # ship gate / invention verification were wired into the legacy
    # run_build_loop path, which the default endpoint reroutes AROUND —
    # they never ran. They live HERE now, on the path every real build
    # takes. Verdict recorded on every compose; SHIP_GATE=enforce turns
    # a failing verdict into a raised error; default observe-only.
    _verdict: Optional[Dict[str, Any]] = None
    # COST DIET (2026-07-22): the judge runs ONCE per user action — on
    # full recomposes (and the explicit regen pass). Shuffles, refreshes,
    # override re-renders and self-heal intermediates keep the stored
    # verdict instead of paying for 3 screenshots + a vision call each.
    _should_judge = bool(full_recompose or _regen_attempted)
    try:
        import vision_grader as _vg
        from design_register import get_invention_count as _gic
        if not _should_judge:
            raise _SkipJudge()
        # Arc D (2026-07-21): the judge grades against the direction's
        # authored reference standard, never in a vacuum.
        try:
            from reference_standards import standard_for as _std_for
            from reference_standards import standard_key_for as _std_key_for
            _ref_standard = _std_for(ctx)
            _ref_standard_key = _std_key_for(ctx)
            # LANGUAGE↔STANDARD COHERENCE (2026-07-23, live rejection):
            # the judge graded a MURAL build against the refined_luxury
            # bar ("against Aman, Mont Blanc…") because the standard
            # classifier and the language selector chose independently.
            # A build is judged by the bar of the language it SPEAKS.
            _lk = str(ctx.get("language_key") or "")
            if _lk:
                import design_languages as _dl_std
                from reference_standards import STANDARDS as _STDS
                _std_key = _dl_std.LANGUAGES.get(_lk, {}).get("standard")
                if _std_key and _std_key in _STDS:
                    _ref_standard = _STDS[_std_key]
                    _ref_standard_key = _std_key
            # SPEC-AS-BAR (2026-07-24, v2 flight one): when an OWNER-
            # APPROVED spec governs the page, the spec IS the bar. The
            # first v2 build was dinged for a "solid fill pill" CTA the
            # approved spec explicitly ordered — a generic direction
            # standard must never outrank the document the owner signed.
            # The judge grades craft AND fidelity to the spec.
            _spec_bar = (ctx.get("design_spec_text") or "").strip()
            if _spec_bar:
                _ref_standard = (
                    "THE OWNER-APPROVED SPEC governs this page — it is "
                    "the bar. Grade CRAFT (execution quality) and "
                    "FIDELITY (does the page deliver what this document "
                    "orders — its named move, its palette roles, its "
                    "section intents). Never penalize a choice the spec "
                    "explicitly makes.\n--- THE SPEC (excerpt) ---\n"
                    + _spec_bar[:2000])
                _ref_standard_key = "approved-spec"
        except Exception:
            _ref_standard = None
            _ref_standard_key = None
        _verdict = _vg.grade(final_html, business_id, standard=_ref_standard,
                             standard_key=_ref_standard_key)
        if _verdict is None:
            # Acceptance-run finding: leaving the PREVIOUS build's verdict
            # in site_config misattributes it to this compose (the forced-
            # fallback run "inherited" the prior run's scores verbatim).
            # No verdict for THIS build -> no verdict stored.
            cfg.pop("vision_verdict", None)
        else:
            cfg["vision_verdict"] = _verdict
            # A shipped build (pass, or observe-mode fail) supersedes any
            # stored rejection banner.
            cfg.pop("vision_rejection", None)
            if _prior_verdict:
                # A2 — the bounded regen's FIRST-pass grade, persisted
                # alongside the new one so both survive (before/after).
                cfg["vision_verdict_prior"] = _prior_verdict
            # NO-DOWNGRADE FOR ALL (2026-07-24): the ratchet used to
            # fire only on below-bar builds — a PASSING build worse
            # than the live site skipped the comparison entirely and
            # replaced it (the live 30→19 downgrade). Every build now
            # answers to the live score, passing or not.
            if True:  # every verdict answers the ratchet — see above
                logger.info(
                    f"[ship-gate] verdict for {business_id}: "
                    f"passes={_verdict.get('passes_gate')} "
                    f"impact={_verdict.get('first_viewport_impact')} "
                    f"smell={_verdict.get('template_smell')} "
                    f"broken={_verdict.get('broken')}")
                # A2: on compose_site's first pass the enforce raise
                # DEFERS to the bounded quality regen (it owns the final
                # verdict); everywhere else the raise fires exactly as
                # before. The regen pass itself raises on a repeat fail.
                #
                # THE RATCHET (2026-07-21, after two paid-for-nothing
                # rejections): the gate now blocks only REGRESSIONS. A
                # below-bar build still ships when it beats the verdict
                # of the site that's currently live (or when the live
                # site has no verdict to defend) — practitioners always
                # get their money's worth of progress; the gate's job is
                # "never downgrade", not "perfection or nothing".
                _live_verdict = (((site or {}).get("site_config") or {})
                                 .get("vision_verdict")
                                 if isinstance(((site or {}).get("site_config")
                                                or {}), dict) else None)
                # ── RATCHET v2 (2026-07-22, the frozen-site fix). Two
                # deadlocks found on a real business:
                #  • ERA MISMATCH: a live verdict graded under an older
                #    rubric defends the live site with a score today's
                #    judge would never award (a stale 28 vs a fresh 6 =
                #    the old site is immortal). Verdicts now carry a
                #    rubric stamp; a live verdict from another era gets
                #    the live page RE-GRADED under today's standard
                #    before it may defend — and if the re-grade is
                #    unavailable, the stale score defends nothing.
                #  • JUDGE NOISE: composites jitter a few points between
                #    runs; `<=` blocked every rebuild landing within a
                #    point of the live score, freezing the site ("same
                #    everything keeps being made"). A regression now
                #    means MEANINGFULLY worse: new < live − margin
                #    (SHIP_GATE_MARGIN, default 2). Ties + noise ship.
                # SAME-BAR RULE (2026-07-23, the paid-for-nothing loop):
                # composites are only comparable when both verdicts were
                # earned under the same rubric AND the same reference
                # standard. Tonight's builds spoke Mural and were judged
                # against the bold_statement bar ("a Nike campaign
                # page") while the live verdict's 25 was earned on a
                # softer default bar — an unwinnable fight the ratchet
                # treated as a regression, burning a build fee each try.
                # A live verdict from another rubric era OR another bar
                # gets the live page re-graded under the CANDIDATE's
                # rubric + standard before it may defend.
                if (_live_verdict is not None
                        and (_live_verdict.get("rubric")
                             != getattr(_vg, "RUBRIC_VERSION", None)
                             or _live_verdict.get("standard_key")
                             != (_ref_standard_key or "default"))):
                    try:
                        _live_html = str(((site or {}).get("site_config")
                                          or {}).get("generated_html") or "")
                        _live_verdict = (_vg.grade(
                                            _live_html, business_id,
                                            standard=_ref_standard,
                                            standard_key=_ref_standard_key)
                                         if _live_html.strip() else None)
                        logger.info(
                            f"[ship-gate] live verdict was stale-era or "
                            f"other-bar — re-graded under current rubric "
                            f"+ candidate's standard: "
                            f"{_vg.verdict_composite(_live_verdict)}")
                    except Exception as _era_e:
                        logger.warning(
                            f"[ship-gate] live re-grade failed ({_era_e}) "
                            f"— stale verdict defends nothing")
                        _live_verdict = None
                try:
                    _margin = int(os.getenv("SHIP_GATE_MARGIN", "2") or 2)
                except (TypeError, ValueError):
                    _margin = 2
                _is_regression = (
                    _live_verdict is not None
                    and _vg.verdict_composite(_verdict)
                    < _vg.verdict_composite(_live_verdict) - _margin)
                if not _is_regression and not _verdict.get("passes_gate"):
                    logger.info(
                        f"[ship-gate] below-bar build ships by ratchet for "
                        f"{business_id}: new composite "
                        f"{_vg.verdict_composite(_verdict)} vs live "
                        f"{_vg.verdict_composite(_live_verdict)}")
                if _vg.gate_enforced() and _is_regression \
                        and (not _regen_allowed or _regen_attempted):
                    # Verdict visibility (2026-07-21, the silent-rejection
                    # gap): the FIRST enforced rebuild blocked correctly
                    # but the editor showed NOTHING — the button appeared
                    # to do nothing. Before raising, best-effort persist
                    # the rejection onto the EXISTING site_config (old
                    # html untouched) so the frontend can show the
                    # judge's scores + notes and a practitioner knows the
                    # gate held the line, not that the build vanished.
                    try:
                        from datetime import datetime as _dt, timezone as _tz
                        _rej_rows = sb_clients.sb_get_as_service(
                            f"/business_sites?business_id=eq.{business_id}"
                            "&select=id,site_config&limit=1") or []
                        if _rej_rows:
                            _rej_cfg = dict(_rej_rows[0].get("site_config") or {})
                            _rej_cfg["vision_rejection"] = {
                                "at": _dt.now(_tz.utc).isoformat(),
                                "verdict": _verdict,
                                # The practitioner PAID for this build —
                                # keep the candidate so a rejection isn't
                                # a total loss (inspectable, and a future
                                # "ship it anyway" needs no rebuild).
                                "candidate_html": final_html,
                                # v2 flight one: the engine report died
                                # with the rejection — persist it here so
                                # a rejected build is diagnosable (which
                                # engine, armor log, repair, fallbacks).
                                "engine_report": _canvas_report,
                            }
                            sb_clients.sb_patch_as_service(
                                f"/business_sites?id=eq.{_rej_rows[0]['id']}",
                                {"site_config": _rej_cfg})
                    except Exception as _rej_e:
                        logger.warning(f"[ship-gate] rejection persist "
                                       f"failed: {_rej_e}")
                    raise RuntimeError("ship-gate: vision verdict failed and "
                                       "SHIP_GATE=enforce is set")
        _inv = _gic(business_id)
        if _inv is None:
            cfg.pop("invention_count", None)  # same staleness rule as the verdict
        else:
            cfg["invention_count"] = _inv
            if _inv < 3:
                logger.warning(f"[ship-gate] inventions below spec for "
                               f"{business_id}: {_inv} < 3 (doctrine D12)")
        # A4 — verify the inventions, don't just count them (spec §3-D:
        # a restated brief line is a judge failure). Report + persist;
        # a hard fail joins compose_site's bounded-regen trigger.
        _inv_verification = _verify_inventions(business_id, ctx)
        if _inv_verification.get("ok") is not None:
            cfg["invention_verification"] = _inv_verification
            if isinstance(quality_report, dict):
                quality_report["invention_verification"] = _inv_verification
            if _inv_verification.get("ok") is False:
                logger.warning(
                    f"[ship-gate] invention verification FAILED for "
                    f"{business_id}: count={_inv_verification.get('count')} "
                    f"restatements="
                    f"{len(_inv_verification.get('restatements') or [])}")
    except RuntimeError:
        raise
    except Exception as _vg_err:
        logger.warning(f"[ship-gate] vision pass skipped: "
                       f"{type(_vg_err).__name__}: {_vg_err}")

    cfg.update({
        "page_spec": {"sections": spec},
        "generated_html": final_html,
        "html_source": "module-composer",
        "html_generated_at": datetime.now(timezone.utc).isoformat(),
        "use_smart_sites": False,
        "quality_report": quality_report,   # Arc 4 — surfaced on /composer/composition
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
    # Canvas Pass (Phase 1): persist the assembled (pre-slot) canvas
    # document + the fact-check report alongside quality_report (§7).
    # Shuffle/refresh/override re-renders reuse the document without an
    # LLM call; a full recompose WITHOUT the canvas clears both (a stale
    # canvas must never mask a fresh module compose — the atelier rule).
    if _canvas_html:
        cfg["canvas"] = {"html": _canvas_html,
                         "generated_at": datetime.now(timezone.utc).isoformat()}
        cfg["html_source"] = "canvas"
    elif full_recompose:
        cfg.pop("canvas", None)
    # The report persists even on a FALLBACK (no canvas html) — the
    # fallback forensics are exactly what a diagnosis needs; a silent
    # "(none)" cost a live build's postmortem once already (2026-07-21).
    if _canvas_report:
        cfg["canvas_report"] = _canvas_report
    elif full_recompose:
        cfg.pop("canvas_report", None)
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
    # RESIDUE PURGE (2026-07-22, Kevin's live report: "so much residue of
    # past designs"): a FULL recompose sweeps the dead Director-era
    # artifacts out of site_config — they are read only by the legacy
    # /director path and confuse every forensic read. Live-path keys
    # (vocabulary_override, previous_compose, build_inputs) stay.
    #
    # ⚠ NEVER add a key to this tuple that THIS function writes. The
    # original list swept `page_spec` and `slot_concept`, which are
    # written ~60 lines above (page_spec at the cfg.update, slot_concept
    # just below it) — so every full recompose wrote them and then
    # deleted them before the PATCH. That cost us three live behaviours
    # for eleven days (audit 2026-08-01):
    #   • /composer/shuffle always 409'd "no composed page yet"
    #   • refresh_if_composed never fired → catalog/gallery edits stopped
    #     reaching the site
    #   • stored_concept_fp was always "" → reroll_defaults was always
    #     True → default slot imagery re-rolled on EVERY build, burning
    #     Unsplash/DALL-E budget the Arc 7 fingerprint exists to save,
    #     and changing photos the practitioner never asked to change
    # Both are also in _RESTORE_KEYS, so restore could never bring them
    # back either. Purge only what nothing writes anymore.
    if full_recompose:
        for _dead in ("design_brief", "design_recommendation",
                      "enriched_brief", "generated_decoration",
                      "html_build_error",
                      "html_build_failed_at", "html_validation_errors",
                      "dalle_spend_log", "composer_cache", "sections"):
            cfg.pop(_dead, None)
    # Brain-mode telemetry: a minimal-mode DRO is the real "thin" story —
    # surface it so applied_thin is never a mystery again.
    try:
        if isinstance(dro, dict) and (dro.get("meta") or {}).get("authored_minimal"):
            cfg["dro_mode"] = "minimal"
            _ff = (dro.get("meta") or {}).get("full_failure")
            if isinstance(_ff, dict):
                cfg["dro_mode_detail"] = _ff   # WHY the full brain fell back
            else:
                cfg.pop("dro_mode_detail", None)
        else:
            cfg.pop("dro_mode", None)
            cfg.pop("dro_mode_detail", None)
    except Exception:
        pass
    # Design languages + frameworks — persist the skeleton + craft picks
    # with their because (forensics + the future outcome-priors loop).
    if ctx.get("language_key"):
        cfg["language"] = {"key": ctx["language_key"],
                           "because": str(ctx.get("language_because") or "")[:300]}
    elif full_recompose:
        cfg.pop("language", None)
    if ctx.get("framework_key"):
        cfg["framework_key"] = ctx["framework_key"]
    if ctx.get("color_source"):
        cfg["color_source"] = ctx["color_source"]
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
              # A2 — compose_site's bounded regen decides on this; also
              # surfaced to callers (was write-only into site_config).
              "vision_verdict": _verdict,
              "url": f"https://{ctx['business']['slug']}.mysolutionist.app" if ctx["business"]["slug"] else None}
    if overrides_reconciled is not None:
        result["overrides_reconciled"] = {
            "applied": overrides_reconciled.get("applied", 0),
            "stale": overrides_reconciled.get("stale", 0)}
    if atelier_meta and (atelier_meta.get("fragments") or {}):
        result["atelier"] = {"sections": sorted(atelier_meta["fragments"])}
    if _canvas_html:
        result["canvas"] = {
            "fresh": bool(_canvas_report),
            "fact_check_ok": bool(((_canvas_report or {}).get("fact_check")
                                   or {}).get("ok")) if _canvas_report else None,
        }
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
    # Design audit P3 — the owner TYPED these; they always surface.
    _prefs = ctx.get("site_prefs") if isinstance(ctx.get("site_prefs"), dict) else {}
    if _prefs.get("proof_stats") and "statband" not in present:
        additions.append({"module": "statband", "variant": "band", "content": {},
                          "_variant_defaulted": True})
    if _prefs.get("process_steps") and "process" not in present:
        additions.append({"module": "process", "variant": "steps", "content": {},
                          "_variant_defaulted": True})
    # Acceptance-run finding: the owner answered YES to the gallery
    # question and the composer still skipped the section. An explicit
    # yes forces it — with zero photos it renders the designed awaiting
    # frames (#181), which is exactly what the owner opted into.
    if _prefs.get("wants_gallery") is True and "gallery" not in present:
        additions.append({"module": "gallery", "variant": "mosaic", "content": {},
                          "_variant_defaulted": True})
    if not additions:
        return spec
    contact_idx = next((i for i, s in enumerate(spec) if s.get("module") == "contact"), len(spec))
    return spec[:contact_idx] + additions + spec[contact_idx:]


# ─── Arc 5 — reference-site study (the marquee feature) ──────────────

_REFERENCE_BUDGET_S = 20.0     # overall wall-clock budget per compose


def _owner_direction_evidence(ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Interview v3 (B4) — the anti-convergence exemption's evidence bundle
    for author_dro/produce_dro: the stored site_prefs plus the fonts_pinned
    signal (the kit stores owner-set fonts AND the owner locked them — the
    explicit pin; see _apply_dro_design's Arc M logic)."""
    design = (ctx.get("bundle") or {}).get("design")
    design = design if isinstance(design, dict) else {}
    return {"site_prefs": ctx.get("site_prefs"),
            "fonts_pinned": bool(design.get("fonts_owner_set"))
            and bool(design.get("fonts_locked"))}


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


# Arc A (2026-07-21) — design-craft vocabulary that marks a line as the
# designer describing the PAGE rather than the page speaking to a
# visitor. Conservative on purpose: a false positive costs one statement
# bar (a thread renders instead); a false negative prints art direction
# on a public site.
_DESIGN_NOTE_RE = re.compile(
    r"\b(diagonal|gradient|palette|typograph\w*|serif|font\w*|layout|"
    r"motif|white\s?space|hue|saturat\w*|viewport|scroll[\s-]?trigger\w*|"
    r"animation|keyframe|hero\s+(?:section|band|image)|section\s+(?:opens|title)|"
    r"letter[\s-]?spac\w*|small[\s-]?caps|display[\s-]?(?:face|type)|"
    r"accent\s+(?:color|face|word)|color[\s-]?mix|wordmark|eyebrow|"
    r"numeral|margin|padding|css|token)\b",
    re.IGNORECASE)


def _reads_as_design_note(line: str) -> bool:
    """True when a candidate statement line reads as internal design
    language (art direction / craft vocabulary) instead of visitor copy."""
    return bool(_DESIGN_NOTE_RE.search(line))


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
    # Arc A (2026-07-21, THE LEAK): DRO-internal fields (concept_statement /
    # first_impression.remember / tension.expression) are the DESIGNER
    # talking — art direction, not visitor copy. The live defect rendered
    # "A diagonal line of light that starts as a scattered problem…" as a
    # full-width pull-quote on the public page. Internal design language
    # never ships: the statement bar draws ONLY from spec copy fields
    # (owner-facing copy by construction), and every candidate still
    # passes the design-note guard as belt-and-suspenders.
    for mod, field in _STATEMENT_COPY_SOURCES:
        candidates.append(str((by_module.get(mod) or {}).get(field) or ""))

    for raw in candidates:
        v = " ".join(str(raw).split())
        if not (12 <= len(v) <= 200):
            continue
        had_candidates = True
        if _reads_as_design_note(v):
            continue  # craft vocabulary → this is a designer's note
        n = _norm_copy_line(v)
        if any(n in c or c in n for c in corpus):
            continue  # the page already says this line — never repeat it
        return v, True
    return "", had_candidates


def _apply_ceremony_pass(spec: List[Dict[str, Any]], ctx: Dict[str, Any],
                         dro: Optional[Dict[str, Any]],
                         seed: Optional[str] = None) -> List[Dict[str, Any]]:
    """FAIL-SOFT shell (Site Arc 12): seams are an enhancement, never
    fatal — if the ceremony pass raises for any reason, the compose
    proceeds with the un-seamed spec and the error is logged LOUD.
    Previously both call sites (compose_site + _direction_pipeline) ran
    this bare, so a ceremony bug would have killed the whole compose.

    NOTE (B5, 2026-07-18): the DRO gate below is now PARTIAL — a DRO
    fallback drops the statement bar (it needs authored tension) but the
    values marquee still earns its seat from real tone words alone. The
    atelier stays fully DRO-gated (run_atelier's regenerate mode), so
    dro_status=fallback still means no bespoke sections, but no longer
    means a seam-free page when the brand voice is rich."""
    try:
        return _apply_ceremony_pass_inner(spec, ctx, dro, seed=seed)
    except Exception as e:
        logger.error(f"[composer.ceremony] ceremony pass crashed "
                     f"(fail-soft — composing without seams) for "
                     f"{str((ctx.get('business') or {}).get('id') or '')[:8]}: "
                     f"{type(e).__name__}: {e}")
        return spec


def _apply_ceremony_pass_inner(spec: List[Dict[str, Any]],
                               ctx: Dict[str, Any],
                               dro: Optional[Dict[str, Any]],
                               seed: Optional[str] = None
                               ) -> List[Dict[str, Any]]:
    """Insert the ceremony seams. Rules (all deterministic):
      - fewer than 4 sections → no seams (a short page has no chapters to
        pause between);
      - B5 (2026-07-18): a DRO fallback no longer silences ceremony. The
        statement bar needs authored tension (DRO-only), but the values
        marquee needs only real tone words + non-stilled motion — both
        available without a rationale, so it still earns its seat;
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
    if len(spec) < _CEREMONY_MIN_SECTIONS:
        return spec
    d = ((dro or {}).get("decisions") or {})

    seed_src = str(seed or (dro or {}).get("id")
                   or ((d.get("hero_concept") or {}).get("concept_statement"))
                   or (ctx.get("business") or {}).get("id") or "ceremony")
    h = int(hashlib.sha256(seed_src.encode("utf-8")).hexdigest()[:12], 16)

    tn = d.get("tension") if isinstance(d.get("tension"), dict) else {}
    tension_present = bool(tn.get("pole_a") and tn.get("pole_b"))
    statement_line = ""
    if tension_present:
        # (2nd tuple element — "had candidates" — no longer needed now that a
        # duplicated statement just drops its seat rather than becoming a line.)
        statement_line, _ = _ceremony_statement_line(spec, dro)
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
    # (Site quality 2026-07-14) When a statement's candidates all duplicate
    # the page copy, the seat is simply DROPPED — no bare thread line stands
    # in for it.
    if marquee_ok:
        wishes.append({"module": "interstitial", "variant": "marquee",
                       "content": {"words": " • ".join(tone_words)}})
    # Site quality (2026-07-14, Kevin): NO bare-line fillers. A seam appears
    # ONLY when it carries real content — a statement quote or a values
    # marquee. When there's nothing to say, insert NOTHING and let the
    # section spacing (whitespace) do the work, the way a professional site
    # does. The old silence/thread hairlines read as a stray animated line
    # drifting between sections (the exact artifact being removed here).
    if not wishes:
        return spec
    n_want = min(len(wishes), _CEREMONY_MAX)

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


def _load_stored_dro(business_id: str) -> Optional[Dict[str, Any]]:
    """Refine mode's memory: the persisted rationale behind the CURRENT
    page (site_config.design_rationale_id → design_rationales.dro).
    None when the page has no stored rationale."""
    rows = sb_clients.sb_get_as_service(
        f"/business_sites?business_id=eq.{business_id}"
        "&select=site_config&limit=1") or []
    rid = (((rows[0].get("site_config") or {}).get("design_rationale_id"))
           if rows else None)
    if not rid:
        return None
    dr = sb_clients.sb_get_as_service(
        f"/design_rationales?id=eq.{rid}&select=id,dro&limit=1") or []
    if not dr:
        return None
    dro = dict(dr[0].get("dro") or {})
    if not dro.get("decisions"):
        return None
    dro.setdefault("id", dr[0].get("id"))
    return dro


def _regen_feedback(verdict: Optional[Dict[str, Any]],
                    findings: List[Dict[str, Any]]) -> str:
    """A2 — build the feedback text the bounded quality regen injects into
    the copy stage and every atelier fragment: the vision grader's verdict
    (when it failed) plus each design-invariant finding's fix hint."""
    parts: List[str] = []
    if verdict and not verdict.get("passes_gate", True):
        parts.append(
            "The previous render FAILED the vision ship-gate "
            f"(first-viewport impact {verdict.get('first_viewport_impact')}/10, "
            f"template smell {verdict.get('template_smell')}/10, "
            f"broken={verdict.get('broken')}). "
            f"Grader notes: {verdict.get('notes') or '(none)'}")
    for f in (findings or [])[:6]:
        parts.append(f"{f.get('rule_id')}: {f.get('description')} "
                     f"Fix: {f.get('fix_hint')}")
    return "\n".join(parts)[:1200]


# A4 (2026-07-18) — deterministic invention verification. Words that
# carry no design meaning are excluded from the restatement check.
_VERIFY_STOP = frozenset({
    "the", "and", "for", "with", "that", "this", "from", "into", "your",
    "their", "our", "his", "her", "its", "are", "was", "were", "has",
    "have", "had", "not", "but", "all", "any", "each", "per", "via",
    "one", "two", "three", "every", "than", "then", "them", "they",
    "will", "would", "could", "should", "shall", "may", "might", "must",
    "can", "also", "just", "only", "over", "under", "between", "within",
    "across", "while", "when", "where", "what", "which", "who", "whom",
    "whose", "how", "why", "because", "about", "against", "brief",
    "constraint", "builds", "addition", "section", "page",
})


def _content_words(text: str) -> set:
    return {w for w in re.findall(r"[a-z]{4,}", (text or "").lower())
            if w not in _VERIFY_STOP}


def _verify_inventions(business_id: str, ctx: Dict[str, Any]) -> Dict[str, Any]:
    """A4 — the invention check the spec's §3-D calls a judge failure:
    >=3 inventions AND none may merely restate the brief. Deterministic
    grade: an invention restates when >=70% of its content words already
    appear in the owner's stated material (offer / creative brief /
    story / feel words / tagline). ok=None means 'no records to verify'
    — reported, never counted as failure."""
    out: Dict[str, Any] = {"ok": None, "count": None, "restatements": []}
    try:
        from design_register import get_invention_count as _gic, \
            get_invention_texts as _git
        count = _gic(business_id)
        texts = _git(business_id)
        if count is None and texts is None:
            return out
        out["count"] = count
        prefs = ctx.get("site_prefs") if isinstance(ctx.get("site_prefs"), dict) else {}
        creative = prefs.get("creative") if isinstance(prefs.get("creative"), dict) else {}
        story = prefs.get("story") if isinstance(prefs.get("story"), dict) else {}
        tension = creative.get("tension") if isinstance(creative.get("tension"), dict) else {}
        b = (ctx.get("bundle") or {}).get("business") or {}
        stated = " ".join([
            str(prefs.get("offer") or ""),
            " ".join(str(v) for k, v in creative.items()
                     if not isinstance(v, dict)),
            " ".join(str(v) for v in tension.values()),
            " ".join(str(v) for v in story.values()),
            " ".join(str(w) for w in (prefs.get("feel_words") or [])),
            str(prefs.get("notes") or ""),
            str(b.get("tagline") or ""), str(b.get("elevator_pitch") or ""),
        ])
        stated_words = _content_words(stated)
        restatements: List[str] = []
        for item in (texts or []):
            addition = (str(item.get("addition") or "")
                        if isinstance(item, dict) else str(item or ""))
            words = _content_words(addition)
            if not words:
                continue
            if len(words & stated_words) / len(words) >= 0.7:
                restatements.append(addition[:120])
        out["restatements"] = restatements
        out["ok"] = bool((count or 0) >= 3 and not restatements)
    except Exception as e:
        logger.info(f"[composer] invention verification skipped: {e}")
    return out


def compose_site(business_id: str, brief_notes: str = "",
                 use_llm: bool = True,
                 design_prefs: Optional[Dict[str, Any]] = None,
                 progress_cb=None,
                 refine: bool = False) -> Dict[str, Any]:
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
    # CANVAS PROTECTION (2026-07-25, the 05:00 incident): a retired
    # Smart Sites banner's click rerouted into compose_site(use_llm=
    # False) and a SUB-SECOND deterministic module compose silently
    # OVERWROTE a paid one-mind build (judge composite 33), deleting
    # the stored canvas document with it. The rank rule already
    # protects module-composer from smart-sites (_use_smart_sites);
    # the same rule now protects canvas from module-composer: a
    # no-LLM convenience compose NEVER replaces a canvas-authored
    # page. Full LLM rebuilds (the paid path) replace it by design.
    if not use_llm:
        try:
            _rows = sb_clients.sb_get_as_service(
                f"/business_sites?business_id=eq.{business_id}"
                "&select=site_config&limit=1") or []
            _cfg = (_rows[0].get("site_config") or {}) if _rows else {}
            _has_canvas_doc = (
                _cfg.get("html_source") == "canvas"
                or str(((_cfg.get("canvas") or {}) if isinstance(
                    _cfg.get("canvas"), dict) else {}).get("html")
                    or "").strip() != "")
            if _has_canvas_doc:
                logger.warning(
                    f"[composer] CANVAS-PROTECTED: refusing a no-LLM "
                    f"compose over a canvas-authored page for "
                    f"{business_id[:8]} — the live document stands")
                return {"ok": True, "skipped": "canvas-protected",
                        "note": "This site is authored by the one-mind "
                                "builder. A quick compose never replaces "
                                "it; run a full rebuild to redesign."}
        except Exception as _cp_e:
            logger.warning(f"[composer] canvas-protection check failed "
                           f"(continuing): {_cp_e}")

    prefs = sanitize_design_prefs(design_prefs)
    if prefs:
        _persist_site_prefs(business_id, prefs)

    # Arc 10 — progress_cb (chief_jobs loading bar) pings at real stage
    # boundaries with honest labels; None on every non-job path.
    _report_progress(progress_cb, 5, "Reading your business")
    ctx = gather_context(business_id)
    # Director's Cut arc 2 — the practitioner's own words for THIS build
    # (Studio chat → rebuild job params.brief_notes) ride ctx so the
    # canvas brief can lead with them verbatim. brief_notes already
    # steered the section plan; now the author hears them too.
    if (brief_notes or "").strip():
        ctx["owner_brief"] = brief_notes.strip()[:600]
    # Arc 3 — an APPROVED design spec is the law of the page: it leads
    # the canvas brief. Authoring/revision happen via /composer/spec/*
    # for pennies, so only decided designs pay for builds.
    try:
        import spec_author as _sa
        _spec_text = _sa.approved_spec_text(business_id)
        if _spec_text:
            ctx["design_spec_text"] = _spec_text
            logger.info(f"[composer] approved spec leads this build "
                        f"({len(_spec_text)} chars) for {business_id[:8]}")
    except Exception as _spec_e:
        logger.info(f"[composer] spec load skipped: {_spec_e}")
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
    creative = _creative_plus_story(ctx)

    dro_failure: Optional[Dict[str, Any]] = None   # forensics → site_config.dro_failure
    if use_llm:
        # REFINE MODE (2026-07-10, the roulette cure): "polish this
        # direction, don't reinvent." Reloads the stored rationale
        # behind the current page and SKIPS authoring — fonts, palette,
        # concept, and the imagery fingerprint all stay put, while copy
        # and atelier fragments regenerate as fresh takes on the SAME
        # direction (brief_notes still steer the polish). The Arc 7
        # anti-convergence machinery lives inside produce_dro, so a
        # refine is naturally exempt from the forced-difference roll.
        # No stored rationale → falls through to a normal authoring
        # compose (a refine can never fail harder than a redesign).
        if refine:
            _report_progress(progress_cb, 30, "Reloading your design direction")
            dro = _load_stored_dro(business_id)
            if dro:
                dro_id = dro.get("id")
                logger.info(f"[composer] REFINE — reusing stored rationale "
                            f"{str(dro_id)[:8]} for {business_id[:8]}")
            else:
                logger.info(f"[composer] refine requested but no stored "
                            f"rationale for {business_id[:8]} — authoring fresh")
        # 1) Author the rationale from the practitioner's own words.
        if dro is None:
            _report_progress(progress_cb, 30, "Authoring the design brief")
            try:
                from agents.composer.drl.passes import produce_dro
                intake = _assemble_intake_text(ctx)
                dro, dro_failure = produce_dro(
                    business_id, intake, reference_analysis=ref_analysis,
                    creative=creative,
                    owner_direction=_owner_direction_evidence(ctx))
                if dro is None:
                    # One retry — cheap insurance against a transient LLM/parse
                    # hiccup before accepting a rationale-less compose.
                    logger.info(f"[composer] DRO production returned None for "
                                f"{business_id[:8]} — retrying once")
                    dro, dro_failure = produce_dro(
                        business_id, intake, reference_analysis=ref_analysis,
                        creative=creative,
                        owner_direction=_owner_direction_evidence(ctx))
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

    # Gallery guarantee (2026-07-14): a business that uploaded real photos of
    # its products / work / results ALWAYS gets its gallery, even if the LLM's
    # spec omitted it. Inserted before contact so real work always shows.
    if ctx.get("gallery") and not any(s.get("module") == "gallery" for s in spec):
        _gv = "mosaic" if (ctx.get("dna") or {}).get("vibe") == "bold" else "grid"
        _pos = next((i for i, s in enumerate(spec)
                     if s.get("module") == "contact"), len(spec))
        spec.insert(max(1, _pos), {"module": "gallery", "variant": _gv, "content": {}})

    # Site Arc 10 — the ceremony pass: deterministic interstitial seams
    # between the chapters (after sanitize/symmetry, before render;
    # inside the existing 45-55% progress window — no new stage).
    # FRAMEWORKS ARC (2026-07-22): the skeleton decision — one named
    # page architecture governs order, portrait seat, and one-
    # representation-per-content-type (the process×3 fix) — BEFORE the
    # ceremony pass places seams between the final chapters.
    try:
        import page_frameworks
        spec = page_frameworks.apply_framework(spec, ctx, dro)
    except Exception:
        pass
    spec = _apply_ceremony_pass(spec, ctx, dro, seed=dro_id)

    # Multi-page (site_multipage): when the site opts in, give the HOME header
    # its cross-page nav BEFORE it renders (idempotent site-row ensure to
    # learn the slug + read the flag). Additive — single-page is untouched.
    _mp_slug = ""
    try:
        import site_multipage
        _site0 = _ensure_site_row(business_id, ctx)
        _cfg0 = (_site0 or {}).get("site_config") or {}
        if site_multipage.is_multi_page(_cfg0) and (_site0 or {}).get("slug"):
            _mp_slug = _site0["slug"]
            ctx["page_nav"] = site_multipage.build_page_nav(_mp_slug, "home")
    except Exception as _e:
        logger.info(f"[composer] multi-page home-nav skipped: {_e}")

    # ── Canvas Pass (Phase 1, docs/CANVAS_PASS.md) ─────────────────────
    # Gated on SITE_CANVAS=on + full recompose + a DRO existing: the
    # canvas planner splits the page into immutable data blocks (module-
    # pre-rendered truth) and open creative sections (LLM-authored in
    # 2-3 chunks under the canvas contract), fact-checks the assembled
    # page, and hands the document to render_and_persist at slot
    # population. Any failure falls back to today's module+atelier path
    # (the §9 degradation ladder). Default OFF: unset SITE_CANVAS leaves
    # the deterministic path byte-identical.
    canvas_html: Optional[str] = None
    canvas_report: Optional[Dict[str, Any]] = None

    def _try_canvas(the_spec: List[Dict[str, Any]], notes: str = ""):
        import canvas as _canvas_mod
        return _canvas_mod.run_canvas(the_spec, ctx, dro, business_id,
                                      progress_cb=progress_cb, feedback=notes)

    # SPEC IS VISION (2026-07-24): the canvas used to require a DRO —
    # so a DRO failure (e.g. the prefill 400) silently skipped the
    # canvas AND the practitioner's APPROVED SPEC never reached any
    # author; the module path shipped the old template instead. An
    # approved spec is a complete, owner-read design document: it
    # qualifies as the vision on its own.
    _has_spec = bool((ctx.get("design_spec_text") or "").strip())
    if use_llm and not dro and _has_spec:
        logger.warning(f"[composer] DRO missing but an APPROVED SPEC "
                       f"exists — canvas runs on the spec for "
                       f"{business_id[:8]}")
    # ── BUILDER V2 (Revamp Phase 2, SITE_BUILDER_V2=on) ────────────────
    # One mind, one call, the whole page from the APPROVED SPEC; the
    # contract armor (annotator, JS/external armor, truth + coverage,
    # one scoped repair) runs after authorship. On success the document
    # joins at the same seam the canvas uses; on any failure the ladder
    # continues below (canvas → modules), wearing the spec's tokens via
    # the bridge either way.
    if use_llm and _has_spec and canvas_html is None:
        try:
            import builder_v2 as _bv2
            if _bv2.enabled():
                _report_progress(progress_cb, 47, "Builder v2 — one mind")
                _v2 = _bv2.run_builder_v2(
                    ctx.get("design_spec_text") or "", ctx, business_id,
                    progress_cb=lambda pct, stage: _report_progress(
                        progress_cb, pct, stage))
                canvas_report = (_v2 or {}).get("report") or canvas_report
                if (_v2 or {}).get("html"):
                    canvas_html = _v2["html"]
                    logger.info(f"[composer] BUILDER V2 composed for "
                                f"{business_id[:8]}")
                else:
                    logger.warning(f"[composer] builder v2 fell back for "
                                   f"{business_id[:8]}: "
                                   f"{(canvas_report or {}).get('fallbacks')}")
        except Exception as _v2e:
            logger.warning(f"[composer] builder v2 crashed (non-fatal — "
                           f"the ladder continues): "
                           f"{type(_v2e).__name__}: {_v2e}")

    if use_llm and (dro or _has_spec) and canvas_html is None:
        try:
            import canvas as _canvas_mod
            if _canvas_mod.canvas_enabled():
                _report_progress(progress_cb, 50, "Authoring the canvas")
                _out = _try_canvas(spec)
                canvas_html = (_out or {}).get("html") or None
                canvas_report = (_out or {}).get("report") or None
                if canvas_html:
                    logger.info(f"[composer] CANVAS composed for "
                                f"{business_id[:8]} "
                                f"(planned={((canvas_report or {}).get('planned'))})")
                else:
                    logger.warning(f"[composer] canvas fell back to the module "
                                   f"path for {business_id[:8]}: "
                                   f"{(canvas_report or {}).get('fallbacks')}")
        except Exception as _ce:
            logger.warning(f"[composer] canvas crashed (non-fatal — the "
                           f"module path continues): "
                           f"{type(_ce).__name__}: {_ce}")
            canvas_html, canvas_report = None, {
                "fallbacks": [{"stage": "exception",
                               "detail": f"{type(_ce).__name__}: {_ce}"}]}

    result = render_and_persist(business_id, spec, ctx, dro_id=dro_id, dro=dro,
                                dro_status=dro_status, dro_summary=dro_summary,
                                defaulted_modules=defaulted_modules,
                                full_recompose=True, progress_cb=progress_cb,
                                dro_failure=dro_failure,
                                # COST DIET (2026-07-22): the automatic
                                # second full build on a gate fail is
                                # OPT-IN (QUALITY_REGEN=on). The verdict
                                # + notes are visible in the editor and
                                # the ratchet blocks downgrades — the
                                # practitioner decides whether a retry
                                # is worth paying for.
                                _regen_allowed=use_llm and _quality_regen_enabled(),
                                _canvas_html=canvas_html,
                                _canvas_report=canvas_report)

    # ── A2 (2026-07-18) — THE BOUNDED QUALITY REGEN ───────────────────
    # The loop closes: when the vision grader FAILS the build — or the
    # design invariants report HIGH findings (DESIGN_INVARIANTS=enforce;
    # advisory findings stay telemetry per that file's rollout contract) —
    # regenerate copy + bespoke fragments ONCE with the grader's notes
    # injected into both prompts, then re-render. Keep-better guard: if
    # pass 1 actually graded better (possible when invariants alone
    # triggered), restore it via the banked previous_compose slot.
    # Bounded: exactly one extra copy+atelier+render pass, only on
    # failing full composes.
    try:
        _v1 = result.get("vision_verdict") or {}
        _inv1 = ((result.get("quality_report") or {}).get("design_invariants")
                 or [])
        _inv_blocking = [f for f in _inv1 if f.get("severity") == "HIGH"]
        _inv_verify = ((result.get("quality_report") or {})
                       .get("invention_verification") or {})
        _invention_fail = _inv_verify.get("ok") is False
        _failed = bool(_v1) and not _v1.get("passes_gate", True)
        # COST DIET enforcement (2026-07-22): #206 declared the automatic
        # second build opt-in, but this condition never consulted the
        # flag — every below-bar build silently paid for a full second
        # compose. QUALITY_REGEN=on is now required, as documented.
        if (use_llm and dro and _quality_regen_enabled()
                and (_failed or _inv_blocking or _invention_fail)):
            _notes = _regen_feedback(_v1 if _failed else None, _inv1)
            if _invention_fail:
                _notes = ((_notes + "\n") if _notes else "") + (
                    "INVENTION CHECK FAILED: the previous design offered "
                    f"{_inv_verify.get('count')} genuine invention(s) — the "
                    "doctrine (D12) requires >=3 additions that are NOT in "
                    "the brief. Restated lines: "
                    f"{'; '.join((_inv_verify.get('restatements') or [])[:3]) or 'n/a'}. "
                    "Add design decisions the brief did not ask for, each "
                    "building on a stated constraint.")
            logger.warning(f"[composer] quality regen for {business_id[:8]} "
                           f"(vision_fail={_failed}, "
                           f"invariants_high={len(_inv_blocking)}, "
                           f"invention_fail={_invention_fail}): "
                           f"{_notes[:200]}")
            _report_progress(progress_cb, 96,
                             "Polishing from grader feedback")
            try:
                spec2 = compose_spec_llm(ctx, brief_notes or "", dro=dro,
                                         feedback=_notes)
                spec2 = _ensure_connections(spec2, ctx)
                spec2 = _apply_cta_goal(spec2, ctx)
                defaulted2 = [s["module"] for s in spec2
                              if s.get("_variant_defaulted")]
                spec2 = _apply_symmetry_preference(spec2,
                                                   decisions.get("layout"))
                if dro:
                    _apply_hero_direction(spec2, decisions.get("hero_concept"))
                if ctx.get("gallery") and not any(s.get("module") == "gallery"
                                                  for s in spec2):
                    _gv = ("mosaic" if (ctx.get("dna") or {}).get("vibe") == "bold"
                           else "grid")
                    _pos = next((i for i, s in enumerate(spec2)
                                 if s.get("module") == "contact"), len(spec2))
                    spec2.insert(max(1, _pos), {"module": "gallery",
                                                "variant": _gv, "content": {}})
                try:
                    import page_frameworks as _pf2
                    spec2 = _pf2.apply_framework(spec2, ctx, dro)
                except Exception:
                    pass
                spec2 = _apply_ceremony_pass(spec2, ctx, dro, seed=dro_id)
            except Exception as _spec_err:
                logger.warning(f"[composer] regen copy pass failed (keeping "
                               f"first pass): {_spec_err}")
                spec2, defaulted2 = None, None
            if spec2:
                # Canvas Pass: pass 1 was canvas-composed → the regen
                # RE-AUTHORS the canvas on the new spec with the grader's
                # notes (not the module path); a failed canvas regen
                # degrades to the module path per the §9 ladder. The
                # keep-better guard below is untouched either way.
                _c2_html: Optional[str] = None
                _c2_report: Optional[Dict[str, Any]] = None
                if canvas_html is not None:
                    try:
                        _out2 = _try_canvas(spec2, _notes)
                        _c2_html = (_out2 or {}).get("html") or None
                        _c2_report = (_out2 or {}).get("report") or None
                    except Exception as _ce2:
                        logger.warning(f"[composer] canvas regen failed "
                                       f"(module path): {_ce2}")
                result2 = render_and_persist(
                    business_id, spec2, ctx, dro_id=dro_id, dro=dro,
                    dro_status=dro_status, dro_summary=dro_summary,
                    defaulted_modules=defaulted2,
                    full_recompose=True, progress_cb=progress_cb,
                    dro_failure=dro_failure,
                    _regen_attempted=True, _regen_notes=_notes,
                    _prior_verdict=_v1 or None,
                    _canvas_html=_c2_html, _canvas_report=_c2_report)
                _v2 = result2.get("vision_verdict") or {}
                _pass1_better = (bool(_v1) and bool(_v2)
                                 and _v1.get("passes_gate", False)
                                 and not _v2.get("passes_gate", True))
                if _pass1_better:
                    # Invariant-triggered regen made the vision grade WORSE
                    # — restore pass 1 (render #2 banked it as
                    # previous_compose) and re-attribute the verdict.
                    logger.warning(f"[composer] regen graded worse for "
                                   f"{business_id[:8]} — restoring first pass")
                    restore_previous_compose(business_id)
                    try:
                        _rows = sb_clients.sb_get_as_service(
                            f"/business_sites?business_id=eq.{business_id}"
                            "&select=id,site_config&limit=1") or []
                        if _rows:
                            _cfg = dict(_rows[0].get("site_config") or {})
                            _cfg["vision_verdict"] = _v1
                            _cfg.pop("vision_verdict_prior", None)
                            sb_clients.sb_patch_as_service(
                                f"/business_sites?id=eq.{_rows[0]['id']}",
                                {"site_config": _cfg})
                    except Exception:
                        pass
                    result["quality_regen"] = {"triggered": True,
                                               "reverted": True,
                                               "notes": _notes[:400]}
                else:
                    result2["quality_regen"] = {"triggered": True,
                                                "reverted": False,
                                                "notes": _notes[:400]}
                    result = result2
    except Exception as _rg_err:
        # FALSE-FAILURE FIX (2026-07-22, Kevin's report: "it says it
        # didn't meet the standard, then I refresh and the upgrade is
        # there"): by the time this regen block runs, PASS 1 HAS ALREADY
        # SHIPPED — so nothing here (including the ratchet blocking the
        # regen's second build) may fail the job. A genuine block of
        # pass 1 raises from render_and_persist above and never reaches
        # this block.
        logger.warning(f"[composer] quality regen abandoned (first pass "
                       f"is live): {type(_rg_err).__name__}: {_rg_err}")

    # (Removed 2026-07-22: the pre-ratchet tail enforce block re-raised
    # "ship-gate: vision verdict failed" for every below-bar verdict even
    # when the ratchet had already SHIPPED the build — the exact
    # failed-message-but-refresh-shows-the-upgrade defect. The ratchet
    # inside render_and_persist is the single gate authority now.)

    # Multi-page: render the secondary pages (sharing the home's design) and
    # persist generated_pages. Best-effort — a failure never blocks the home.
    if _mp_slug:
        try:
            import site_multipage
            _title_mp = (ctx.get("business") or {}).get("name") or "Welcome"
            _pages = site_multipage.build_secondary_pages(ctx, _mp_slug, _title_mp)
            if _pages:
                _rows = sb_clients.sb_get_as_service(
                    f"/business_sites?business_id=eq.{business_id}"
                    f"&select=site_config&order=updated_at.desc&limit=1") or []
                _cfg = (_rows[0].get("site_config") if _rows else {}) or {}
                _cfg["generated_pages"] = _pages
                _cfg["site_pages"] = ["home"] + list(site_multipage.SECONDARY_PAGES)
                sb_clients.sb_patch_as_service(
                    f"/business_sites?business_id=eq.{business_id}",
                    {"site_config": _cfg})
                logger.info(f"[composer] multi-page: persisted "
                            f"{len(_pages)} secondary page(s) for {business_id[:8]}")
        except Exception as _e:
            logger.warning(f"[composer] multi-page build skipped (non-fatal): {_e}")

    # Arc 19 weight-hole fix (2026-07-30): THE one billable row for this
    # build — weighted 25 by usage_metering.UNIT_WEIGHTS while the per-call
    # authoring rows above it are weight 0. Only a shipped LLM compose
    # bills: a blocked build raises out of render_and_persist before this
    # line, and deterministic/fallback composes (source != "llm") are free.
    if use_llm and source == "llm":
        try:
            from api_usage_logger import log_api_usage_sync
            log_api_usage_sync(
                endpoint="/composer/compose", model="site-build-marker",
                input_tokens=0, output_tokens=0, business_id=business_id,
                task_type="site_build_marker", cost_cents_override=0.0)
        except Exception as _mk_e:
            logger.warning(f"[composer] build marker row failed "
                           f"(non-fatal): {_mk_e}")

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
    creative = _creative_plus_story(ctx)

    from agents.composer.drl import passes as drl_passes
    # ONE signal pass shared by all three candidates (same intake).
    _report_progress(progress_cb, 15, "Listening to your style words")
    signals = drl_passes.detect_signals(business_id, intake)
    recent = drl_passes.fetch_recent_dros(business_id)

    import copy as _copy
    import time as _time
    items: List[Dict[str, Any]] = []
    errors: List[str] = []
    _n_stances = max(len(DIRECTION_STANCES), 1)
    # Site Arc 12 — candidate authoring stays on the DRL model (Opus by
    # default: the 3 candidate DROs ARE the creative reasoning being
    # chosen between; ~20k output tokens ≈ +$0.40/run at Opus rates vs
    # Sonnet — Kevin ruled quality-first). Opus streams ~2-3x slower, so
    # log cumulative elapsed per candidate: the 10-min chief_jobs stale
    # sweep is the hard wall, and this is the early-warning line.
    _t0 = _time.monotonic()
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
                creative=creative, stance=stance_text,
                owner_direction=_owner_direction_evidence(ctx))
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
                        f"{business_id[:8]}: {label} "
                        f"(cumulative {_time.monotonic() - _t0:.0f}s "
                        f"after {_idx + 1}/{_n_stances} candidates)")
        except Exception as e:
            errors.append(f"{stance_key}: {e}")
            logger.warning(f"[composer.directions] '{stance_key}' failed for "
                           f"{business_id[:8]} (continuing, cumulative "
                           f"{_time.monotonic() - _t0:.0f}s): {e}")

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
    """Access gate shared by every composer endpoint: 404 for an unknown
    business; the owner passes, and — seat-access arc (7/31) — so does an
    active team seat at MEMBER or above (Studio/site work is everyday
    operator work; viewers stay read-only). Session-only auth is NOT
    enough here — these endpoints do service-role writes."""
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{business_id}&select=id,owner_id&limit=1") or []
    if not rows:
        raise HTTPException(status_code=404, detail="business not found")
    if str(rows[0].get("owner_id")) == str(user_id):
        return
    from business_users_router import require_role
    require_role(business_id, str(user_id), "member")


class ComposeBody(BaseModel):
    business_id: str
    brief_notes: Optional[str] = None
    use_llm: bool = True
    design_prefs: Optional[Dict[str, Any]] = None   # Arc 2 "Ask the Owner"
    # Refine mode: reuse the stored rationale (polish the current
    # direction) instead of authoring a fresh one (rolling a new one).
    refine: bool = False


@router.post("/compose")
def compose(body: ComposeBody,
            session: UserSession = Depends(sb_clients.authed_request)) -> Dict[str, Any]:
    _require_owner(body.business_id, session.user.id)
    # 7/30 tier arc — the most expensive action on the platform finally
    # checks the allowance (dormant behind BILLING_ENFORCE; deterministic
    # composes stay free).
    if body.use_llm:
        import billing_limits
        billing_limits.require_units(body.business_id)
    result = compose_site(body.business_id, body.brief_notes or "", body.use_llm,
                          design_prefs=body.design_prefs, refine=body.refine)
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
    # Booking detection fix (2026-07-10): the interview's connect chip
    # read only the legacy flag — a published booking module showed
    # "Set up later". booking_is_live sees the real system.
    from booking_widget_router import booking_is_live
    booking_configured = bool(booking_is_live(business_id, b_settings)
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


# ─── Interview v3 (Chief-guided interview) — prefill / probe / events ────
# The backend of docs/CHIEF_GUIDED_INTERVIEW.md §4. All owner-gated, all
# fail-soft; only the probe calls an LLM (hard-capped).


@router.get("/interview/prefill/{business_id}")
def interview_prefill(business_id: str,
                      user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """Interview v3 (B2) — ONE call that gives the beat machine everything
    it needs to confirm-instead-of-ask: the raw stored site_prefs, the
    brand-kit design tokens, the same clarity signals the adaptive
    interview uses, and the gallery count. Single businesses.settings read
    (the _persist_site_prefs idiom), zero LLM. Fail-soft: empty/missing
    data → nulls/zeros and the interview simply asks everything."""
    _require_owner(business_id, user.id)

    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{business_id}&select=settings&limit=1") or []
    settings = rows[0].get("settings") if rows else {}
    if not isinstance(settings, dict):
        settings = {}

    site_prefs = (settings.get("site_prefs")
                  if isinstance(settings.get("site_prefs"), dict) else None)

    # brand_design — settings.brand_kit: the nested colors dict + fonts,
    # tolerating the legacy flat primary_color shape.
    kit = (settings.get("brand_kit")
           if isinstance(settings.get("brand_kit"), dict) else {})
    kc = kit.get("colors") if isinstance(kit.get("colors"), dict) else {}
    font_pair = (kit.get("font_pair")
                 if isinstance(kit.get("font_pair"), dict) else {})
    brand_design = {
        "accent_color": kc.get("accent") or kit.get("accent_color"),
        "primary_color": kc.get("primary") or kit.get("primary_color"),
        "secondary_color": kc.get("secondary") or kit.get("secondary_color"),
        "background_color": kc.get("background") or kit.get("background_color"),
        "text_color": kc.get("text") or kit.get("text_color"),
        "font_heading": kit.get("font_heading") or font_pair.get("heading"),
        "font_body": kit.get("font_body") or font_pair.get("body"),
        "fonts_locked": bool(kit.get("fonts_locked")),
        # The Brand Room's stored sentence, so beat 6 can offer it back for
        # confirmation. Rides the settings read that already happened.
        # site_prefs.visual_style (a previously CONFIRMED answer) wins when
        # present — re-asking a question they already answered this way
        # would read as the system forgetting.
        "visual_style": ((site_prefs or {}).get("visual_style")
                         or kit.get("visual_style") or ""),
    }

    # signals — the same facts prefill-signals computes (one bundle read,
    # one offerings read; each fail-soft on its own).
    has_about = False
    audience_known = False
    try:
        import brand_engine
        bundle = brand_engine.get_bundle(business_id) or {}
        intel = (bundle.get("practitioner_intelligence")
                 if isinstance(bundle.get("practitioner_intelligence"), dict) else {})
        voice = bundle.get("voice") if isinstance(bundle.get("voice"), dict) else {}
        has_about = len(str(intel.get("about_business") or "").strip()) > 80
        strategy = (intel.get("strategy_track")
                    if isinstance(intel.get("strategy_track"), dict) else {})
        audience_known = bool(str(voice.get("audience") or "").strip()
                              or str(strategy.get("target_audience") or "").strip())
    except Exception as e:
        logger.info(f"[composer.interview-prefill] bundle read skipped: {e}")

    offerings: List[Dict[str, Any]] = []
    try:
        offerings = [o for o in (sb_clients.sb_get_as_service(
            f"/offerings?business_id=eq.{business_id}&is_active=eq.true"
            "&select=id,name,price,description&limit=50") or [])
            if isinstance(o, dict)]
    except Exception as e:
        logger.info(f"[composer.interview-prefill] offerings read skipped: {e}")
    offer_clear = any(
        str(o.get("name") or "").strip()
        and o.get("price") is not None and str(o.get("price")).strip() != ""
        and len(str(o.get("description") or "").strip()) >= 40
        for o in offerings)

    # testimonial_count — the compose context's source of truth is
    # settings.website_content.testimonials (visible dict rows only, the
    # gather_context rule); it rides the SAME settings read, so it's cheap.
    wc = (settings.get("website_content")
          if isinstance(settings.get("website_content"), dict) else {})
    _testi_raw = wc.get("testimonials") or []
    testimonial_count = len(
        [t for t in _testi_raw
         if isinstance(t, dict) and t.get("show_on_website", True)]
    ) if isinstance(_testi_raw, list) else 0

    # gallery_photos — settings.media_library.gallery, the gather_context
    # visibility rule (dict rows with a url, show_on_website not False).
    ml = (settings.get("media_library")
          if isinstance(settings.get("media_library"), dict) else {})
    _gal_raw = ml.get("gallery") or []
    gallery_photos = len(
        [g for g in _gal_raw
         if isinstance(g, dict) and str(g.get("url") or "").strip()
         and g.get("show_on_website", True)]
    ) if isinstance(_gal_raw, list) else 0

    return {"site_prefs": site_prefs,
            "brand_design": brand_design,
            "signals": {"offer_clear": offer_clear,
                        "audience_known": audience_known,
                        "has_about": has_about,
                        "offer_count": len(offerings),
                        "testimonial_count": testimonial_count},
            "media": {"gallery_photos": gallery_photos}}


_PROBE_SYSTEM = (
    "You are Chief, mid-interview for a website design. Ask ONE short "
    "follow-up question that would make this answer more usable for "
    "designing the site. If the answer is already usable, respond with "
    "the single word CLEAR.")
_PROBE_MODEL = "claude-haiku-4-5-20251001"   # cheap + fast; 150 tokens, 10s
_PROBE_ANSWER_CAP = 600
_PROBE_FOLLOWUP_CAP = 300


class InterviewProbeBody(BaseModel):
    business_id: str
    beat_id: Any = None            # beats are numbered client-side; stay lenient
    answer: Any = ""
    context: Optional[Dict[str, Any]] = None


@router.post("/interview/probe")
def interview_probe(body: InterviewProbeBody,
                    user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """Interview v3 (B3) — ONE short follow-up question when a free-text
    answer is vague. Budget-capped server-side: 6/hour per business via
    rate_limit.py (a budget that only lives in the client isn't a budget).
    Fail-SILENT: CLEAR / empty / error / timeout → {"followup": None} and
    the beat proceeds."""
    _require_owner(body.business_id, user.id)

    import rate_limit
    if not rate_limit.allow("interview_probe", body.business_id):
        raise HTTPException(
            status_code=429,
            detail="Probe budget reached — the interview continues without it.",
            headers={"Retry-After": str(rate_limit.retry_after("interview_probe"))})

    answer = str(body.answer or "").strip()
    if not answer:
        return {"followup": None}
    ctx = body.context if isinstance(body.context, dict) else {}
    user_content = (
        f"Business: {ctx.get('business_name') or '(unnamed)'} "
        f"(type: {ctx.get('type') or 'unknown'})\n"
        f"Interview beat: {body.beat_id}\n"
        f"The owner's answer: {answer[:_PROBE_ANSWER_CAP]}")
    try:
        import site_llm
        msg = site_llm.create_message(
            model=_PROBE_MODEL, max_tokens=150, system=_PROBE_SYSTEM,
            user_content=user_content, timeout=10.0,
            task="composer/interview-probe")
        text = "".join(b.text for b in msg.content
                       if getattr(b, "type", None) == "text").strip()
    except Exception as e:
        logger.info(f"[composer.interview-probe] probe failed soft for "
                    f"{body.business_id[:8]} ({type(e).__name__}): {e}")
        return {"followup": None}
    if not text or text.upper().rstrip(".! ") == "CLEAR":
        return {"followup": None}
    return {"followup": text[:_PROBE_FOLLOWUP_CAP]}


_INTERVIEW_EVENT_KINDS = ("start", "answer", "skip", "edit_back", "probe",
                          "skip_to_summary", "submit")
_INTERVIEW_EVENTS_CAP = 200        # ring buffer size in settings
_INTERVIEW_EVENTS_REQ_CAP = 50     # max events accepted per request


class InterviewEventsBody(BaseModel):
    business_id: str
    # List[Any] on purpose: lenient validation lives in the endpoint —
    # bad rows are dropped there, never a 422 (fire-and-forget telemetry).
    events: List[Any] = []


@router.post("/interview/events")
def interview_events(body: InterviewEventsBody,
                     user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """Interview v3 (B6) — per-beat completion telemetry (Phase 2's adaptive
    depth is only buildable with this data). Fire-and-forget from the
    client: lenient validation (bad rows silently dropped), appended to
    businesses.settings.interview_events as a ring buffer capped at 200
    (read-modify-write, the _persist_site_prefs idiom). No LLM."""
    _require_owner(body.business_id, user.id)

    clean: List[Dict[str, Any]] = []
    for e in (body.events or [])[:_INTERVIEW_EVENTS_REQ_CAP]:
        if not isinstance(e, dict):
            continue
        kind = e.get("event")
        beat = e.get("beat")
        if kind not in _INTERVIEW_EVENT_KINDS or beat is None:
            continue
        row: Dict[str, Any] = {"beat": beat, "event": kind}
        at = e.get("at")
        if isinstance(at, (str, int, float)):
            row["at"] = at
        clean.append(row)
    if not clean:
        return {"ok": True, "accepted": 0}

    try:
        rows = sb_clients.sb_get_as_service(
            f"/businesses?id=eq.{body.business_id}&select=settings&limit=1") or []
        if not rows:
            raise HTTPException(404, "business not found")
        settings = dict(rows[0].get("settings") or {})
        buf = settings.get("interview_events")
        buf = ([r for r in buf if isinstance(r, dict)]
               if isinstance(buf, list) else [])
        settings["interview_events"] = (buf + clean)[-_INTERVIEW_EVENTS_CAP:]
        sb_clients.sb_patch_as_service(
            f"/businesses?id=eq.{body.business_id}", {"settings": settings})
    except HTTPException:
        raise
    except Exception as e:
        # Fire-and-forget telemetry: a persist hiccup never surfaces.
        logger.info(f"[composer.interview-events] persist failed soft for "
                    f"{body.business_id[:8]}: {e}")
        return {"ok": False, "accepted": 0}
    return {"ok": True, "accepted": len(clean)}


class ShuffleBody(BaseModel):
    business_id: str
    section_index: int
    # None → cycle to the NEXT variant (the old "Shuffle look").
    # Set → PICK this exact variant (the layout picker). Validated below.
    variant: Optional[str] = None


@router.post("/shuffle")
def shuffle(body: ShuffleBody,
            session: UserSession = Depends(sb_clients.authed_request)) -> Dict[str, Any]:
    """Change one section's expression variant and re-render. Deterministic +
    instant — no LLM call. `variant` picks a specific layout; omitting it
    cycles to the next (back-compat)."""
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
    if body.variant is not None:
        # Direct pick (layout picker). Validate against the module's real
        # variants so a bad value can't corrupt the spec.
        if body.variant not in variants:
            raise HTTPException(
                400, f"'{body.variant}' is not a layout of {sec['module']} "
                     f"(choices: {list(variants)})")
        sec["variant"] = body.variant
    else:
        cur = sec.get("variant")
        idx = variants.index(cur) if cur in variants else -1
        sec["variant"] = variants[(idx + 1) % len(variants)]
    result = render_and_persist(body.business_id, spec, ctx)
    return {"ok": True, "shuffled": {"index": body.section_index,
                                     "module": sec["module"],
                                     "variant": sec["variant"]}, **result}


# ─── THE SPEC AUTHOR (Director's Cut arc 3) ──────────────────────────
# The design spec is authored, read, revised and approved for PENNIES
# (text-only calls); only an APPROVED spec is worth a paid build,
# where compose_site hands it to the canvas as the law of the page.

class SpecAuthorBody(BaseModel):
    business_id: str
    notes: Optional[str] = None      # the owner's words for this draft


class SpecReviseBody(BaseModel):
    business_id: str
    notes: str                       # revision notes — required


class SpecStatusBody(BaseModel):
    business_id: str


def _spec_inputs(business_id: str):
    """Shared assembly for author/revise: ctx + stored DRO + the stored
    section plan (no LLM, no compose fee)."""
    ctx = gather_context(business_id)
    dro = _load_stored_dro(business_id)
    cfg = ((ctx.get("site") or {}).get("site_config") or {})
    spec_raw = cfg.get("page_spec")
    plan = sanitize_spec(spec_raw, ctx) if spec_raw else []
    return ctx, dro, plan


@router.get("/spec/{business_id}")
def get_design_spec(business_id: str,
                    session: UserSession = Depends(sb_clients.authed_request)
                    ) -> Dict[str, Any]:
    """The current design spec document (draft or approved), or null."""
    _require_owner(business_id, session.user.id)
    import spec_author
    return {"spec": spec_author.get_spec(business_id)}


@router.post("/spec/author")
def author_design_spec(body: SpecAuthorBody,
                       session: UserSession = Depends(sb_clients.authed_request)
                       ) -> Dict[str, Any]:
    """Author a fresh spec draft from everything the system knows.
    Text-only call — cheap by design; never triggers a build."""
    _require_owner(body.business_id, session.user.id)
    import spec_author
    ctx, dro, plan = _spec_inputs(body.business_id)
    if (body.notes or "").strip():
        ctx["owner_brief"] = body.notes.strip()[:600]
    text = spec_author.author_spec(body.business_id, ctx, dro, plan)
    if not text:
        raise HTTPException(502, "spec author unavailable — try again")
    saved = spec_author.save_spec(body.business_id, text, status="draft")
    return {"ok": True, "spec": saved}


@router.post("/spec/revise")
def revise_design_spec(body: SpecReviseBody,
                       session: UserSession = Depends(sb_clients.authed_request)
                       ) -> Dict[str, Any]:
    """Revise the existing spec with the owner's notes — keeps every
    decision the notes don't question."""
    _require_owner(body.business_id, session.user.id)
    import spec_author
    prior = spec_author.get_spec(body.business_id)
    if not prior:
        raise HTTPException(409, "no spec to revise — author one first")
    if not (body.notes or "").strip():
        raise HTTPException(400, "revision notes are required")
    ctx, dro, plan = _spec_inputs(body.business_id)
    text = spec_author.author_spec(
        body.business_id, ctx, dro, plan,
        prior_spec=str(prior.get("text") or ""), feedback=body.notes.strip())
    if not text:
        raise HTTPException(502, "spec author unavailable — try again")
    saved = spec_author.save_spec(body.business_id, text, status="draft")
    return {"ok": True, "spec": saved}


@router.post("/spec/approve")
def approve_design_spec(body: SpecStatusBody,
                        session: UserSession = Depends(sb_clients.authed_request)
                        ) -> Dict[str, Any]:
    """Mark the spec approved — the next full rebuild executes it as
    the law of the page."""
    _require_owner(body.business_id, session.user.id)
    import spec_author
    spec = spec_author.set_status(body.business_id, "approved")
    if not spec:
        raise HTTPException(409, "no spec to approve — author one first")
    return {"ok": True, "spec": spec}


# ─── DISCOVERY (Revamp Phase 1) — the ONE dossier ────────────────────

class DiscoveryReconBody(BaseModel):
    business_id: str


class DiscoveryReferenceBody(BaseModel):
    business_id: str
    url: str
    verdict: str            # "love" | "hate"
    why: Optional[str] = None


@router.get("/discovery/{business_id}")
def get_discovery(business_id: str,
                  session: UserSession = Depends(sb_clients.authed_request)
                  ) -> Dict[str, Any]:
    """The current discovery dossier, or null."""
    _require_owner(business_id, session.user.id)
    import discovery
    return {"dossier": discovery.get_dossier(business_id)}


@router.post("/discovery/recon")
def discovery_recon(body: DiscoveryReconBody,
                    session: UserSession = Depends(sb_clients.authed_request)
                    ) -> Dict[str, Any]:
    """Step 0: migrate what the system already holds into the dossier
    (brand mark, work, portrait, prefs, vertical) with source 'recon'.
    Never clobbers what the practitioner said. No LLM, no build."""
    _require_owner(body.business_id, session.user.id)
    import discovery
    d = discovery.recon_dossier(body.business_id)
    if d is None:
        raise HTTPException(404, "business not found")
    return {"ok": True, "dossier": d}


@router.post("/discovery/reference")
def discovery_reference(body: DiscoveryReferenceBody,
                        session: UserSession = Depends(sb_clients.authed_request)
                        ) -> Dict[str, Any]:
    """Study one loved/hated reference site: screenshot → transferable
    rules + bans + taste reading. Failures are recorded facts (the
    dossier notes what couldn't be captured); the response is never a
    silent gap and never a 500 for a bot-blocked site."""
    _require_owner(body.business_id, session.user.id)
    if not (body.url or "").lower().startswith("http"):
        raise HTTPException(400, "url must be http(s)")
    import discovery
    entry = discovery.study_reference(
        body.business_id, body.url.strip(), body.verdict,
        (body.why or "").strip())
    return {"ok": True, "reference": entry}


class DiscoveryAnswerBody(BaseModel):
    business_id: str
    patch: Dict[str, Any]


class DiscoveryDeriveBody(BaseModel):
    business_id: str


@router.post("/discovery/answer")
def discovery_answer(body: DiscoveryAnswerBody,
                     session: UserSession = Depends(sb_clients.authed_request)
                     ) -> Dict[str, Any]:
    """The practitioner-write door: identity/taste/truth/vertical leaves
    (each {"value","source"} with a practitioner source) and/or the
    confirmed_brief. Recon and inference have their own doors; nothing
    here can be silently overwritten by them later."""
    _require_owner(body.business_id, session.user.id)
    import discovery
    d = discovery.answer(body.business_id, body.patch or {})
    if d is None:
        raise HTTPException(404, "business site not found")
    return {"ok": True, "dossier": d}


@router.post("/discovery/derive")
def discovery_derive(body: DiscoveryDeriveBody,
                     session: UserSession = Depends(sb_clients.authed_request)
                     ) -> Dict[str, Any]:
    """Derive the seven taste readings from the mark + work + studied
    references (one vision call). Written with source 'inferred' —
    pending the practitioner's confirm; their answered pairs are never
    overwritten. Fail-open with a recorded gap."""
    _require_owner(body.business_id, session.user.id)
    import discovery
    d = discovery.derive_taste(body.business_id)
    if d is None:
        raise HTTPException(404, "business site not found")
    return {"ok": True, "dossier": d}


class CoachTurnBody(BaseModel):
    business_id: str
    messages: List[Dict[str, str]] = []


class CoachFinishBody(BaseModel):
    business_id: str


@router.post("/coach/turn")
def coach_turn(body: CoachTurnBody,
               session: UserSession = Depends(sb_clients.authed_request)
               ) -> Dict[str, Any]:
    """THE DESIGN COACH (2026-07-25) — discovery's conversational door.
    Stateless: the frontend carries the transcript, the backend carries
    the truth (dossier + business facts injected every turn so the
    coach never re-asks). Every extracted detail lands in the dossier
    with provenance 'asked' before the reply returns. Errors come back
    as {error} for a visible retry, never a 500 blank."""
    _require_owner(body.business_id, session.user.id)
    import design_coach
    return design_coach.run_turn(body.business_id, body.messages or [])


@router.post("/coach/finish")
def coach_finish(body: CoachFinishBody,
                 session: UserSession = Depends(sb_clients.authed_request)
                 ) -> Dict[str, Any]:
    """Session close: derive the taste readings from everything
    gathered, stamp the session complete, return the digest. The
    frontend follows with /spec/author so the Director drafts the
    blueprint from a still-warm dossier."""
    _require_owner(body.business_id, session.user.id)
    import design_coach
    return design_coach.finish_session(body.business_id)


class DropFillBody(BaseModel):
    business_id: str
    slot: str
    url: str


_DROP_SLOT_RE_TMPL = (
    r'<div\b[^>]*\bdata-sx-slot="{slot}"[^>]*>'
    r'(?:(?!</?div\b).)*?</div>')


def fill_drop_slot(html: str, slot: str, url: str) -> Optional[str]:
    """Deterministic placeholder → image swap (the claude.ai Design
    Labs move, 2026-07-25). The builder authored the frame and the
    crop; the owner's photo inherits that intention. Pure; None when
    the slot isn't found. The inline display:block outranks the
    authored `.sx-drop{display:none}` so a FILLED slot shows on the
    public page while empty ones stay hidden."""
    safe_slot = re.escape(slot)
    pat = re.compile(_DROP_SLOT_RE_TMPL.format(slot=safe_slot),
                     re.DOTALL | re.IGNORECASE)
    if not pat.search(html):
        return None
    esc_url = url.replace('"', "%22")
    replacement = (
        f'<div class="sx-drop sx-filled" data-sx-slot="{slot}" '
        f'style="display:block;padding:0">'
        f'<img src="{esc_url}" alt="" loading="lazy" '
        f'style="width:100%;height:100%;object-fit:cover;display:block">'
        f'</div>')
    return pat.sub(replacement, html, count=1)


@router.post("/drop/fill")
def drop_fill(body: DropFillBody,
              session: UserSession = Depends(sb_clients.authed_request)
              ) -> Dict[str, Any]:
    """Fill an art-directed drop slot with the owner's uploaded image —
    zero model calls, surgical, persisted to BOTH the served page and
    the stored canvas so re-renders keep the photo."""
    _require_owner(body.business_id, session.user.id)
    url = (body.url or "").strip()
    if not (url.startswith("https://") and len(url) < 2000):
        raise HTTPException(400, "a https image url is required")
    rows = sb_clients.sb_get_as_service(
        f"/business_sites?business_id=eq.{body.business_id}"
        "&select=id,html_content,site_config&limit=1") or []
    if not rows:
        raise HTTPException(404, "site not found")
    row = rows[0]
    html = row.get("html_content") or ""
    filled = fill_drop_slot(html, body.slot, url)
    if filled is None:
        raise HTTPException(404, f"drop slot '{body.slot}' not on the page")
    cfg = dict(row.get("site_config") or {})
    canvas = cfg.get("canvas") if isinstance(cfg.get("canvas"), dict) else None
    if canvas and str(canvas.get("html") or "").strip():
        c_filled = fill_drop_slot(str(canvas["html"]), body.slot, url)
        if c_filled is not None:
            canvas = dict(canvas)
            canvas["html"] = c_filled
            cfg["canvas"] = canvas
    fills = dict(cfg.get("drop_fills") or {})
    fills[body.slot] = url
    cfg["drop_fills"] = fills
    sb_clients.sb_patch_as_service(
        f"/business_sites?id=eq.{row['id']}",
        {"html_content": filled, "site_config": cfg})
    logger.info(f"[composer] drop slot '{body.slot}' filled for "
                f"{body.business_id[:8]}")
    return {"ok": True, "slot": body.slot}


_DROP_UPLOAD_MIMES = {"image/jpeg": "jpg", "image/jpg": "jpg",
                      "image/png": "png", "image/webp": "webp",
                      "image/avif": "avif"}
_DROP_UPLOAD_MAX = 10 * 1024 * 1024


@router.post("/drop/upload")
async def drop_upload(business_id: str = FormField(...),
                      slot: str = FormField(...),
                      file: UploadFile = File(...),
                      session: UserSession = Depends(sb_clients.authed_request)
                      ) -> Dict[str, Any]:
    """ONE gesture: the owner clicks a drop slot in the Studio, picks a
    photo, and this uploads it (site_images bucket) AND fills the frame
    (fill_drop_slot persistence) in a single call."""
    _require_owner(business_id, session.user.id)
    ext = _DROP_UPLOAD_MIMES.get((file.content_type or "").lower())
    if not ext:
        raise HTTPException(400, "jpeg, png, webp, or avif only")
    data = await file.read()
    if not data:
        raise HTTPException(400, "empty file")
    if len(data) > _DROP_UPLOAD_MAX:
        raise HTTPException(400, "image too large (10 MB max)")
    import time as _time
    from agents.slot_system.dalle_client import _upload_site_image
    safe_slot = re.sub(r"[^a-zA-Z0-9_-]", "_", slot)[:60]
    path = f"{business_id}/drop_{safe_slot}_{int(_time.time())}.{ext}"
    url = _upload_site_image(path, data, file.content_type or "image/jpeg")
    if not url:
        raise HTTPException(502, "storage upload failed — try again")
    fill = drop_fill(DropFillBody(business_id=business_id, slot=slot,
                                  url=url), session)
    return {**fill, "url": url}


class RefreshBody(BaseModel):
    business_id: str


@router.post("/refresh")
def refresh_composed(body: RefreshBody,
                     session: UserSession = Depends(sb_clients.authed_request)) -> Dict[str, Any]:
    """Re-render a composed site from its stored spec (no LLM) so changes made
    OUTSIDE the site editor — new/edited/reordered gallery photos in the Media
    Library, etc. — appear without a full recompose. Owner-gated,
    fire-and-forget (the re-render runs in the background)."""
    _require_owner(body.business_id, session.user.id)
    refresh_if_composed_async(body.business_id)
    return {"ok": True, "refreshing": True}


# ─── Custom domain (Tier 1 — "connect a domain you own") ─────────────
# A practitioner points a domain they bought elsewhere at their site. Flow:
#   connect → we store it pending + a TXT ownership token + DNS instructions
#   verify  → we DNS-check the TXT token; on match the domain is verified
# HTTPS/cert issuance for the domain is an INFRA step (the domain must be
# added to the hosting platform) — tracked separately.
_PLATFORM_DOMAIN = "mysolutionist.app"
_DOMAIN_RE = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)(\.[a-z0-9-]{1,63})+$")


def _normalize_domain(raw: str) -> str:
    d = str(raw or "").strip().lower()
    d = re.sub(r"^https?://", "", d)
    d = d.split("/")[0].split("?")[0].strip().strip(".")
    if d.startswith("www."):
        d = d[4:]
    return d


def _dns_txt_contains(name: str, token: str) -> bool:
    """DNS-over-HTTPS TXT lookup (dependency-free). True if `token` appears in
    any TXT record for `name`."""
    try:
        r = httpx.get("https://dns.google/resolve",
                      params={"name": name, "type": "TXT"}, timeout=8.0)
        if r.status_code >= 400:
            return False
        for ans in (r.json().get("Answer") or []):
            if token in str(ans.get("data") or "").replace('"', ""):
                return True
    except Exception as e:
        logger.info(f"[domain] TXT lookup failed for {name}: {e}")
    return False


def _load_site_cfg(business_id: str):
    rows = sb_clients.sb_get_as_service(
        f"/business_sites?business_id=eq.{business_id}"
        f"&select=slug,site_config&order=updated_at.desc&limit=1") or []
    if not rows:
        return None, None, None
    return rows[0].get("slug") or "", dict(rows[0].get("site_config") or {}), rows[0]


class DomainConnectBody(BaseModel):
    business_id: str
    domain: str


@router.post("/domain/connect")
def connect_domain(body: DomainConnectBody,
                   session: UserSession = Depends(sb_clients.authed_request)) -> Dict[str, Any]:
    """Save a custom domain the practitioner owns as PENDING + return the DNS
    records they must add (an ownership TXT token + how to point the domain)."""
    _require_owner(body.business_id, session.user.id)
    domain = _normalize_domain(body.domain)
    if not domain or not _DOMAIN_RE.match(domain) or domain.endswith(_PLATFORM_DOMAIN):
        raise HTTPException(400, "Enter a valid domain you own, like yourbusiness.com")
    # Uniqueness — a domain can't be claimed by two sites.
    claimed = sb_clients.sb_get_as_service(
        f"/business_sites?site_config->>custom_domain=eq.{domain}"
        f"&select=business_id&limit=1") or []
    if claimed and claimed[0].get("business_id") != body.business_id:
        raise HTTPException(409, "That domain is already connected to another site.")
    slug, cfg, _row = _load_site_cfg(body.business_id)
    if cfg is None:
        raise HTTPException(404, "No site yet — compose your site first.")
    import secrets
    token = cfg.get("custom_domain_token") or ("sol-verify-" + secrets.token_hex(12))
    cfg["custom_domain"] = domain
    cfg["custom_domain_status"] = "pending"
    cfg["custom_domain_token"] = token
    # Cloudflare for SaaS: register the custom hostname so Cloudflare issues +
    # auto-renews the TLS cert and fronts the domain (scales past Railway's
    # per-service cap). Fail-open to plain ownership verification.
    # Certs are PER HOSTNAME, so www needs its own registration — without it,
    # www serves no cert at all (HANDSHAKE_FAILURE) even though our own DNS
    # instructions tell the practitioner to point www here.
    import cloudflare_saas
    cf = cloudflare_saas.create_custom_hostname(domain) if cloudflare_saas.enabled() else None
    cf_www = (cloudflare_saas.create_custom_hostname(f"www.{domain}", apex=domain)
              if cf else None)
    if cf:
        cfg["custom_domain_cf_id"] = cf.get("id")
    if cf_www:
        cfg["custom_domain_cf_www_id"] = cf_www.get("id")
    sb_clients.sb_patch_as_service(
        f"/business_sites?business_id=eq.{body.business_id}", {"site_config": cfg})
    if cf:
        return {"ok": True, "domain": domain, "status": "pending",
                "cert": "cloudflare",
                "dns": (cf["dns"] or []) + ((cf_www or {}).get("dns") or [])}
    return {
        "ok": True, "domain": domain, "status": "pending", "cert": "manual",
        "dns": [
            {"type": "TXT", "host": f"_solutionist-verify.{domain}", "value": token,
             "note": "Proves you own the domain."},
            {"type": "CNAME", "host": "www", "value": f"{slug}.{_PLATFORM_DOMAIN}",
             "note": f"Points www.{domain} at your site."},
            {"type": "ALIAS/ANAME (or A)", "host": "@", "value": f"{slug}.{_PLATFORM_DOMAIN}",
             "note": ("Points the bare domain at your site. If your registrar has no "
                      "ALIAS/ANAME, use its 'forward root to www' option instead.")},
        ],
    }


class DomainVerifyBody(BaseModel):
    business_id: str


@router.post("/domain/verify")
def verify_domain(body: DomainVerifyBody,
                  session: UserSession = Depends(sb_clients.authed_request)) -> Dict[str, Any]:
    """Check the ownership TXT record; mark the domain verified on match."""
    _require_owner(body.business_id, session.user.id)
    _slug, cfg, _row = _load_site_cfg(body.business_id)
    if cfg is None:
        raise HTTPException(404, "No site found.")
    domain = cfg.get("custom_domain")
    if not domain:
        raise HTTPException(400, "No domain connected yet.")
    # Cloudflare path: the domain is verified once BOTH the hostname and the
    # SSL cert are active on Cloudflare's edge. www is checked alongside —
    # and re-registered if missing, which backfills domains connected before
    # www registration existed — but never blocks verification: the apex
    # governs "verified", www reports its own state.
    import cloudflare_saas
    if cloudflare_saas.enabled():
        st = cloudflare_saas.hostname_status(domain) or {}
        hs, ss = st.get("hostname_status"), st.get("ssl_status")
        www = f"www.{domain}"
        st_www = cloudflare_saas.hostname_status(www, apex=domain) or {}
        if not st_www.get("found"):
            # Self-heal (create is idempotent): connected pre-www-fix.
            created = cloudflare_saas.create_custom_hostname(www, apex=domain)
            if created:
                cfg["custom_domain_cf_www_id"] = created.get("id")
                st_www = {"found": True, **created}
                # Persist now — the pending path below returns without patching.
                sb_clients.sb_patch_as_service(
                    f"/business_sites?business_id=eq.{body.business_id}",
                    {"site_config": cfg})
        www_ok = bool(st_www.get("active"))
        www_dns = st_www.get("dns") or []
        if st.get("active"):
            cfg["custom_domain_status"] = "verified"
            sb_clients.sb_patch_as_service(
                f"/business_sites?business_id=eq.{body.business_id}", {"site_config": cfg})
            message = ("Your domain is live over HTTPS. 🎉" if www_ok else
                       (f"Your domain is live over HTTPS. 🎉 The www version "
                        f"({www}) is still finishing — make sure its records "
                        "below are added, then check back."))
            return {"ok": True, "status": "verified", "domain": domain,
                    "domain_ok": True, "cert_ok": True, "www_ok": www_ok,
                    "dns": ([] if www_ok else www_dns),
                    "message": message}
        domain_ok = (hs == "active")
        cert_ok = (ss == "active")
        if not domain_ok:
            message = ("Waiting on your domain's DNS. Add the CNAME record above at your "
                       "domain provider — DNS can take a few minutes to a few hours to "
                       "point here, then check back.")
        elif not cert_ok:
            message = ("Your domain is connected — now the HTTPS certificate is being "
                       "issued. Make sure the SSL validation record (the TXT whose name "
                       "starts with '_acme-challenge') is added at your domain provider, "
                       "then check back in a few minutes.")
        else:
            message = "Almost there — finishing setup. Check back in a moment."
        return {"ok": False, "status": "pending", "domain": domain,
                "dns": (st.get("dns") or []) + www_dns,
                "domain_ok": domain_ok, "cert_ok": cert_ok, "www_ok": www_ok,
                "hostname_status": hs, "ssl_status": ss, "message": message}
    # Manual fallback (no Cloudflare configured): ownership TXT check.
    token = cfg.get("custom_domain_token")
    if not token:
        raise HTTPException(400, "No domain connected yet.")
    if _dns_txt_contains(f"_solutionist-verify.{domain}", token):
        cfg["custom_domain_status"] = "verified"
        sb_clients.sb_patch_as_service(
            f"/business_sites?business_id=eq.{body.business_id}", {"site_config": cfg})
        return {"ok": True, "status": "verified", "domain": domain}
    return {"ok": False, "status": "pending", "domain": domain,
            "message": ("We couldn't find the verification record yet. DNS changes "
                        "can take a few minutes to a few hours — add the TXT record, "
                        "then try again.")}


@router.post("/domain/disconnect")
def disconnect_domain(body: DomainVerifyBody,
                      session: UserSession = Depends(sb_clients.authed_request)) -> Dict[str, Any]:
    """Remove the custom domain; the site keeps its free subdomain."""
    _require_owner(body.business_id, session.user.id)
    _slug, cfg, _row = _load_site_cfg(body.business_id)
    if cfg is None:
        raise HTTPException(404, "No site found.")
    domain = cfg.get("custom_domain")
    if domain:
        try:
            import cloudflare_saas
            cloudflare_saas.delete_custom_hostname(domain)
            cloudflare_saas.delete_custom_hostname(f"www.{domain}")
        except Exception:
            pass
    for k in ("custom_domain", "custom_domain_status", "custom_domain_token",
              "custom_domain_cf_id", "custom_domain_cf_www_id"):
        cfg.pop(k, None)
    sb_clients.sb_patch_as_service(
        f"/business_sites?business_id=eq.{body.business_id}", {"site_config": cfg})
    return {"ok": True, "disconnected": True}


class SiteVisibilityBody(BaseModel):
    business_id: str
    offline: bool


@router.post("/site/visibility")
def set_site_visibility(body: SiteVisibilityBody,
                        session: UserSession = Depends(sb_clients.authed_request)) -> Dict[str, Any]:
    """Take the public site offline (a calm 'back soon' page) or bring it
    back online. Reversible in one click. The editor preview is unaffected —
    only the public address (subdomain + custom domain) is gated — so the
    practitioner can keep working while visitors see the maintenance page."""
    _require_owner(body.business_id, session.user.id)
    _slug, cfg, _row = _load_site_cfg(body.business_id)
    if cfg is None:
        raise HTTPException(404, "No site yet — compose your site first.")
    cfg["offline"] = bool(body.offline)
    sb_clients.sb_patch_as_service(
        f"/business_sites?business_id=eq.{body.business_id}", {"site_config": cfg})
    return {"ok": True, "offline": bool(body.offline)}


@router.get("/composition/{business_id}")
def get_spec(business_id: str,
             session: UserSession = Depends(sb_clients.authed_request)) -> Dict[str, Any]:
    """The composition trust surface: what got built, whether the
    rationale applied, the conformance report, and any stale overrides.

    ROUTE RENAMED (audit 2026-08-01). This was a SECOND
    `@router.get("/spec/{business_id}")` on the same router — FastAPI
    matches in registration order, so `get_design_spec` (line ~4851,
    which returns the Blueprint document as {"spec": …}) always won and
    everything below was unreachable. SiteComposerPanel gated on
    `j?.ok`, which the winning handler never returns, so the panel sat
    in its pre-compose state forever and dro_status / quality_report /
    stale_overrides could not be fetched by anything, ever.

    Two handlers, two jobs, two paths now:
      GET /composer/spec/{id}         → the Blueprint (design_spec)
      GET /composer/composition/{id}  → what actually got composed
    """
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
    creative = _creative_plus_story(ctx)

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
    src = cfg.get("html_source")
    if src == "module-composer" and cfg.get("page_spec"):
        spec = sanitize_spec(cfg["page_spec"], ctx)
        render_and_persist(business_id, spec, ctx)
        return True
    # TOUCHABLE PREVIEW (2026-07-25): canvas/v2 pages re-render too —
    # render_and_persist reuses the STORED canvas document on non-full
    # passes and re-applies text + color overrides onto it. Without
    # this, an Edit Mode save persisted to the database but NEVER
    # reached the served page of a v2 site (the trigger was a no-op).
    _cv = cfg.get("canvas") if isinstance(cfg.get("canvas"), dict) else {}
    if src == "canvas" and str((_cv or {}).get("html") or "").strip():
        spec = sanitize_spec(cfg.get("page_spec") or {"sections": []}, ctx)
        render_and_persist(business_id, spec, ctx)
        return True
    return False


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
                         "offerings, gallery, testimonials, cta or contact section"}

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
