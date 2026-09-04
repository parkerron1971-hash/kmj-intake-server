"""
site_facts.py — ONE SET OF FACTS (2026-08-29, the builder bench).

KMJ's Blueprint said "CREATIVE CONSULTANCY · SINCE 2022" and "4 years
turning stuck into started". Neither number exists anywhere in the
system: the business was created 2026-04, the dossier and settings
carry no year. The Director invented a tenure, wrote it decidedly (as
its own prompt demands), and the builder's truth law — which traces
every number on the page back to REAL DATA — flagged the year and the
repair deleted it. Two authors, two ideas of what is true, and the
page paid for the argument on every build.

This module is the single place both read. build_facts() collects what
is actually on file — the founding date, the legal name, phone, city,
the doors that are ON with their exact urls, what is counted, the
dossier's proven stats — and facts_block() states it in one block that
rides the Director's prompt AND the builder's REAL DATA. A fact that is
not on file is said to be not on file, so nobody writes around the gap
by inventing.

tenure_claims() is the law the truth law could not express: "4 years"
is one digit, invisible to a 3+-digit trace, and the most common thing
an author invents.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("site_facts")

_YEAR_RE = re.compile(r"\b(19[5-9]\d|20[0-4]\d)\b")
_TENURE_RE = re.compile(
    r"\b(\d{1,2})\+?\s*(?:years?|yrs?)\b(?:\s+(?:of|in|turning|serving|strong|running|experience))?",
    re.IGNORECASE)


def _profile_row(business_id: str) -> Dict[str, Any]:
    try:
        import sb_clients
        rows = sb_clients.sb_get_as_service(
            f"/business_profiles?business_id=eq.{business_id}"
            "&select=formed_on,legal_name,phone,address_city,address_state&limit=1") or []
        return rows[0] if rows and isinstance(rows[0], dict) else {}
    except Exception as e:
        logger.info(f"[facts] business profile skipped: {e}")
        return {}


def _founded_year(settings: Dict[str, Any], profile: Dict[str, Any],
                  dossier: Dict[str, Any]) -> Optional[int]:
    """The founding year, from the places it can actually be written:
    the business profile's formation date, the document defaults' sticky
    'Year founded', a settings field, or a dossier truth stat that says
    so. Never the account's created_at — that is when they joined us."""
    cands: List[Any] = [
        (profile or {}).get("formed_on"),
        ((settings.get("doc_defaults") or {}) if isinstance(settings.get("doc_defaults"), dict) else {}).get("founded"),
        settings.get("founded"), settings.get("founded_year"), settings.get("year_founded"),
    ]
    for stat in ((dossier.get("truth") or {}).get("proven_stats") or []):
        text = " ".join(str(stat.get(k) or "") for k in ("stat", "label", "value")) \
            if isinstance(stat, dict) else str(stat)
        if re.search(r"found|since|establish|est\.", text, re.IGNORECASE):
            cands.append(text)
    for c in cands:
        if not c:
            continue
        m = _YEAR_RE.search(str(c))
        if m:
            return int(m.group(1))
    return None


_STATED_YEARS_RE = re.compile(r"\b(\d{1,2})\+?\s*(?:years?|yrs?)\b", re.IGNORECASE)


def stated_years(ctx: Dict[str, Any], dossier: Dict[str, Any]) -> List[int]:
    """THE OWNER'S OWN TENURE (2026-09-04, the barbershop bench). The
    tenure law only knew the founding year, so an owner who typed "I've
    been cutting 14 years" about a shop founded in 2021 watched the
    repair round strip the truest sentence on the page. A number of
    years the practitioner stated themselves — in their prompt, or in
    the discovery dossier's own-words sections — is a fact on file,
    exactly like a proven stat. Founding-year tenure stays a computed
    fact; this is the other kind."""
    texts: List[str] = [str((ctx or {}).get("owner_brief") or "")]
    for key in ("identity", "story", "world", "signature", "confirmed_brief"):
        v = (dossier or {}).get(key)
        if v:
            try:
                import json as _json
                texts.append(_json.dumps(v, ensure_ascii=False))
            except Exception:
                texts.append(str(v))
    out: List[int] = []
    for t in texts:
        for m in _STATED_YEARS_RE.finditer(t):
            n = int(m.group(1))
            if 1 <= n <= 80 and n not in out:
                out.append(n)
    return out


def build_facts(ctx: Dict[str, Any], business_id: str,
                profile: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    ctx = ctx if isinstance(ctx, dict) else {}
    settings = ctx.get("settings") if isinstance(ctx.get("settings"), dict) else {}
    biz = ctx.get("business") if isinstance(ctx.get("business"), dict) else {}
    contact = ctx.get("contact") if isinstance(ctx.get("contact"), dict) else {}
    cfg = (((ctx.get("site") or {}).get("site_config") or {})
           if isinstance(ctx.get("site"), dict) else {})
    dossier = cfg.get("discovery_dossier") if isinstance(cfg.get("discovery_dossier"), dict) else {}
    prof = profile if profile is not None else _profile_row(business_id)
    year = _founded_year(settings, prof, dossier)
    now = datetime.now(timezone.utc).year
    facts: Dict[str, Any] = {
        "name": str(biz.get("name") or ""),
        "legal_name": str(prof.get("legal_name") or ""),
        "founded_year": year,
        "years_in_business": (now - year) if year and year <= now else None,
        "phone": str(prof.get("phone") or contact.get("phone") or ""),
        "email": str(contact.get("email") or ""),
        "city": ", ".join(p for p in (str(prof.get("address_city") or ""),
                                       str(prof.get("address_state") or "")) if p),
        "hours": str(contact.get("hours") or ""),
        "offerings": len(ctx.get("offerings") or []) if isinstance(ctx.get("offerings"), list) else 0,
        "photos": len(ctx.get("gallery") or []) if isinstance(ctx.get("gallery"), list) else 0,
        "testimonials": len(ctx.get("testimonials") or []) if isinstance(ctx.get("testimonials"), list) else 0,
        "proven_stats": [],
        "stated_years": stated_years(ctx, dossier),
        "doors": [],
    }
    for stat in ((dossier.get("truth") or {}).get("proven_stats") or [])[:8]:
        if isinstance(stat, dict):
            label = str(stat.get("stat") or stat.get("label") or "").strip()
            value = str(stat.get("value") or "").strip()
            if label or value:
                facts["proven_stats"].append(f"{label}: {value}".strip(": "))
        elif isinstance(stat, str) and stat.strip():
            facts["proven_stats"].append(stat.strip())
    try:
        import builder_v2
        block = builder_v2.connected_systems_block(business_id, ctx)
        facts["doors"] = [ln[2:] for ln in block.splitlines() if ln.startswith("- ")]
    except Exception as e:
        logger.info(f"[facts] doors skipped: {e}")
    return facts


def facts_block(facts: Dict[str, Any]) -> str:
    """The one block both authors read. Every line is either a fact or
    the statement that the fact is not on file."""
    f = facts or {}
    lines: List[str] = []
    if f.get("founded_year"):
        yrs = f.get("years_in_business")
        lines.append(f"- Founded: {f['founded_year']}"
                     + (f" ({yrs} years in business)" if isinstance(yrs, int) and yrs >= 1 else ""))
    else:
        lines.append("- Founded: NOT ON FILE — do not state a founding year, "
                     "a 'since', or a number of years in business")
    if f.get("legal_name"):
        lines.append(f"- Legal name: {f['legal_name']}")
    lines.append(f"- Phone: {f['phone']}" if f.get("phone") else "- Phone: not on file — do not print one")
    lines.append(f"- Email: {f['email']}" if f.get("email") else "- Email: not on file — do not print one")
    if f.get("city"):
        lines.append(f"- Location: {f['city']}")
    if f.get("hours"):
        lines.append(f"- Hours: {f['hours']}")
    lines.append(f"- On file: {f.get('offerings', 0)} offerings, {f.get('photos', 0)} photos, "
                 f"{f.get('testimonials', 0)} testimonials — these are the only counts you may cite")
    if f.get("stated_years"):
        lines.append("- Years the owner stated in their own words (usable verbatim, "
                     "as the owner's tenure, never as the business's age): "
                     + ", ".join(f"{n} years" for n in f["stated_years"]))
    if f.get("proven_stats"):
        lines.append("- Proven stats (the owner's own, usable verbatim): "
                     + "; ".join(f["proven_stats"]))
    else:
        lines.append("- Proven stats: none on file — no client counts, percentages, "
                     "ratings or results may appear")
    for d in f.get("doors") or []:
        lines.append(f"- {d}")
    return ("THE FACTS (the only years, numbers, prices, counts and links the page "
            "may state; anything not listed here is unknown — write around it, "
            "never invent it):\n" + "\n".join(lines))


def tenure_claims(html_text: str, facts: Dict[str, Any]) -> List[str]:
    """'N years' on the page is a tenure claim; it must equal the years
    on file. With no founding year on file, any such claim is invented."""
    problems: List[str] = []
    yrs = (facts or {}).get("years_in_business")
    stated = {int(x) for x in ((facts or {}).get("stated_years") or []) if str(x).isdigit()}
    for m in _TENURE_RE.finditer(html_text or ""):
        n = int(m.group(1))
        if isinstance(yrs, int) and n == yrs:
            continue
        if n in stated:
            continue
        problems.append(
            f"TENURE CLAIM: '{m.group(0).strip()}' on the page — "
            + (f"the business has {yrs} years on file; say that or nothing."
               if isinstance(yrs, int) else
               "no founding year is on file, so no number of years may be claimed. Remove it."))
        if len(problems) >= 3:
            break
    return problems
