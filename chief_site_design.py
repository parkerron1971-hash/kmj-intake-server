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


def _stated_offers_line(cfg: Dict[str, Any]) -> str:
    """What the owner told the Design Coach they sell and when they are open
    (discovery truth), in their words, or ""."""
    dd = cfg.get("discovery_dossier") if isinstance(cfg.get("discovery_dossier"), dict) else {}
    truth = dd.get("truth") if isinstance(dd.get("truth"), dict) else {}
    said = []
    for o in (truth.get("offers") or [])[:6]:
        if not isinstance(o, dict) or not str(o.get("name") or "").strip():
            continue
        bits = [str(o.get(k)).strip() for k in ("price", "duration") if str(o.get(k) or "").strip()]
        said.append(str(o["name"]).strip() + (f" ({', '.join(bits)})" if bits else ""))
    hours = truth.get("hours")
    hv = str((hours.get("value") if isinstance(hours, dict) else hours) or "").strip()
    if not said and not hv:
        return ""
    return ("They told the Design Coach"
            + (f" they offer: {'; '.join(said)}" if said else "")
            + (f"{';' if said else ''} hours: {hv}" if hv else "") + ".")


def booking_lines(cfg: Dict[str, Any], settings: Optional[Dict[str, Any]],
                  modules: Optional[List[Dict[str, Any]]] = None,
                  offerings: Optional[List[Dict[str, Any]]] = None) -> List[str]:
    """THE BOOKING DOOR, IN CHIEF'S VIEW (2026-10-04, Kevin: "what about
    booking? if someone wants to book, why haven't I seen that?"). The
    Design Coach heard the services, the prices and the hours; the
    blueprint card said "add them as services"; nothing set booking up,
    so every button on the page opened a note form. Chief now sees
    whether booking is live and, when it is not, exactly what is missing
    and what the owner already said, so it can offer to set it up from
    their own words and ask only for what they did not say."""
    s = settings if isinstance(settings, dict) else {}
    page = s.get("booking_page") if isinstance(s.get("booking_page"), dict) else {}
    calendar = any(str((m or {}).get("archetype") or "") == "booking_calendar"
                   for m in (modules or []) if isinstance(m, dict))
    bookable = any(str((o or {}).get("category") or "") in ("service", "session")
                   and int((o or {}).get("duration_min") or 0) > 0
                   for o in (offerings or []) if isinstance(o, dict))
    if page.get("published") and calendar:
        return ["  Booking: live. The site's book and discovery-call buttons open the "
                "booking page."]
    missing = []
    if not calendar:
        missing.append("no booking calendar yet")
    if not bookable:
        missing.append("no service with a length in minutes")
    if not page.get("published"):
        missing.append("the booking page is not published")
    lines = [f"  Booking: off ({'; '.join(missing)}). Visitors can only leave a note."]
    said = _stated_offers_line(cfg)
    if said and not bookable:
        lines.append(
            f"  {said} When booking comes up, or before or after a site build, "
            "offer once to let visitors book from those words: ask only for what "
            "they did not say (a length for each bookable service; never guess "
            "one), then create_offering for each (\"show_price_to_customer\": false "
            "for any they gave no price), set_availability_day for each day and "
            "the hours they said, and publish_booking_page.")
    elif bookable and calendar and not page.get("published"):
        lines.append("  Everything booking needs is on file: offer publish_booking_page.")
    return lines


def doors_lines(doors: Optional[List[Dict[str, Any]]]) -> List[str]:
    """THE SITE'S OTHER DOORS (2026-10-04, Kevin: "what about events as well?
    all the things that are needed that chief can connect to the site?").
    site_doors.py knows every door; booking keeps its own detailed line
    (booking_lines). Here: the other doors that are live, and the ones close
    to opening (something is on file for them), each with what it needs and
    who opens it: Chief with its verbs, or the owner where Chief has none on
    purpose."""
    rows = [d for d in (doors or []) if isinstance(d, dict) and d.get("key") != "booking"]
    if not rows:
        return []
    lines: List[str] = []
    live = [d for d in rows if d.get("live")]
    if live:
        lines.append("  Also live on the site: "
                     + "; ".join(f"{d.get('name')} ({d.get('path')})" for d in live)
                     + ". A page built before a door opened gains a link to it in its "
                       "navigation on the next refresh.")
    for d in rows:
        if d.get("live") or not d.get("near"):
            continue
        who = "Chief opens it with" if d.get("chief_can_open") else "The owner opens it:"
        needs = ", ".join(d.get("missing") or []) or "nothing on file"
        lines.append(f"  {d.get('name')}: off (needs {needs}). {who} "
                     f"{d.get('opens_with')}. Offer it once when it comes up.")
    return lines


def site_design_lines(site: Optional[Dict[str, Any]],
                      settings: Optional[Dict[str, Any]],
                      modules: Optional[List[Dict[str, Any]]] = None,
                      offerings: Optional[List[Dict[str, Any]]] = None,
                      doors: Optional[List[Dict[str, Any]]] = None) -> List[str]:
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
    try:
        lines.extend(booking_lines(cfg, settings, modules, offerings))
    except Exception as e:
        logger.info(f"[site-design] booking lines skipped: {e}")
    try:
        lines.extend(doors_lines(doors))
    except Exception as e:
        logger.info(f"[site-design] door lines skipped: {e}")
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
