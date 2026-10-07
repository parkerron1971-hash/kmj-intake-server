"""business_marketing_links.py — a business post's tracked link, on its own site.

B6 of docs/plans/MARKETING_SUITE_PLAN_2026-10-07.md: the platform desk's
links (platform_marketing.tracked_link, short_link, caption_with_landing_link
and follow, and the apex /go/ route in public_site) for every business.

  short link    {origin}/go/{code}. The origin is the business's verified
                custom domain, else https://{slug}.mysolutionist.app. The code
                is business_marketing_store.link_code(post id): derived, so a
                retried save or an edit lands on the same code.
  tracked_url   the landing page with the desk's utm tags and
                utm_content=<post id>, the one join key the results use. The
                landing is the post's own link, else the desk's, else the
                booking page when anything is bookable, else the site's home.
                Its host is always one of the business's own hosts.
  publish_text  the caption with the short link (the platform's rule: a
                mention of the landing page is swapped for it; otherwise it is
                appended once).

A business with no site (no business_sites row with a slug, or nothing
published and nothing bookable, and no link chosen) posts with no link:
tracked_url is empty and publish_text is the caption.

THE APPROVAL. landing_url and publish_text are inside the post's content_hash
(business_marketing_store.digest); tracked_url is a function of landing_url
and the post id, so changing where a post goes changes what the owner
approved.

THE REDIRECT (/go/{code} on a business's own host, public_site). The host's
business is resolved first. marketing_follow is asked WITHOUT counting; the
visitor is redirected only when the post is that business's and its
tracked_url is https on one of that business's own hosts (never an open
redirect). Only then, and only for a person (not a link-preview fetcher, not
Do Not Track), is the click counted. Anything else is the site's normal
answer for the path: its 404.

FAIL CLOSED. A read the link depends on that fails raises LinksUnavailable;
it is never "no site". The redirect treats it as a miss (the site's 404).
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, Dict, FrozenSet, Mapping, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import UUID

import business_marketing_store as store
import sb_clients
from business_sites_helpers import PUBLIC_DOMAIN

logger = logging.getLogger("business_marketing_links")

# Every desk post goes to several networks with one link, so the source is
# the kind of channel; utm_content names the post.
UTM = (("utm_source", "social"), ("utm_medium", "organic_social"), ("utm_campaign", "marketing_desk"))
SITE_COLUMNS = ("business_id,slug,status,custom_domain:site_config->>custom_domain,"
                "custom_domain_status:site_config->>custom_domain_status")
_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,99}$")
_LABEL = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
_DOMAIN = re.compile(rf"^(?=.{{4,253}}$){_LABEL}(?:\.{_LABEL})+$")


class LinksUnavailable(Exception):
    """A read the link depends on did not happen. Never "no site"."""


# ── the business's site ───────────────────────────────────────────────

def _domain(raw: Any) -> str:
    """A custom domain as connect stores it: the apex, lower case, no scheme."""
    value = str(raw or "").strip().lower().removeprefix("https://").removeprefix("http://")
    return value.strip("/").removeprefix("www.")


def site_from_row(row: Optional[Mapping[str, Any]]) -> Optional[Dict[str, Any]]:
    """{business_id, slug, domain (only when verified, else ''), published},
    or None when the row names no site. Takes the narrow select above or a
    whole row with site_config."""
    if not row or not row.get("slug"):
        return None
    cfg = row.get("site_config") if isinstance(row.get("site_config"), Mapping) else {}
    domain = _domain(row["custom_domain"] if "custom_domain" in row else cfg.get("custom_domain"))
    status = row["custom_domain_status"] if "custom_domain_status" in row else cfg.get("custom_domain_status")
    verified = str(status or "").strip().lower() == "verified"
    return {"business_id": str(row.get("business_id") or ""), "slug": str(row["slug"]).strip().lower(),
            "domain": domain if domain and verified else "", "published": row.get("status") == "published"}


def own_hosts(site: Optional[Mapping[str, Any]]) -> FrozenSet[str]:
    """The hosts this business's site and booking page answer on: its
    platform subdomain, and its custom domain (and www) once verified. A
    pending domain has no DNS yet, and a dead link in a post is worse than
    none."""
    if not site:
        return frozenset()
    hosts = {f"{site['slug']}.{PUBLIC_DOMAIN}"}
    if site.get("domain"):
        hosts |= {site["domain"], f"www.{site['domain']}"}
    return frozenset(hosts)


def origin(site: Optional[Mapping[str, Any]]) -> Optional[str]:
    """The address the public uses: the verified custom domain, else the subdomain."""
    if not site:
        return None
    return f"https://{site.get('domain') or site['slug'] + '.' + PUBLIC_DOMAIN}"


def short_link(site: Mapping[str, Any], code: str) -> str:
    return f"{origin(site)}/go/{code}"


def site_for(business_id: Any) -> Optional[Dict[str, Any]]:
    """The business's site, or None when it has none. Raises on a failed read."""
    rows = sb_clients.sb_get_as_service(
        f"/business_sites?business_id=eq.{UUID(str(business_id))}&select={SITE_COLUMNS}"
        "&order=updated_at.desc&limit=1")
    if rows is None:
        raise LinksUnavailable("The business's site could not be read.")
    return site_from_row(rows[0]) if rows else None


def site_for_host(kind: str, name: str) -> Optional[Dict[str, Any]]:
    """The site a request host names, the way public_site serves it: a
    platform subdomain by slug, a custom domain (www or not) by the domain
    connect stored. None for a name that is not a site's; raises on a failed
    read. Names are checked before they go into a query."""
    if kind == "slug":
        slug = str(name or "").strip().lower()
        if not _SLUG.match(slug):
            return None
        where = f"slug=eq.{slug}"
    elif kind == "domain":
        domain = _domain(name)
        if not _DOMAIN.match(domain):
            return None
        where = f"site_config->>custom_domain=eq.{domain}"
    else:
        return None
    rows = sb_clients.sb_get_as_service(
        f"/business_sites?{where}&select={SITE_COLUMNS}&order=updated_at.desc&limit=1")
    if rows is None:
        raise LinksUnavailable("The site for this address could not be read.")
    return site_from_row(rows[0]) if rows else None


# ── where a post goes ─────────────────────────────────────────────────

def _https_on(url: Any, hosts) -> Optional[Any]:
    """The parsed URL when it is https on one of these hosts (no user, no
    odd port), else None."""
    if not isinstance(url, str) or not url:
        return None
    try:
        parts = urlsplit(url)
        port = parts.port
    except (ValueError, TypeError):
        return None
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or not host or parts.username or parts.password or port not in (None, 443):
        return None
    return parts if host in hosts else None


def on_site(url: Any, site: Optional[Mapping[str, Any]]) -> bool:
    return _https_on(url, own_hosts(site)) is not None


def _booking_page(business: Mapping[str, Any]) -> Dict[str, Any]:
    if "booking_page" in business:
        page = business.get("booking_page")
    else:
        settings = business.get("settings") if isinstance(business.get("settings"), Mapping) else {}
        page = settings.get("booking_page")
    return page if isinstance(page, dict) else {}


def bookable(business_id: Any, business: Mapping[str, Any]) -> bool:
    """Anything can be booked on the business's booking page: it is
    published (settings.booking_page), its booking_calendar module is active
    (booking_widget_router.booking_is_live) and at least one active service
    or session has a duration (booking_page_router.publish_blockers). Read
    fail-closed."""
    if not _booking_page(business).get("published"):
        return False
    bid = UUID(str(business_id))
    module = sb_clients.sb_get_as_service(
        f"/custom_modules?business_id=eq.{bid}&archetype=eq.booking_calendar&is_active=eq.true"
        "&select=id&limit=1")
    if module is None:
        raise LinksUnavailable("The booking calendar could not be read.")
    if not module:
        return False
    offers = sb_clients.sb_get_as_service(
        f"/offerings?business_id=eq.{bid}&category=in.(service,session)&is_active=eq.true"
        "&duration_min=gt.0&select=id&limit=1")
    if offers is None:
        raise LinksUnavailable("The services could not be read.")
    return bool(offers)


def default_landing(business_id: Any, business: Mapping[str, Any],
                    site: Optional[Mapping[str, Any]]) -> Optional[str]:
    """Where a post goes when nobody chose: the booking page when anything is
    bookable, else the site's home when it is published, else nowhere."""
    if not site:
        return None
    if bookable(business_id, business):
        return f"{origin(site)}/book"
    if site.get("published"):
        return f"{origin(site)}/"
    return None


def tracked_url(landing: str, post_id: Any, site: Mapping[str, Any]) -> str:
    """The landing page tagged for this post (platform_marketing.tracked_link's
    rule: the page's own query is kept, the utm tags are set). Refuses a
    landing that is not on the business's own hosts."""
    parts = _https_on(landing, own_hosts(site))
    if parts is None:
        raise ValueError("A post's link goes to the business's own site or booking page.")
    tags = dict(parse_qsl(parts.query, keep_blank_values=True))
    tags.update(UTM)
    tags["utm_content"] = str(UUID(str(post_id)))
    return urlunsplit((parts.scheme, parts.netloc, parts.path or "/", urlencode(tags), parts.fragment))


def publish_text(caption: str, landing: str, link: str, site: Mapping[str, Any]) -> str:
    """The words that go out: the caption carrying the short link."""
    from platform_marketing import caption_with_landing_link
    caption = caption or ""
    if not caption.strip():
        return link
    return caption_with_landing_link(caption, landing, link, hosts=own_hosts(site))


def fields(post_id: Any, caption: str, landing: Optional[str],
           site: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """A post's link columns: landing_url, tracked_url, link_code, publish_text.
    No landing (or no site): no link, and the caption goes out as written."""
    code = store.link_code(post_id)
    caption = caption or ""
    if not landing or not site:
        return {"landing_url": None, "tracked_url": None, "link_code": code, "publish_text": caption}
    return {"landing_url": landing, "tracked_url": tracked_url(landing, post_id, site), "link_code": code,
            "publish_text": publish_text(caption, landing, short_link(site, code), site)}


# ── the redirect ──────────────────────────────────────────────────────

def destination(found: Optional[Mapping[str, Any]], site: Optional[Mapping[str, Any]]) -> Optional[str]:
    """The URL to send a visitor to, or None. Only a post of the host's own
    business, and only to https on that business's own hosts."""
    if not found or not site or not site.get("business_id"):
        return None
    if str(found.get("business_id") or "") != site["business_id"]:
        return None
    url = found.get("tracked_url")
    return url if _https_on(url, own_hosts(site)) is not None else None


async def follow_on_host(kind: str, name: str, code: str, *, person: bool) -> Optional[str]:
    """Where a short link on this business's host goes, or None (the site's
    404). Counts the click only for a person, and only once the link is known
    to be this business's and safe to follow."""
    code = (code or "").strip().lower()
    if not store.GO_CODE.match(code):
        return None
    try:
        site = await asyncio.to_thread(site_for_host, kind, name)
        if site is None:
            return None
        found = await store.follow(code, count_click=False)
    except (LinksUnavailable, store.StoreError):
        logger.warning("marketing link %s on a %s host could not be resolved", code, kind)
        return None
    url = destination(found, site)
    if url is None:
        return None
    if person:
        try:
            await store.follow(code, count_click=True)
        except store.StoreError:
            logger.warning("marketing link %s: the click could not be counted", code)
    return url
