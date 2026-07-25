# discovery.py
# ─────────────────────────────────────────────────────────────────────
# PHASE 1 of the revamp (docs/REVAMP_TARGET.md, signed 2026-07-24) —
# THE ONE DOSSIER + recon + the reference-site study.
#
# Discovery's product is `site_config.discovery_dossier`: the single
# JSON home the Director reads. No more hunting across seven surfaces
# (the brand-mark bug was exactly that hunt failing).
#
# This module ships the foundation:
#   - get/save dossier (merge-safe: recon never clobbers what the
#     practitioner said — source vocabulary per DISCOVERY_AGENT.md §5)
#   - recon_dossier(): migrates what the system already holds (brand
#     kit mark, gallery, slots, prefs, contact, vertical) in with
#     source "recon"
#   - study_reference(): Playwright screenshots a loved/hated site →
#     vision call extracts transferable RULES + named BANS + a TASTE
#     READING with confidence per pair (Revision 2 extended contract).
#     Failures degrade to skip-and-record (Footnote B): the dossier
#     notes WHICH reference couldn't be captured and why.
#
# The conversational agent (Chief script + Studio surface) is Phase 1b;
# from day one the spec author reads whatever dossier exists.
# ─────────────────────────────────────────────────────────────────────

from __future__ import annotations

import base64
import json
import llm_call
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("discovery")

DOSSIER_VERSION = 1
# sources that outrank recon — never clobbered by a recon refresh
_PRACTITIONER_SOURCES = ("asked", "flipped", "inferred-confirmed")


def _empty_dossier() -> Dict[str, Any]:
    return {
        "version": DOSSIER_VERSION,
        "artifacts": {"brand_mark_url": None, "work": [],
                       "portrait_url": None, "references": []},
        "identity": {},
        "taste": {},
        # Design Coach sections (2026-07-25): the conversational door
        # captures the owner's world, story, and signature moment in
        # their own words — the Director's richest material.
        "world": {},
        "story": {},
        "signature": {},
        "truth": {"proven_stats": [], "colors_must": [], "colors_avoid": []},
        "vertical": {"type": None, "answers": {}},
        "gaps": [],
        "confirmed_brief": None,
        "confirmed_at": None,
        "updated_at": None,
    }


# ─── persistence (site row pattern) ──────────────────────────────────

def _site_row(business_id: str):
    import sb_clients
    rows = sb_clients.sb_get_as_service(
        f"/business_sites?business_id=eq.{business_id}"
        "&select=id,site_config&limit=1") or []
    return rows[0] if rows else None


def get_dossier(business_id: str) -> Optional[Dict[str, Any]]:
    row = _site_row(business_id)
    if not row:
        return None
    d = (row.get("site_config") or {}).get("discovery_dossier")
    return d if isinstance(d, dict) else None


def save_dossier(business_id: str, dossier: Dict[str, Any]) -> bool:
    import sb_clients
    row = _site_row(business_id)
    if not row:
        return False
    cfg = dict(row.get("site_config") or {})
    dossier["updated_at"] = datetime.now(timezone.utc).isoformat()
    cfg["discovery_dossier"] = dossier
    sb_clients.sb_patch_as_service(
        f"/business_sites?id=eq.{row['id']}", {"site_config": cfg})
    return True


# ─── recon (Step 0) ──────────────────────────────────────────────────

def _src_of(field: Any) -> str:
    if isinstance(field, dict):
        return str(field.get("source") or "")
    return ""


def merge_recon(existing: Dict[str, Any],
                fresh: Dict[str, Any]) -> Dict[str, Any]:
    """Recon fills gaps; it NEVER clobbers what the practitioner said.
    A field whose source is asked/flipped/inferred-confirmed survives
    every recon refresh; recon-sourced and empty fields update. Pure
    (testable)."""
    out = json.loads(json.dumps(existing))  # deep copy
    for section in ("identity", "taste"):
        tgt = out.setdefault(section, {})
        for k, v in (fresh.get(section) or {}).items():
            if _src_of(tgt.get(k)) not in _PRACTITIONER_SOURCES:
                tgt[k] = v
    # artifacts: fill-if-empty per key; work/references union by url
    a_out = out.setdefault("artifacts", {})
    a_new = fresh.get("artifacts") or {}
    for k in ("brand_mark_url", "portrait_url"):
        if not a_out.get(k) and a_new.get(k):
            a_out[k] = a_new[k]
    have = {w.get("url") for w in (a_out.get("work") or [])
            if isinstance(w, dict)}
    a_out.setdefault("work", [])
    for w in (a_new.get("work") or []):
        if isinstance(w, dict) and w.get("url") and w["url"] not in have:
            a_out["work"].append(w)
            have.add(w["url"])
    # truth: recon may add mark-derived musts / prefs-derived avoids,
    # never remove practitioner entries
    t_out = out.setdefault("truth", {})
    for key in ("colors_must", "colors_avoid"):
        seen = {json.dumps(x, sort_keys=True)
                for x in (t_out.get(key) or [])}
        t_out.setdefault(key, [])
        for x in ((fresh.get("truth") or {}).get(key) or []):
            if json.dumps(x, sort_keys=True) not in seen:
                t_out[key].append(x)
    # vertical type: fill if empty
    v_out = out.setdefault("vertical", {})
    v_new = fresh.get("vertical") or {}
    if not v_out.get("type") and v_new.get("type"):
        v_out["type"] = v_new["type"]
    for k, v in (v_new.get("answers") or {}).items():
        v_out.setdefault("answers", {})
        if _src_of(v_out["answers"].get(k)) not in _PRACTITIONER_SOURCES:
            v_out["answers"][k] = v
    return out


def recon_dossier(business_id: str) -> Optional[Dict[str, Any]]:
    """Build/refresh the dossier from what the system already holds.
    Everything lands with source 'recon' (or 'recon-mark'). Returns the
    merged, persisted dossier."""
    import sb_clients
    biz_rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{business_id}"
        "&select=name,type,settings&limit=1") or []
    if not biz_rows:
        return None
    biz = biz_rows[0]
    settings = biz.get("settings") or {}
    bk = settings.get("brand_kit") if isinstance(settings.get("brand_kit"), dict) else {}
    logos = bk.get("logos") if isinstance(bk.get("logos"), dict) else {}
    prefs = settings.get("site_prefs") if isinstance(settings.get("site_prefs"), dict) else {}

    fresh = _empty_dossier()
    fresh["artifacts"]["brand_mark_url"] = (
        logos.get("primary") or bk.get("logo_url") or None)
    fresh["vertical"]["type"] = (
        settings.get("custom_type") or biz.get("type") or None)

    # slots + gallery from the site row
    row = _site_row(business_id)
    cfg = (row.get("site_config") if row else None) or {}
    slots = cfg.get("slots") if isinstance(cfg.get("slots"), dict) else {}
    for name, rec in sorted(slots.items()):
        if not isinstance(rec, dict) or rec.get("removed"):
            continue
        cu = (rec.get("custom_url") or "").strip()
        if not cu:
            continue
        if "about" in name or "portrait" in name or "profile" in name:
            fresh["artifacts"]["portrait_url"] = cu
        else:
            fresh["artifacts"]["work"].append(
                {"url": cu, "note": f"owner upload ({name})",
                 "source": "recon"})
    ml = settings.get("media_library")
    gallery = (ml.get("gallery") if isinstance(ml, dict) else None) or []
    for g in gallery:
        if isinstance(g, dict) and (g.get("url") or "").strip():
            fresh["artifacts"]["work"].append(
                {"url": g["url"].strip(),
                 "note": g.get("alt") or g.get("caption") or "",
                 "source": "recon"})

    # prefs → avoids (source recon; the agent still asks WHY later)
    avoid = prefs.get("avoid")
    avoids = avoid if isinstance(avoid, list) else (
        [avoid] if isinstance(avoid, str) and avoid.strip() else [])
    for a in avoids[:6]:
        fresh["truth"]["colors_avoid"].append(
            {"color": str(a)[:60], "why": None, "source": "recon"})

    existing = get_dossier(business_id) or _empty_dossier()
    merged = merge_recon(existing, fresh)
    # gaps: honest, recomputed each recon
    gaps = []
    if not merged["artifacts"].get("brand_mark_url"):
        gaps.append("brand_mark_missing")
    if not merged["artifacts"].get("work"):
        gaps.append("work_missing")
    if not merged["artifacts"].get("portrait_url"):
        gaps.append("portrait_missing")
    if not merged["artifacts"].get("references"):
        gaps.append("references_missing")
    merged["gaps"] = sorted(set(gaps)
                            | {g for g in (existing.get("gaps") or [])
                               if g.endswith("_pending")})
    save_dossier(business_id, merged)
    return merged


# ─── the reference-site study (§4, extended contract) ────────────────

_STUDY_SYSTEM = """You are studying a website the practitioner pointed at, to extract what a creative director can LEARN from it — transferable rules only, NEVER identity. You never copy a brand; you name the disciplines that make the page work (or fail).

Return JSON ONLY:
{"rules": ["transferable rule, e.g. 'hairline dividers; one accent doing one job'", ... up to 6],
 "bans": ["named ban if this is a HATED site, e.g. 'no parallax', ...],
 "taste": {"ground": {"value": "dark|light", "confidence": 0.0-1.0},
           "density": {"value": "spacious|rich", "confidence": ...},
           "carrier": {"value": "type|photo", "confidence": ...},
           "edges": {"value": "sharp|soft", "confidence": ...},
           "era": {"value": "modern|classic", "confidence": ...},
           "tone": {"value": "playful|serious", "confidence": ...},
           "motion": {"value": "signature-moment|gentle|still", "confidence": ...}}}
For a LOVED site: rules carry the learning. For a HATED site: bans carry it (rules may be empty). Confidence reflects how clearly THIS site expresses the pair."""


def _screenshot_url(url: str) -> Optional[List[bytes]]:
    """Navigate + screenshot at 390/1440. None on any failure (the
    caller records the failure loudly — Footnote B)."""
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return None
    shots: List[bytes] = []
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            try:
                for width in (390, 1440):
                    page = browser.new_page(
                        viewport={"width": width, "height": 900})
                    page.goto(url, wait_until="domcontentloaded",
                              timeout=20000)
                    page.wait_for_timeout(1200)
                    shots.append(page.screenshot(type="jpeg", quality=55))
                    page.close()
            finally:
                browser.close()
    except Exception as e:
        logger.info(f"[discovery] screenshot failed for {url}: "
                    f"{type(e).__name__}: {e}")
        return None
    return shots


def study_reference(business_id: str, url: str, verdict: str,
                    why: str = "") -> Dict[str, Any]:
    """Study one loved/hated reference; append the entry to the dossier.
    ALWAYS returns an entry — failures are recorded facts, never silent
    gaps and never a stalled intake."""
    verdict = "hate" if str(verdict).lower().startswith("h") else "love"
    entry: Dict[str, Any] = {"url": url, "verdict": verdict,
                             "why": (why or "")[:200],
                             "studied_at": datetime.now(timezone.utc).isoformat()}
    shots = _screenshot_url(url)
    if not shots:
        entry["error"] = ("could not capture (bot-blocked, dead link, "
                          "or timeout) — the Director is told what it "
                          "couldn't see")
    else:
        try:
            from anthropic import Anthropic
            import model_ladder
            key = os.environ.get("ANTHROPIC_API_KEY")
            if not key:
                raise RuntimeError("no ANTHROPIC_API_KEY")
            content: List[Dict[str, Any]] = []
            for w, shot in zip((390, 1440), shots):
                content.append({"type": "text", "text": f"{w}px:"})
                content.append({"type": "image", "source": {
                    "type": "base64", "media_type": "image/jpeg",
                    "data": base64.b64encode(shot).decode()}})
            content.append({"type": "text",
                            "text": f"The practitioner marked this site "
                                    f"{verdict.upper()}"
                                    + (f' ("{why}")' if why else "")
                                    + ". Extract per the contract. JSON only."})
            client = llm_call.sdk_client(key=key, timeout=90.0, max_retries=1)

            def _do(model: str, max_tokens: int, timeout: float):
                return client.messages.create(
                    model=model, max_tokens=max_tokens,
                    system=_STUDY_SYSTEM,
                    messages=[{"role": "user", "content": content}],
                    timeout=timeout,
                    **model_ladder.sampling_kwargs(model, None))

            msg, _used = model_ladder.call_with_ladder(
                _do, model=(os.environ.get("DISCOVERY_STUDY_MODEL")
                            or "claude-sonnet-4-5-20250929").strip(),
                task="discovery_study", business_id=business_id,
                max_tokens=900)
            raw = "".join(b.text for b in msg.content
                          if getattr(b, "type", None) == "text")
            import re as _re
            m = _re.search(r"\{.*\}", raw, _re.DOTALL)
            data = json.loads(m.group(0)) if m else {}
            entry["rules"] = [str(r)[:160] for r in (data.get("rules") or [])][:6]
            entry["bans"] = [str(b)[:120] for b in (data.get("bans") or [])][:6]
            taste = data.get("taste")
            if isinstance(taste, dict):
                entry["taste"] = taste
        except Exception as e:
            entry["error"] = f"study call failed: {type(e).__name__}: {e}"
            logger.warning(f"[discovery] reference study failed for "
                           f"{url}: {e}")

    dossier = get_dossier(business_id) or _empty_dossier()
    refs = dossier.setdefault("artifacts", {}).setdefault("references", [])
    refs[:] = [r for r in refs if r.get("url") != url] + [entry]
    save_dossier(business_id, dossier)
    return entry


# ─── practitioner writes (Phase 1b) ──────────────────────────────────

_TASTE_PAIRS = ("ground", "density", "carrier", "edges", "era",
                "tone", "motion")


def apply_practitioner_patch(existing: Dict[str, Any],
                             patch: Dict[str, Any]) -> Dict[str, Any]:
    """Merge a practitioner-sourced patch into the dossier. Only
    practitioner sources may ride this door (asked / flipped /
    inferred-confirmed) — recon and inference have their own paths.
    Pure (testable). Unknown sections/leaves are ignored."""
    out = json.loads(json.dumps(existing))

    def _valid_leaf(v: Any) -> bool:
        return (isinstance(v, dict) and "value" in v
                and str(v.get("source")) in _PRACTITIONER_SOURCES)

    for section in ("identity", "taste", "world", "story", "signature",
                    "meta"):
        for k, v in (patch.get(section) or {}).items():
            if _valid_leaf(v):
                out.setdefault(section, {})[k] = v
    truth = patch.get("truth") or {}
    if isinstance(truth.get("proven_stats"), list):
        out.setdefault("truth", {})["proven_stats"] = [
            {"label": str(s.get("label"))[:80],
             "value": str(s.get("value"))[:40],
             "proof": str(s.get("proof") or "")[:160]}
            for s in truth["proven_stats"][:8]
            if isinstance(s, dict) and s.get("label") and s.get("value")]
    if isinstance(truth.get("colors_avoid"), list):
        keep = [a for a in (out.get("truth", {}).get("colors_avoid") or [])
                if _src_of(a) == "recon"]
        out.setdefault("truth", {})["colors_avoid"] = keep + [
            {"color": str(a.get("color"))[:60],
             "why": str(a.get("why") or "")[:200], "source": "asked"}
            for a in truth["colors_avoid"][:6]
            if isinstance(a, dict) and a.get("color")]
    for k, v in ((patch.get("vertical") or {}).get("answers") or {}).items():
        if _valid_leaf(v):
            out.setdefault("vertical", {}).setdefault("answers", {})[k] = v
    if isinstance(patch.get("confirmed_brief"), str) \
            and patch["confirmed_brief"].strip():
        out["confirmed_brief"] = patch["confirmed_brief"].strip()[:1200]
        out["confirmed_at"] = datetime.now(timezone.utc).isoformat()
        # confirmation upgrades any remaining bare inferences: an
        # unconfirmed inference is a GAP, not a value (§5 invariant)
        for k, v in list((out.get("taste") or {}).items()):
            if isinstance(v, dict) and v.get("source") == "inferred":
                v["source"] = "inferred-confirmed"
    return out


def answer(business_id: str, patch: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The practitioner-write endpoint's engine."""
    existing = get_dossier(business_id) or _empty_dossier()
    merged = apply_practitioner_patch(existing, patch)
    if not save_dossier(business_id, merged):
        return None
    return merged


# ─── the derived-taste reading (Phase 1b, Revision 2 §3) ─────────────

_DERIVE_SYSTEM = """You are reading a business's design taste from its real artifacts: the brand mark, the owner's work, and taste readings extracted from reference sites they love. Synthesize ONE verdict per pair with a confidence score. This is inference for the owner to CONFIRM — it will be shown to them for a yes; do not hedge into the middle, commit to the likelier pole.

Return JSON ONLY:
{"taste": {"ground": {"value": "dark|light", "confidence": 0.0-1.0},
           "density": {"value": "spacious|rich", "confidence": ...},
           "carrier": {"value": "type|photo", "confidence": ...},
           "edges": {"value": "sharp|soft", "confidence": ...},
           "era": {"value": "modern|classic", "confidence": ...},
           "tone": {"value": "playful|serious", "confidence": ...},
           "motion": {"value": "signature-moment|gentle|still", "confidence": ...}}}"""


def derive_taste(business_id: str) -> Optional[Dict[str, Any]]:
    """One vision call over the mark + work + reference readings →
    the seven pair readings, written with source 'inferred' (pending
    the practitioner's confirm). Pairs the practitioner already
    answered are NEVER overwritten. Fail-open: on any failure the
    dossier is returned unchanged with a recorded gap."""
    dossier = get_dossier(business_id) or _empty_dossier()
    arts = dossier.get("artifacts") or {}
    urls: List[str] = []
    if (arts.get("brand_mark_url") or "").strip():
        urls.append(arts["brand_mark_url"].strip())
    for w in (arts.get("work") or [])[:5]:
        u = (w.get("url") or "").strip() if isinstance(w, dict) else ""
        if u and u not in urls:
            urls.append(u)
    ref_readings = [
        {"verdict": r.get("verdict"), "why": r.get("why"),
         "taste": r.get("taste")}
        for r in (arts.get("references") or [])
        if isinstance(r, dict) and r.get("taste")]
    if not urls and not ref_readings:
        gaps = set(dossier.get("gaps") or [])
        gaps.add("taste_underivable_no_artifacts")
        dossier["gaps"] = sorted(gaps)
        save_dossier(business_id, dossier)
        return dossier
    try:
        from anthropic import Anthropic
        import model_ladder
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise RuntimeError("no ANTHROPIC_API_KEY")
        content: List[Dict[str, Any]] = []
        for i, u in enumerate(urls, 1):
            label = ("THE BRAND MARK" if i == 1 and arts.get("brand_mark_url")
                     else f"WORK {i}")
            content.append({"type": "text", "text": f"{label}: {u}"})
            content.append({"type": "image",
                            "source": {"type": "url", "url": u}})
        if ref_readings:
            content.append({"type": "text",
                            "text": "REFERENCE READINGS (from sites they "
                                    "love/hate):\n"
                                    + json.dumps(ref_readings)[:3000]})
        content.append({"type": "text", "text": "Synthesize. JSON only."})
        client = llm_call.sdk_client(key=key, timeout=90.0, max_retries=1)

        def _do(model: str, max_tokens: int, timeout: float):
            return client.messages.create(
                model=model, max_tokens=max_tokens, system=_DERIVE_SYSTEM,
                messages=[{"role": "user", "content": content}],
                timeout=timeout,
                **model_ladder.sampling_kwargs(model, None))

        msg, _used = model_ladder.call_with_ladder(
            _do, model=(os.environ.get("DISCOVERY_STUDY_MODEL")
                        or "claude-sonnet-4-5-20250929").strip(),
            task="discovery_derive", business_id=business_id,
            max_tokens=600)
        raw = "".join(b.text for b in msg.content
                      if getattr(b, "type", None) == "text")
        import re as _re
        m = _re.search(r"\{.*\}", raw, _re.DOTALL)
        taste = (json.loads(m.group(0)) if m else {}).get("taste") or {}
    except Exception as e:
        logger.warning(f"[discovery] derive_taste failed: "
                       f"{type(e).__name__}: {e}")
        gaps = set(dossier.get("gaps") or [])
        gaps.add("taste_derivation_failed")
        dossier["gaps"] = sorted(gaps)
        save_dossier(business_id, dossier)
        return dossier

    t_out = dossier.setdefault("taste", {})
    for pair in _TASTE_PAIRS:
        v = taste.get(pair)
        if not isinstance(v, dict) or not v.get("value"):
            continue
        if _src_of(t_out.get(pair)) in _PRACTITIONER_SOURCES:
            continue                       # their word stands
        t_out[pair] = {"value": str(v["value"])[:40],
                       "confidence": float(v.get("confidence") or 0.5),
                       "source": "inferred"}
    dossier["gaps"] = sorted(set(dossier.get("gaps") or [])
                             - {"taste_underivable_no_artifacts",
                                "taste_derivation_failed"})
    save_dossier(business_id, dossier)
    return dossier


# ─── the Director's view ─────────────────────────────────────────────

def dossier_digest(dossier: Optional[Dict[str, Any]]) -> str:
    """Compact JSON for the spec author's prompt. '' when nothing
    useful exists. Screenshots don't ride (rules/taste text does)."""
    if not isinstance(dossier, dict):
        return ""
    slim = {k: v for k, v in dossier.items()
            if k in ("artifacts", "identity", "taste", "truth",
                     "world", "story", "signature",
                     "vertical", "gaps", "confirmed_brief") and v}
    refs = ((slim.get("artifacts") or {}).get("references")) or []
    if not any((slim.get(k)) for k in
               ("identity", "taste", "world", "story", "signature",
                "confirmed_brief")) and not refs:
        # recon-only artifact lists already ride the inventory — don't
        # duplicate them into a second section for nothing
        return ""
    return json.dumps(slim, ensure_ascii=False, indent=1)[:8000]
