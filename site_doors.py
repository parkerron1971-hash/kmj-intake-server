"""THE SITE'S DOORS (2026-10-04).

Kevin: "what about events as well? all the things that are needed that
chief can connect to the site?"

A door is a working public page the business's site can link to: booking,
events, the shop, giving, courses, sermons, news, the member app. Each one
already had its own idea of "live" in its own router, the builder knew
three of them, Chief knew none as a whole, and a page built before a door
opened never linked to it. This module is the one place that knows every
door: whether it is live, what is missing when it is not, how it is
opened (by Chief, or by the owner where Chief has no verb on purpose),
where it lives, and what a link to it is called.

The "is it live" rules are the owning routers' own functions, never a
re-derivation, so the site, Chief and the builder cannot disagree with
the page a visitor lands on.

Readers:
  - Chief's PRACTITIONER SITE block (chief_site_design.doors_lines)
  - the builder's CONNECTED SYSTEMS block (builder_v2.connected_systems_block)
  - every render of a builder page (site_composer.wire_site_doors): a door
    that opened after the build gets a link in the page's navigation.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Callable, Dict, List, Optional

import sb_clients

logger = logging.getLogger("site_doors")

PUBLIC_DOMAIN = "mysolutionist.app"


class Door:
    def __init__(self, key: str, name: str, path: str, nav_label: str,
                 opens_with: str, chief_can_open: bool) -> None:
        self.key = key
        self.name = name              # what the owner calls it
        self.path = path              # root-relative, on the site's own host
        self.nav_label = nav_label    # the link text a page gains
        self.opens_with = opens_with  # how it is opened, for Chief
        self.chief_can_open = chief_can_open


DOORS: List[Door] = [
    Door("booking", "Booking", "/book", "Book",
         "create_offering for each bookable service (with its length in minutes), "
         "set_availability_day for the open days, then publish_booking_page",
         True),
    Door("events", "Events", "/events", "Events",
         "ensure_module with archetype event_roster, create_module_entry for each "
         "event, then set_site_capability {\"capability\": \"events\", \"on\": true}",
         True),
    Door("store", "Shop", "/store", "Shop",
         "create_offering for each item with a price (category product, package or "
         "course), then setup_store; taking cards needs the owner to connect Stripe "
         "in Settings, which Chief cannot do for them",
         True),
    Door("giving", "Giving", "/give", "Give",
         "set_giving {\"on\": true} once card payments are connected (connecting "
         "Stripe is the owner's, in Settings); owner only",
         True),
    Door("courses", "Courses", "/academy", "Courses",
         "create_course and save_course_content draft it, then publish_course with its "
         "title once Course Studio's checklist passes",
         True),
    Door("sermons", "Sermons", "/sermons", "Sermons",
         "publish_sermon with its title (or the latest) once it has a video, audio or "
         "summary",
         True),
    Door("news", "News", "/news", "News",
         "publish_to_site with the post",
         True),
    Door("members", "Member app", "/my", "Members",
         "set_member_app {\"on\": true}, owner only; refused while sign-in codes can't "
         "be sent by email or text",
         True),
]
BY_KEY: Dict[str, Door] = {d.key: d for d in DOORS}


# ─── the facts, read once ────────────────────────────────────────────

def _rows(path: str) -> List[Dict[str, Any]]:
    try:
        return sb_clients.sb_get_as_service(path) or []
    except Exception as e:
        logger.info(f"[doors] read skipped ({path.split('?')[0]}): {e}")
        return []


def door_facts(business_id: str) -> Dict[str, Any]:
    """Everything the door rules need, in seven small reads."""
    biz = (_rows(f"/businesses?id=eq.{business_id}"
                 "&select=id,name,type,settings,stripe_account_id&limit=1") or [{}])[0]
    site = (_rows(f"/business_sites?business_id=eq.{business_id}"
                  "&select=slug,custom_domain:site_config->>custom_domain&limit=1") or [{}])[0]
    return {
        "business": biz,
        "site": site,
        "archetypes": [str(m.get("archetype") or "") for m in _rows(
            f"/custom_modules?business_id=eq.{business_id}&is_active=eq.true"
            "&select=archetype&limit=100")],
        "offerings": _rows(
            f"/offerings?business_id=eq.{business_id}&is_active=eq.true"
            "&select=name,category,current_price,duration_min&limit=200"),
        "sermons": _rows(f"/sermons?business_id=eq.{business_id}"
                         "&select=published&limit=50"),
        "courses": _rows(f"/academy_courses?business_id=eq.{business_id}"
                         "&select=status&limit=50"),
    }


# ─── the rules, each the owning router's own ─────────────────────────

def _settings(f: Dict[str, Any]) -> Dict[str, Any]:
    s = (f.get("business") or {}).get("settings")
    return s if isinstance(s, dict) else {}


def _nonprofit(f: Dict[str, Any]) -> bool:
    try:
        import vertical_family
        return vertical_family.is_nonprofit_like((f.get("business") or {}).get("type"))
    except Exception:
        return False


def _booking(f: Dict[str, Any]) -> Dict[str, Any]:
    page = _settings(f).get("booking_page")
    published = bool(page.get("published")) if isinstance(page, dict) else False
    calendar = "booking_calendar" in f.get("archetypes", [])
    bookable = any(str(o.get("category") or "") in ("service", "session")
                   and int(o.get("duration_min") or 0) > 0 for o in f.get("offerings", []))
    missing = [m for m, ok in (("a booking calendar", calendar),
                               ("a service with a length in minutes", bookable),
                               ("the booking page published", published)) if not ok]
    # the same rule as booking_widget_router.booking_is_live
    return {"live": published and calendar, "missing": missing,
            "near": calendar or bookable or published}


def _events(f: Dict[str, Any]) -> Dict[str, Any]:
    from events_rsvp_router import events_settings
    enabled = bool(events_settings(_settings(f)).get("enabled"))
    roster = "event_roster" in f.get("archetypes", [])
    missing = [m for m, ok in (("an Events module", roster),
                               ("the events page switched on", enabled)) if not ok]
    # the same rule as events_rsvp_router.events_public_is_active
    return {"live": enabled and roster, "missing": missing, "near": roster or enabled}


def _store(f: Dict[str, Any]) -> Dict[str, Any]:
    from store_router import SELLABLE_CATEGORIES
    import payments_core
    sellable = False
    for o in f.get("offerings", []):
        try:
            if str(o.get("category") or "") in SELLABLE_CATEGORIES \
                    and float(o.get("current_price") or 0) > 0:
                sellable = True
                break
        except (TypeError, ValueError):
            continue
    biz = f.get("business") or {}
    charge = bool(biz.get("stripe_account_id")) and payments_core.can_charge(biz)
    missing = [m for m, ok in (("an item with a price", sellable),
                               ("card payments connected", charge)) if not ok]
    # a shop with nothing to buy, or that cannot take the card, is a dead end
    return {"live": sellable and charge, "missing": missing, "near": sellable}


def _giving(f: Dict[str, Any]) -> Dict[str, Any]:
    from giving_router import giving_is_active, giving_settings
    biz = f.get("business") or {}
    enabled = bool(giving_settings(_settings(f)).get("enabled"))
    stripe = bool(biz.get("stripe_account_id"))
    missing = [m for m, ok in (("giving switched on", enabled),
                               ("card payments connected", stripe)) if not ok]
    return {"live": giving_is_active(biz), "missing": missing, "near": _nonprofit(f)}


def _courses(f: Dict[str, Any]) -> Dict[str, Any]:
    statuses = [str(c.get("status") or "") for c in f.get("courses", [])]
    live = "published" in statuses
    return {"live": live, "missing": [] if live else ["a published course"],
            "near": bool(statuses)}


def _sermons(f: Dict[str, Any]) -> Dict[str, Any]:
    from sermons_public import sermons_are_public
    rows = f.get("sermons", [])
    live = sermons_are_public(rows)
    return {"live": live, "missing": [] if live else ["a published sermon"],
            "near": bool(rows)}


def _news(f: Dict[str, Any]) -> Dict[str, Any]:
    import site_news
    posts = site_news.normalize_posts((_settings(f).get("website_content") or {}).get("news"))
    return {"live": bool(posts), "missing": [] if posts else ["a published post"],
            "near": False}


def _members(f: Dict[str, Any]) -> Dict[str, Any]:
    from member_portal import portal_active, portal_eligible
    biz = f.get("business") or {}
    eligible = portal_eligible(biz)
    live = portal_active(biz)
    return {"live": live, "missing": [] if live else ["the member app switched on"],
            "near": eligible}


_RULES: Dict[str, Callable[[Dict[str, Any]], Dict[str, Any]]] = {
    "booking": _booking, "events": _events, "store": _store, "giving": _giving,
    "courses": _courses, "sermons": _sermons, "news": _news, "members": _members,
}


def site_origin(site: Dict[str, Any]) -> str:
    """https://<custom domain> or https://<slug>.mysolutionist.app."""
    custom = str((site or {}).get("custom_domain") or "").strip().lower().strip("/")
    if custom:
        return f"https://{custom}"
    return f"https://{(site or {}).get('slug') or 'business'}.{PUBLIC_DOMAIN}"


def doors_from_facts(f: Dict[str, Any]) -> List[Dict[str, Any]]:
    """[{key, name, path, url, nav_label, live, missing, near, opens_with,
    chief_can_open}] for every door, in DOORS order. A rule that fails reads
    as closed: a door is only ever claimed live on the owner's real data."""
    origin = site_origin(f.get("site") or {})
    out = []
    for d in DOORS:
        try:
            st = _RULES[d.key](f)
        except Exception as e:
            logger.info(f"[doors] {d.key} rule skipped: {e}")
            st = {"live": False, "missing": [], "near": False}
        out.append({"key": d.key, "name": d.name, "path": d.path,
                    "url": origin + d.path, "nav_label": d.nav_label,
                    "live": bool(st.get("live")), "missing": list(st.get("missing") or []),
                    "near": bool(st.get("near")), "opens_with": d.opens_with,
                    "chief_can_open": d.chief_can_open})
    return out


def site_doors(business_id: str) -> List[Dict[str, Any]]:
    return doors_from_facts(door_facts(business_id))


def live_doors(business_id: str) -> List[Dict[str, Any]]:
    return [d for d in site_doors(business_id) if d["live"]]


# ─── how a page reaches its doors ────────────────────────────────────

# THE BOOKING DOOR (2026-10-04, Kevin: "what about booking?"): a page built
# before booking was live sends its book buttons to the note form
# (#contact), because the wired-site contract only links what is live at
# build time. Once the owner turns booking on (Chief's publish_booking_page
# or the Embed tab), those buttons open the booking page instead, on every
# render, without a rebuild; turning booking off sends them back, since the
# stored document is never changed. Only a link that points at #contact AND
# says book, schedule, appointment, reserve or discovery call is moved; the
# note form keeps every other link ("Leave a note", a price row without a
# booking word).
_BOOK_WORDS_RE = re.compile(r"\b(book|booking|schedule|appointment|reserve|discovery call)\b",
                            re.IGNORECASE)
_CONTACT_HREF_RE = re.compile(r"""href=(["'])/?#contact\1""", re.IGNORECASE)
_ANCHOR_RE = re.compile(r"(<a\b[^>]*>)(.*?)</a>", re.IGNORECASE | re.DOTALL)


def rewire_booking_links(html: str, booking_url: str) -> str:
    """Pure: point the book-worded #contact links at booking_url."""
    if not html or not booking_url:
        return html
    import html as _html
    url = _html.escape(booking_url, quote=True)

    def _swap(m: Any) -> str:
        tag, inner = m.group(1), m.group(2)
        if not _CONTACT_HREF_RE.search(tag):
            return m.group(0)
        if not _BOOK_WORDS_RE.search(re.sub(r"<[^>]+>", " ", inner)):
            return m.group(0)
        tag = _CONTACT_HREF_RE.sub(f'href="{url}"', tag, count=1)
        if "data-sx-door" not in tag:
            tag = tag[:-1] + ' data-sx-door="booking">'
        return tag + inner + "</a>"

    return _ANCHOR_RE.sub(_swap, html)


# EVERY DOOR, REACHABLE (2026-10-04, Kevin: "what about events as well?
# all the things that are needed that chief can connect to the site?"): a
# door that opened after the build (events switched on, a course
# published, giving turned on) had no link anywhere on the page, so a
# working page sat unreachable from the site: the dead-weight rule at
# platform scale. On every render, each live door the page does not
# already link to gains one link in each of the page's <nav> blocks,
# shaped like that nav's own plain links (same class, inside an <li> when
# the nav uses them). Links are root-relative ("/events"), so the stored
# page stays right on whichever host serves it (business_sites_helpers).
# The stored document is never changed: a door that closes loses its link
# on the next render.
_NAV_RE = re.compile(r"<nav\b[^>]*>.*?</nav>", re.IGNORECASE | re.DOTALL)
_CLASS_RE = re.compile(r"""\bclass\s*=\s*(["'])(.*?)\1""", re.IGNORECASE | re.DOTALL)
_NOT_A_PLAIN_LINK = re.compile(r"\b(btn|button|cta|brand|logo|wordmark|skip|menu-toggle)\b",
                               re.IGNORECASE)


def _links_to(html: str, path: str) -> bool:
    return bool(re.search(r"""href\s*=\s*["'](?:https?://[^"'/]+)?"""
                          + re.escape(path) + r"""(?=["'/?#])""", html, re.IGNORECASE))


def _with_nav_link(nav: str, door: Dict[str, Any]) -> str:
    """One <nav> block with the door's link added after its last plain
    link, or unchanged when the nav has no plain link to copy."""
    import html as _html
    template = None
    for m in _ANCHOR_RE.finditer(nav):
        tag = m.group(1)
        cls = (_CLASS_RE.search(tag) or [None, None, ""])[2]
        href = re.search(r"""href\s*=\s*["']([^"']*)""", tag, re.IGNORECASE)
        if "<img" in m.group(2).lower() or _NOT_A_PLAIN_LINK.search(cls or ""):
            continue
        if not href or href.group(1).startswith(("mailto:", "tel:")):
            continue
        template = (m, cls)
    if template is None:
        return nav
    m, cls = template
    label = _html.escape(str(door.get("nav_label") or door.get("name") or ""))
    link = (f'<a href="{_html.escape(str(door["path"]), quote=True)}"'
            + (f' class="{cls}"' if cls else "")
            + f' data-sx-door="{_html.escape(str(door["key"]), quote=True)}">{label}</a>')
    end = m.end()
    li_close = re.match(r"\s*</li>", nav[end:], re.IGNORECASE)
    if li_close:
        li_open = re.search(r"<li\b[^>]*>\s*$", nav[:m.start()], re.IGNORECASE)
        li_tag = li_open.group(0).strip() if li_open else "<li>"
        at = end + li_close.end()
        return nav[:at] + li_tag + link + "</li>" + nav[at:]
    return nav[:end] + link + nav[end:]


def add_door_links(html: str, doors: List[Dict[str, Any]]) -> str:
    """Pure: give each live door the page does not link to a link in every
    <nav>. Idempotent (a door the page links to is left alone)."""
    out = html or ""
    for door in doors or []:
        if not door.get("live") or not door.get("path") or _links_to(out, str(door["path"])):
            continue
        out = _NAV_RE.sub(lambda nm: _with_nav_link(nm.group(0), door), out)
    return out


def wire_html(html: str, live: List[Dict[str, Any]]) -> str:
    """Every live door reachable from a page: the booking rewire of the
    book-worded note links, then a nav link for each live door the page
    does not link to. Pure."""
    if not html or not live:
        return html
    if any(d.get("key") == "booking" for d in live):
        html = rewire_booking_links(html, "/book")
    return add_door_links(html, live)


def is_builder_page(html: str) -> bool:
    """A page the new builder wrote: its editable text carries v2/ keys.
    Hand-built and older pages keep their own navigation untouched."""
    return 'data-override-target="v2/' in (html or "")         or "data-override-target='v2/" in (html or "")


# THE SERVE-TIME CHECK (2026-10-04): several doors are switched on straight
# from the app (events, courses, sermons: client writes the backend never
# sees), so a refresh hook could not catch them all. public_site wires the
# doors as it serves a builder page, from this cache: seven small reads per
# business at most every DOORS_TTL_S seconds, never per view.
DOORS_TTL_S = 120
_LIVE_CACHE: Dict[str, Any] = {}


def live_doors_cached(business_id: str) -> List[Dict[str, Any]]:
    import time
    hit = _LIVE_CACHE.get(business_id)
    now = time.time()
    if hit and now - hit[0] < DOORS_TTL_S:
        return hit[1]
    try:
        live = live_doors(business_id)
    except Exception as e:
        logger.info(f"[doors] live check skipped for {business_id[:8]}: {e}")
        live = hit[1] if hit else []
    if len(_LIVE_CACHE) > 2000:
        _LIVE_CACHE.clear()
    _LIVE_CACHE[business_id] = (now, live)
    return live
