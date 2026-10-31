"""Page IDs and stored secondary pages shared by manual-site consumers."""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import parse_qsl, urlencode


# Routes owned by API/portal handlers before the site catch-all, compliance
# pages, and preview namespaces. Keep in step with the route-table test.
# News/academy retain their hosted indexes and detail pages. Sermons is
# deliberately allowed: a manual index can link to hosted sermon details.
RESERVED_PAGE_IDS = frozenset({
    "team", "offerings", "campaigns", "rules", "audit", "health", "bills",
    "suppliers", "entities", "collaborators", "contractors", "chief-proposals",
    "chief-suggestions", "accounting-periods", "period-overrides", "module-specs",
    "agent-coordination", "live", "group-live", "my", "texting-terms",
    "texting-privacy", "data", "news", "academy", "daily", "stream-relay",
    "housing-allowance", "year-funds", "bank-statements", "giving-deposits",
})


def valid_page_id(page_id: Any) -> bool:
    return isinstance(page_id, str) and re.fullmatch(r"[a-z0-9-]+", page_id) is not None


def secondary_pages(site_config: Any) -> Dict[str, str]:
    """Nonempty, URL-safe pages in site order, then any unlisted pages."""
    if not isinstance(site_config, dict):
        return {}
    pages = site_config.get("generated_pages")
    if not isinstance(pages, dict):
        return {}
    order = site_config.get("site_pages")
    order = order if isinstance(order, list) else []
    result: Dict[str, str] = {}
    for pid in order + list(pages):
        if (not valid_page_id(pid) or pid in RESERVED_PAGE_IDS
                or pid == "home" or pid in result):
            continue
        html = pages.get(pid)
        if isinstance(html, str) and html.strip():
            result[pid] = html
    return result


# A hand-built site's old addresses: build.py REDIRECTS, stored by site_sync
# as site_config.manual_redirects and answered with a 301 only where the
# site would otherwise 404. An old path is lowercase segments, or ends in
# "/*" for everything under it. A target is "/" or one of the site's own
# pages, with an optional ?query and #anchor, or one of its forms' pages
# (/public/widget/form/<id>, the address an old sign-up page moved to when
# it became a card in the app): never another host. A path an API route
# answers first (/live) is refused: only the Worker could vouch that a
# request came from the site's own host, and nothing checks that yet.
MAX_REDIRECTS = 100
_REDIRECT_FROM_RE = re.compile(r"/[a-z0-9-]+(?:/[a-z0-9-]+)*(?:/\*)?")
_REDIRECT_TO_RE = re.compile(r"/([a-z0-9-]*)(\?[a-z0-9=&-]*)?(#[a-z0-9-]+)?")
_REDIRECT_TO_FORM_RE = re.compile(
    r"/public/widget/form/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
# Hosted pages that answer before a site's redirects are looked at.
_HOSTED_PATHS = frozenset({"book", "give", "events", "sermons", "store"})


def redirect_target_ok(target: Any) -> bool:
    return isinstance(target, str) and (_REDIRECT_TO_RE.fullmatch(target) is not None
                                        or _REDIRECT_TO_FORM_RE.fullmatch(target) is not None)


def _lands_on_the_site(target: Any, pages: set) -> bool:
    """A target one of these pages (or home) answers, or a form page."""
    if not redirect_target_ok(target):
        return False
    page = _REDIRECT_TO_RE.fullmatch(target)
    return page is None or page.group(1) in pages | {""}


def clean_redirects(redirects: Any, page_ids: Iterable[str]) -> Tuple[Dict[str, str], List[Tuple[Any, str]]]:
    """The redirects site_sync installs, and (old path, reason) for each
    one it skips. page_ids are the pages being installed, home included."""
    if redirects is None:
        return {}, []
    if not isinstance(redirects, dict):
        return {}, [("REDIRECTS", "redirects must be a dict")]
    pages = {p for p in page_ids if p != "home"}
    kept: Dict[str, str] = {}
    skipped: List[Tuple[Any, str]] = []
    for old, to in redirects.items():
        if not isinstance(old, str) or _REDIRECT_FROM_RE.fullmatch(old) is None:
            skipped.append((old, "redirect from an invalid path"))
            continue
        first = old.split("/")[1]
        if old[1:] in pages:
            skipped.append((old, "redirect from a page the site serves"))
        elif first in RESERVED_PAGE_IDS or first in _HOSTED_PATHS:
            skipped.append((old, "redirect from a path another handler answers"))
        elif not _lands_on_the_site(to, pages):
            skipped.append((old, f"redirect to {to!r}, not one of the site's pages"))
        elif len(kept) >= MAX_REDIRECTS:
            skipped.append((old, f"redirect cap {MAX_REDIRECTS} reached"))
        else:
            kept[old] = to
    return kept, skipped


def manual_redirect(site_config: Any, path: Any) -> Optional[str]:
    """Where a hand-built site sends this old address, or None. An exact
    entry wins; otherwise the longest "/x/*" entry that the path is under."""
    if not isinstance(site_config, dict) or site_config.get("html_source") != "manual":
        return None
    redirects = site_config.get("manual_redirects")
    if not isinstance(redirects, dict) or not isinstance(path, str):
        return None
    p = path.rstrip("/").lower() or "/"
    to = redirects.get(p)
    if to is None:
        under = [old for old in redirects
                 if isinstance(old, str) and old.endswith("/*") and p.startswith(old[:-1])]
        to = redirects.get(max(under, key=len)) if under else None
    return to if redirect_target_ok(to) else None


def with_visitor_query(target: str, query: Any) -> str:
    """The redirect target with the visitor's own query string kept
    (utm_source, fbclid and the like), so a campaign link still counts
    after the move. Where both name a parameter, the target's value wins.
    The path and #anchor stay the target's, so the result never leaves
    the site."""
    if not isinstance(query, str) or not query:
        return target
    rest, hash_, anchor = target.partition("#")
    path, _, own_query = rest.partition("?")
    own = parse_qsl(own_query, keep_blank_values=True)
    named = {key for key, _ in own}
    theirs = [(k, v) for k, v in parse_qsl(query, keep_blank_values=True) if k not in named]
    pairs = own + theirs
    return path + ("?" + urlencode(pairs) if pairs else "") + hash_ + anchor
