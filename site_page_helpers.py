"""Page IDs and stored secondary pages shared by manual-site consumers."""
from __future__ import annotations

import re
from typing import Any, Dict


# Routes owned by API/portal handlers before the site catch-all, compliance
# pages, and preview namespaces. Keep in step with the route-table test.
# News/academy retain their hosted indexes and detail pages. Sermons is
# deliberately allowed: a manual index can link to hosted sermon details.
RESERVED_PAGE_IDS = frozenset({
    "team", "offerings", "campaigns", "rules", "audit", "health", "bills",
    "suppliers", "entities", "collaborators", "contractors", "chief-proposals",
    "chief-suggestions", "accounting-periods", "period-overrides", "module-specs",
    "agent-coordination", "live", "group-live", "my", "texting-terms",
    "texting-privacy", "data", "news", "academy",
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
