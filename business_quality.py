"""
business_quality.py — the second look a WHOLE BUSINESS gets.

build_quality reviews one module against what the intake asked for. This
reviews a business blueprint against what every business needs on day
one, whatever it sells. Kevin's brief (2026-09-06): a person brings the
idea of a business and Chief lays out everything it needs — so the
rubric is the checklist a good operator runs before opening the doors:

  get paid       something with a price, or a place money is recorded
  get found      a site brief with a headline and a first call to action
  a way in       a booking, an intake form, or a contact path
  keep records   at least one module — the business's memory
  follow up      at least one automation that fires without a person

Deterministic, no model call; the generator revises once against these
findings the same way it revises a module. A finding's message is the
instruction that would have prevented it.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List

from build_quality import Finding, QualityReport

_MONEY = re.compile(r"\b(invoice|invoic|payment|paid|pay|bill|deposit|retainer|fee|price|pricing|charge|sale|sales|revenue|order)\w*", re.I)
_WAY_IN = re.compile(r"\b(book|booking|appointment|schedule|intake|inquir|enquir|consult|sign.?up|register|reservation|request)\w*", re.I)


def _modules(bp: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [m for m in (bp.get("modules") or []) if isinstance(m, dict)]


def assess(bp: Dict[str, Any]) -> QualityReport:
    """The rubric over a blueprint dict (stage-one output: module intakes,
    offerings, forms, site brief, rails). Pure."""
    rep = QualityReport()
    mods = _modules(bp)
    offerings = [o for o in (bp.get("offerings") or []) if isinstance(o, dict)]
    forms = [f for f in (bp.get("forms") or []) if isinstance(f, dict)]
    site = bp.get("site") if isinstance(bp.get("site"), dict) else {}
    all_text = " ".join(
        f"{m.get('name', '')} {m.get('intake', '')} {m.get('why', '')}" for m in mods)

    # ─── keep records ───────────────────────────────────────────────────
    if not mods:
        rep.findings.append(Finding(
            "no_records", "revise", None,
            "a business with no module has no memory — add at least the one thing "
            "they will add to every day (clients, jobs, sessions, orders, expenses)"))

    # ─── get paid ───────────────────────────────────────────────────────
    priced = any(o.get("current_price") is not None for o in offerings)
    money_module = bool(_MONEY.search(all_text))
    if not priced and not money_module:
        rep.findings.append(Finding(
            "no_way_to_get_paid", "revise", None,
            "nothing in this business has a price and no module records money — add "
            "the offerings they sell (with prices where the idea gives them) or an "
            "invoices / payments module"))

    # ─── get found ──────────────────────────────────────────────────────
    if not (site.get("headline") or "").strip():
        rep.findings.append(Finding(
            "no_way_to_be_found", "revise", None,
            "write the site brief — a headline in the customer's words, a tagline, the "
            "pages, and the first thing a visitor should do"))
    elif not (site.get("primary_cta") or "").strip():
        rep.findings.append(Finding(
            "site_without_a_cta", "revise", None,
            "the site brief has no primary_cta — what should a visitor do first "
            "(book, call, request a quote)?"))

    # ─── a way in ───────────────────────────────────────────────────────
    way_in = bool(_WAY_IN.search(all_text)) or any(
        (f.get("form_type") or "intake") != "feedback" for f in forms)
    if not way_in:
        rep.findings.append(Finding(
            "no_way_in", "revise", None,
            "there is no door for a new customer — add a booking module, an intake "
            "form, or a request form so a stranger can become a client without a "
            "phone call"))

    # ─── follow up ──────────────────────────────────────────────────────
    follow = bool(re.search(r"\b(remind|reminder|overdue|follow.?up|alert|notify|tell me|when .* (reaches|hits|crosses))\w*", all_text, re.I))
    if mods and not follow:
        rep.findings.append(Finding(
            "no_follow_up", "revise", None,
            "no module's intake asks to be reminded of anything — say in at least one "
            "intake what should nudge them (an overdue invoice, a client not seen in "
            "30 days, a deadline), so the builder adds the trigger"))

    # ─── shape ──────────────────────────────────────────────────────────
    names = [(m.get("name") or "").strip().lower() for m in mods]
    dupes = sorted({n for n in names if n and names.count(n) > 1})
    if dupes:
        rep.findings.append(Finding(
            "duplicate_modules", "revise", None,
            f"two modules named {', '.join(dupes)} — merge them or name what differs"))
    if len(mods) > 6:
        rep.findings.append(Finding(
            "too_many_modules", "revise", None,
            f"{len(mods)} modules on day one is a wall — keep the five or six they will "
            f"actually open this week; the rest can be built when they ask"))
    for m in mods:
        if len((m.get("intake") or "").split()) < 12:
            rep.findings.append(Finding(
                "thin_intake", "revise", None,
                f"module '{m.get('name')}' has a one-line intake — the module builder "
                f"designs from these words, so say what is tracked, per whom, with what "
                f"amounts and dates, and what should be noticed"))
            break
    for f in forms:
        if f.get("form_type") == "intake" and mods and not f.get("link_module"):
            rep.findings.append(Finding(
                "form_not_linked", "note", None,
                f"form '{f.get('name')}' feeds no module — name the module its "
                f"submissions should land in"))
            break
    rails = bp.get("rails") if isinstance(bp.get("rails"), dict) else {}
    gaps = [k for k, v in rails.items() if isinstance(v, dict) and (v.get("gap") or "").strip()]
    if gaps:
        rep.findings.append(Finding(
            "rails_declare_gaps", "note", None,
            f"the blueprint itself says these are not covered: {', '.join(gaps)}"))
    return rep
