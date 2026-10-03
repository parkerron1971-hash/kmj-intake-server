"""
chief_site_design.py — Chief hands a site request to the Design Coach
(2026-10-03).

Kevin's ruling, in two parts:
  - "the goal of the blueprint was to retrieve data from [the] client [on]
    the style of website they wanted, so chief wouldn't create a site and
    it looks generic." Chief's rebuild_site used to start a build with no
    blueprint, and compose_site runs the new builder only on an APPROVED
    blueprint, so a site asked for in the chat came off the older ladder.
  - "if someone asks Chief to build a site, should chief pull in the coach
    in the chat?" Yes, as a handoff, not a merge: the Coach keeps its own
    voice and picture cards (design_coach.py stays its own door, no action
    tags, no Chief injectors), Chief owns the start and the finish.

So:
  start_design_session  opens the Coach from the chat (frontend event).
  show_blueprint        puts the blueprint card in front of them: the idea,
                        the setting, what is missing, the price, and a
                        Build it button. The build starts on THEIR tap.
  rebuild_gate          Chief's rebuild_site refuses without an approved
                        blueprint and names the verb that does apply.
  site_design_lines     the PRACTITIONER SITE lines that tell Chief where
                        the design stands and which photos are not on the
                        site yet.

Practitioner-facing words never mention builders, GitHub or Claude Code.
"""
import asyncio
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger("chief_site_design")

SESSION_EVENT = "solutionist-design-session"
CARD_EVENT = "solutionist-blueprint-card"


def _spec(business_id: str) -> Optional[Dict[str, Any]]:
    try:
        import spec_author
        return spec_author.get_spec(business_id)
    except Exception as e:
        logger.info(f"[site-design] blueprint read skipped: {e}")
        return None


def _hand_built_block(business_id: str) -> Optional[str]:
    try:
        import site_adopt
        return site_adopt.hand_built_block_for(business_id)
    except Exception:
        return None


def rebuild_gate(business_id: str) -> Optional[str]:
    """None when a Chief rebuild may start; otherwise the reason, worded
    for Chief, naming the verb that applies. Only an APPROVED blueprint
    reaches the new builder, and the blueprint is where their style lives."""
    spec = _spec(business_id)
    if spec and str(spec.get("status") or "") == "approved":
        return None
    if spec:
        return ("their design blueprint is drafted but not approved yet. Emit "
                "show_blueprint: the card shows the idea, what the page will be "
                "missing and the price, and the build starts when they tap Build it")
    return ("there is no design blueprint yet, so the site would not be built "
            "from their style. Emit start_design_session: the Design Coach "
            "learns their style here in the chat, the blueprint comes back as "
            "a card, and the build starts when they tap Build it")


def _gallery(settings: Dict[str, Any]) -> List[Dict[str, Any]]:
    gal = ((settings or {}).get("media_library") or {}).get("gallery") or []
    return [g for g in gal if isinstance(g, dict)
            and str(g.get("url") or "").strip()
            and g.get("show_on_website", True)]


def photos_not_on_site(settings: Dict[str, Any], site_config: Dict[str, Any]) -> int:
    """Library photos the composed page does not carry. Only counted for a
    page from the new builder, whose html is its own (site_config.canvas);
    module-composed pages re-render the library on refresh by themselves."""
    cfg = site_config if isinstance(site_config, dict) else {}
    if ((cfg.get("canvas_report") or {}).get("engine")) != "builder_v2":
        return 0
    html = str((cfg.get("canvas") or {}).get("html") or "")
    if not html:
        return 0
    return sum(1 for g in _gallery(settings) if str(g["url"]).strip() not in html)


def site_design_lines(site: Optional[Dict[str, Any]],
                      settings: Optional[Dict[str, Any]]) -> List[str]:
    """Lines for Chief's PRACTITIONER SITE block. [] for a hand-built site
    (site_adopt describes those) and when nothing applies."""
    site = site if isinstance(site, dict) else {}
    cfg = site.get("site_config") if isinstance(site.get("site_config"), dict) else {}
    if str(cfg.get("html_source") or "") == "manual":
        return []
    spec = cfg.get("design_spec") if isinstance(cfg.get("design_spec"), dict) else None
    status = str((spec or {}).get("status") or "") if (spec or {}).get("text") else ""
    lines: List[str] = []
    if status == "approved":
        lines.append("  Design blueprint: approved. A rebuild follows it; refine keeps "
                     "the look and redoes the execution. A NEW look starts with "
                     "start_design_session.")
    elif status:
        lines.append("  Design blueprint: drafted, waiting for their tap. To build, emit "
                     "show_blueprint (the card has the Build it button).")
    else:
        lines.append("  Design blueprint: none yet. Any site build or redesign starts "
                     "with start_design_session (the Design Coach, in the chat).")
    n = photos_not_on_site(settings or {}, cfg)
    if n:
        lines.append(
            f"  Photos not on the site yet: {n} in their library. Offer to work them "
            "in: enqueue_job refine_section with params {\"section\": \"work\", "
            "\"instruction\": \"Use the new photos from their library in this "
            "section\"} (one section, priced as a section rework).")
    return lines


async def handle_start_design_session(client, biz, action) -> Dict[str, Any]:
    """Open the Design Coach from the chat. 'quick' (the default from the
    chat) is about five questions and two picture picks; 'deep' is the full
    sit-down."""
    raw = str(action.get("mode") or "").strip().lower()
    mode = "deep" if raw in ("deep", "full", "long") else "quick"
    # anything already decided (their words, the business layout's site
    # brief) rides to the blueprint as its notes when the session ends
    params = action.get("params") if isinstance(action.get("params"), dict) else {}
    brief = str(action.get("brief_notes") or params.get("brief_notes") or "").strip()[:800]
    block = await asyncio.to_thread(_hand_built_block, biz["id"])
    if block:
        return {"type": "start_design_session",
                "result": f"Not opened — {block}. Use edit_site_text for copy, "
                          "check_site to look at it",
                "label": "Site is hand-built — no design session", "nav": None}
    # WHAT WAS HANDED OVER, ON THE RECEIPT (2026-10-03, the second live
    # test): Chief told the owner "the only thing I passed along is what
    # you told me", the answer check had nothing to check it against, and
    # the owner read "I couldn't confirm this claim: ..." instead. The
    # receipt now carries the words handed to the Coach, so the claim is
    # checkable and the owner can see exactly what went.
    handed = (f" Handed the Coach these notes: \"{brief}\"." if brief
              else " Handed the Coach no notes; it starts from what is on file.")
    return {
        "type": "start_design_session",
        "result": ("Opened the design session: the Design Coach is with them now "
                   f"({mode} session).{handed} When it ends the blueprint is drafted "
                   "and comes back to this chat as a card with the price and a Build "
                   "it button. Do not start a build yourself."),
        "label": "Design session with the Coach",
        "nav": None,
        "frontend_event": {"name": SESSION_EVENT,
                           "detail": {"mode": mode, "business_id": biz["id"],
                                      "brief_notes": brief}},
    }


def _card_summary(business_id: str, spec: Dict[str, Any]) -> str:
    """One line Chief can speak from: the idea, the setting, the price."""
    try:
        import blueprint_card
        import site_composer
        card = blueprint_card.summary(spec, site_composer.gather_context(business_id),
                                      business_id) or {}
        bits = []
        if card.get("idea"):
            bits.append(f"idea: {card['idea']}")
        label = (card.get("setting") or {}).get("label")
        if label:
            bits.append(f"setting: {label}")
        price = (card.get("price") or {}).get("line")
        if price:
            bits.append(f"price: {price}")
        return "; ".join(bits)
    except Exception as e:
        logger.info(f"[site-design] card summary skipped: {e}")
        return ""


async def handle_show_blueprint(client, biz, action) -> Dict[str, Any]:
    """Put the blueprint card in front of them. The card's Build it button
    is the approval and the start: Chief never approves a blueprint."""
    spec = await asyncio.to_thread(_spec, biz["id"])
    if not spec:
        return {"type": "show_blueprint",
                "result": ("No blueprint yet. Emit start_design_session so the "
                           "Design Coach can learn their style first."),
                "label": "No blueprint yet", "nav": None}
    status = str(spec.get("status") or "draft")
    said = await asyncio.to_thread(_card_summary, biz["id"], spec)
    return {
        "type": "show_blueprint",
        "result": (f"Showed the blueprint card ({status})."
                   + (f" {said}." if said else "")
                   + " The build starts only when they tap Build it on the card; "
                     "changes go through enqueue_job revise_spec with their notes."),
        "label": "Your blueprint",
        "nav": None,
        "frontend_event": {"name": CARD_EVENT, "detail": {"business_id": biz["id"]}},
    }
