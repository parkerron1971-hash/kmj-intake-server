"""
blueprint_card.py — the blueprint in a few plain lines, for the chat
(2026-10-03).

Kevin's ruling: when someone asks Chief for a site, Chief brings the
Design Coach into the chat, the Director writes the blueprint from what
the Coach learned, and Chief comes back with the blueprint "in three
plain lines", what the page will be missing, and the price, then asks
"build it?". The blueprint itself is a long working document for the
builder; the practitioner deciding whether to build needs the idea, the
setting, the look, and what it costs.

Pure reads, no model call, no writes. The readiness lines (what is
missing) stay in build_readiness; this module only adds the summary and
the price.
"""
from typing import Any, Dict, List, Optional

SETTING_LINES = {
    "plain": ("Plain", "Clear and calm. Nothing renamed, nothing in the way."),
    "signature": ("Signature", "One object carries one moment. The rest stays plain."),
    "world-offer": ("World, on one offer page",
                    "The idea runs one offer page. The home page stays calm."),
    "world-site": ("World, the whole site", "The idea runs every page."),
}


def _leaf(v: Any) -> str:
    """A dossier field is either a bare value or {value, source}."""
    if isinstance(v, dict):
        v = v.get("value")
    if isinstance(v, (list, tuple)):
        v = ", ".join(str(x) for x in v if str(x).strip())
    return str(v or "").strip()


def _dossier(ctx: Dict[str, Any]) -> Dict[str, Any]:
    site = ctx.get("site") if isinstance(ctx.get("site"), dict) else {}
    cfg = site.get("site_config") if isinstance(site.get("site_config"), dict) else {}
    d = cfg.get("discovery_dossier")
    return d if isinstance(d, dict) else {}


def _setting_key(sheet: Dict[str, Any], dossier: Dict[str, Any]) -> str:
    """The card key: the blueprint's own sheet first (it is what gets built),
    the owner's Coach pick when the sheet says nothing."""
    intensity = str(sheet.get("intensity") or "").strip().lower()
    scope = str(sheet.get("scope") or "").strip().lower()
    if intensity == "world":
        return "world-offer" if scope == "offer" else "world-site"
    if intensity in ("plain", "signature"):
        return intensity
    pick = _leaf((dossier.get("taste") or {}).get("concept")).lower()
    return pick if pick in SETTING_LINES else ""


def _objects(spec_text: str) -> List[str]:
    try:
        import site_objects
        out = []
        for key in site_objects.object_names_in(spec_text or ""):
            obj = site_objects.OBJECTS.get(key)
            out.append(obj.name if obj else key)
        return out[:4]
    except Exception:
        return []


def price(business_id: str, plan_sections: int, offer_page: bool) -> Dict[str, Any]:
    """What building this blueprint costs, in the words the card shows.

    The build is charged on the section plan it composes at build time
    (site_composer.build_charge), so before the build the exact count is
    only known when an earlier plan is stored. Otherwise the card says the
    rule instead of guessing a number. Charged only when the build lands."""
    import pricing_config
    offer = pricing_config.offer_page_price() if offer_page else 0
    free = False
    try:
        import usage_metering
        free = bool(business_id) and usage_metering.trial_first_build_is_free(business_id)
    except Exception:
        free = False
    if free:
        return {"free": True, "credits": 0,
                "line": "Your first build is on the house."}
    with_offer = " That includes the offer page." if offer else ""
    if plan_sections > 0:
        n = pricing_config.price_for_build(plan_sections, offer_page=offer_page)
        return {"free": False, "credits": n,
                "line": f"About {n:,} credits.{with_offer} Charged only when the site is ready."}
    base = pricing_config.build_base() + offer
    inc = pricing_config.build_included_sections()
    per = pricing_config.build_per_section()
    return {"free": False, "credits": base,
            "line": (f"From {base:,} credits: {inc} sections included, {per} for each "
                     f"section after that.{with_offer} Charged only when the site is ready.")}


def summary(spec: Optional[Dict[str, Any]], ctx: Dict[str, Any],
            business_id: str = "", plan_sections: int = 0,
            offer_pages_on: bool = True) -> Optional[Dict[str, Any]]:
    """{status, idea, setting{key,label,line}, look, moment, objects[],
    offer_page{name,path}|None, price{free,credits,line}} or None when there
    is no blueprint to summarize. offer_pages_on mirrors the composer's
    SITE_OFFER_PAGE switch: a World-offer blueprint only gets (and pays
    for) its offer page when the switch is on."""
    if not isinstance(spec, dict) or not str(spec.get("text") or "").strip():
        return None
    ctx = ctx if isinstance(ctx, dict) else {}
    text = str(spec.get("text") or "")
    try:
        import site_concept
        sheet = site_concept.parse_sheet(text) or {}
    except Exception:
        sheet = {}
    dossier = _dossier(ctx)
    key = _setting_key(sheet, dossier)
    label, line = SETTING_LINES.get(key, ("", ""))
    offer_page = None
    if key == "world-offer" and offer_pages_on:
        try:
            import site_pages
            offer_page = {"name": site_pages.offer_name(sheet) or "your offer",
                          "path": site_pages.offer_path(sheet)}
        except Exception:
            offer_page = {"name": "your offer", "path": "/offer"}
    taste = dossier.get("taste") if isinstance(dossier.get("taste"), dict) else {}
    sig = dossier.get("signature") if isinstance(dossier.get("signature"), dict) else {}
    layout, layout_options = _layout(sheet, ctx)
    return {
        "status": str(spec.get("status") or "draft"),
        "idea": str(sheet.get("idea") or "").strip()[:260],
        "setting": {"key": key, "label": label, "line": line},
        "look": _leaf(taste.get("look")).lower() or None,
        "moment": (_leaf(sig.get("sharpened")) or _leaf(sig.get("moment")))[:200] or None,
        "objects": _objects(text),
        "offer_page": offer_page,
        "price": price(business_id, plan_sections, offer_page is not None),
        "layout": layout,
        "layout_options": layout_options,
    }


def _sentence(text: str) -> str:
    t = " ".join(str(text or "").split()).strip(" .")
    return (t[0].upper() + t[1:] + ".") if t else ""


def _layout(sheet: Dict[str, Any], ctx: Dict[str, Any]):
    """THE LAYOUT (2026-10-03): the layout the blueprint chose, with the
    Director's own reason, and the three best fits for this business to
    switch to (the rubric's best marked recommended). (None, []) when the
    blueprint names no layout or the library is unavailable."""
    try:
        import site_layouts
    except Exception:
        return None, []
    key = site_layouts.key_from_sheet(sheet)
    layout = None
    if key:
        L = site_layouts.LAYOUTS[key]
        layout = {"key": key, "name": L["name"],
                  "reason": _sentence(site_layouts.reason_from_sheet(sheet))[:260]
                  or _sentence(L["line"])}
    try:
        rows = site_layouts.rank(site_layouts.signals(ctx))
    except Exception:
        rows = []
    if not rows:
        return layout, []
    best = max(rows, key=lambda r: r["score"])["key"]
    options = [{"key": r["key"], "name": r["name"],
                "reason": site_layouts.reason_line(r),
                "recommended": r["key"] == best} for r in rows[:3]]
    return layout, options
