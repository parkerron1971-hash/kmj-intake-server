"""Pass 3.8g — multi-page Builder orchestrator.

Generates one Builder pass per page in the requested page set, builds a
shared <nav> once, injects that nav into every page, and returns the
collected map of {page_id: html} ready to persist into
site_config.generated_pages.

Cost discipline: every page costs one Builder run. The cost cap is
checked BEFORE each page, so a partial multi-page generation is the
worst case rather than a runaway loop.

Failure discipline: every per-page operation is wrapped in try/except.
A single failed page records an error and continues to the next, rather
than aborting the whole batch.
"""
from __future__ import annotations

import sys
from typing import Optional, Tuple


def build_pages(
    site_pages: list,
    base_brief: dict,
    bundle: dict,
    scheme: Optional[dict],
    products: list,
    testimonials: list,
    recommendation: dict,
) -> Tuple[dict, list]:
    """Build HTML for each page in `site_pages`.

    Returns (pages_dict, errors). pages_dict keys are page_ids; values
    are full HTML strings with the shared nav injected. errors is a
    list of human-readable strings — empty on a clean run.
    """
    from studio_brief_expander import expand_page_brief
    from studio_builder_agent import build_html
    from studio_cost_cap import can_generate, record_generation
    from studio_page_types import get_page_type

    pages: dict = {}
    errors: list = []

    nav_html = _generate_nav(site_pages, recommendation, base_brief)

    for page_id in site_pages:
        page_type = get_page_type(page_id)
        if not page_type:
            errors.append(f"Skipped unknown page: {page_id}")
            continue

        # Cost cap is checked BEFORE each page so a partial batch is
        # the worst case. The previous pages are still persisted.
        allowed, current, cap = can_generate()
        if not allowed:
            errors.append(
                f"Cost cap reached ({current}/{cap}) — skipped {page_id}"
            )
            continue

        # Expand brief for this page. Falls back internally to base brief
        # on any failure, so page_brief is essentially never None for
        # known page_ids.
        try:
            page_brief, brief_err = expand_page_brief(
                bundle, recommendation, products, page_id, base_brief,
            )
        except Exception as e:
            errors.append(
                f"Page brief crashed for {page_id}: {type(e).__name__}: {e}"
            )
            print(
                f"[multi_page_builder] {page_id} brief crashed: {e}",
                file=sys.stderr,
            )
            page_brief = dict(base_brief or {})
            page_brief["_page_id"] = page_id

        if brief_err:
            errors.append(f"Brief expansion warning for {page_id}: {brief_err}")

        if not page_brief:
            page_brief = dict(base_brief or {})
            page_brief["_page_id"] = page_id

        # Cross-page navigation context for the Builder prompt
        page_brief["_nav_html"] = nav_html
        page_brief["_other_pages"] = [p for p in site_pages if p != page_id]
        page_brief["_current_page"] = page_id

        # Build HTML
        try:
            record_generation()
            html, err, warnings = build_html(
                page_brief, bundle, scheme, products, testimonials,
            )
            if html:
                html = _inject_nav(html, nav_html)
                pages[page_id] = html
                if warnings:
                    errors.append(
                        f"Quality warnings on {page_id}: {'; '.join(warnings[:3])}"
                    )
            else:
                errors.append(f"Build failed for {page_id}: {err}")
        except Exception as e:
            errors.append(
                f"Build crashed for {page_id}: {type(e).__name__}: {e}"
            )
            print(
                f"[multi_page_builder] {page_id} build crashed: {e}",
                file=sys.stderr,
            )

    return pages, errors


def landing_page_html(
    base_brief: dict,
    bundle: dict,
    scheme: Optional[dict],
    products: list,
    testimonials: list,
    recommendation: dict,
):
    """Single-page mode — same as Pass 3.8d Builder, no nav injection.

    Reused by the public_site routing layer when site_type == 'landing-page'
    so generation goes through the same cost-cap gate as multi-page builds.
    """
    from studio_builder_agent import build_html
    from studio_cost_cap import can_generate, record_generation

    allowed, current, cap = can_generate()
    if not allowed:
        return None, f"Cost cap reached ({current}/{cap})"

    record_generation()
    html, err, warnings = build_html(
        base_brief, bundle, scheme, products, testimonials,
    )
    return html, err


# ─── nav generation + injection ──────────────────────────────────────

def _resolve_brand_label(recommendation: dict, base_brief: dict) -> str:
    """Best-effort brand label for the nav. Prefer concept_name, else
    business name from the brief, else fallback string."""
    if isinstance(recommendation, dict):
        label = (
            recommendation.get("concept_name")
            or recommendation.get("conceptName")
            or recommendation.get("brand_name")
        )
        if label:
            return str(label)
    if isinstance(base_brief, dict):
        label = base_brief.get("conceptName") or base_brief.get("businessName")
        if label:
            return str(label)
    return "Brand"


def _generate_nav(site_pages: list, recommendation: dict, base_brief: dict) -> str:
    """Generate the consistent multi-page nav. Returns one HTML string
    containing the <nav>, the brand mark, the link list, and the
    accompanying <style> block.

    Designed to look right when injected into any of the four page types
    by `_inject_nav`. The nav is fixed, blurred, and z-index 100 so it
    sits above hero content without disturbing page layout.
    """
    from studio_page_types import get_page_type

    brand_label = _resolve_brand_label(recommendation, base_brief)

    nav_items = []
    for pid in site_pages:
        page = get_page_type(pid)
        if page and page.get("has_nav"):
            nav_items.append(
                f'<a href="{page["slug"]}" data-nav-link data-page="{pid}">{page["name"]}</a>'
            )

    nav_html = (
        '<nav class="solutionist-multipage-nav" data-multipage-nav '
        'style="position:fixed;top:0;left:0;right:0;z-index:100;'
        'padding:1rem clamp(1rem, 3vw, 2rem);'
        'display:flex;justify-content:space-between;align-items:center;'
        '-webkit-backdrop-filter:blur(20px);backdrop-filter:blur(20px);'
        'background:rgba(0,0,0,0.4);'
        'transition:all 0.4s cubic-bezier(0.16, 1, 0.3, 1);">\n'
        '  <a href="/" class="solutionist-multipage-brand" '
        'style="display:flex;align-items:center;gap:0.6rem;text-decoration:none;'
        'color:inherit;font-weight:700;letter-spacing:0.18em;'
        'text-transform:uppercase;font-size:0.78rem;">\n'
        '    <span style="display:inline-block;width:14px;height:14px;'
        'background:var(--accent, #c9a84c);transform:rotate(45deg);'
        'border-radius:2px;"></span>\n'
        f'    <span>{brand_label}</span>\n'
        '  </a>\n'
        '  <div class="solutionist-multipage-links" '
        'style="display:flex;gap:1.5rem;align-items:center;font-size:0.78rem;'
        'letter-spacing:0.18em;text-transform:uppercase;font-weight:700;">\n'
        f'    {"".join(nav_items)}\n'
        '  </div>\n'
        '</nav>\n'
    )

    nav_style = (
        "<style data-pass=\"3-8g-multipage-nav\">\n"
        ".solutionist-multipage-nav a[data-nav-link] {\n"
        "  color: rgba(255,255,255,0.65);\n"
        "  text-decoration: none;\n"
        "  transition: color 0.3s cubic-bezier(0.16, 1, 0.3, 1);\n"
        "}\n"
        ".solutionist-multipage-nav a[data-nav-link]:hover,\n"
        ".solutionist-multipage-nav a[data-nav-link][data-page-active] {\n"
        "  color: var(--accent, #c9a84c);\n"
        "}\n"
        "@media (max-width: 700px) {\n"
        "  .solutionist-multipage-links { display: none; }\n"
        "}\n"
        "body.has-multipage-nav { padding-top: 64px; }\n"
        "</style>\n"
    )

    return nav_style + nav_html


def _inject_nav(html: str, nav_html: str) -> str:
    """Inject the nav block immediately after <body...>.

    Idempotent — if a previous nav with the same data-pass marker is
    already present we replace it, so re-running the multi-page builder
    on persisted HTML doesn't stack multiple navs.
    """
    if not html or not nav_html:
        return html

    # Idempotency: strip an old nav if we previously injected one.
    if 'data-pass="3-8g-multipage-nav"' in html:
        # Crude but effective — match the old style block + nav we wrote
        import re as _re
        html = _re.sub(
            r'<style data-pass="3-8g-multipage-nav">.*?</style>\s*'
            r'<nav class="solutionist-multipage-nav".*?</nav>\s*',
            "",
            html,
            count=1,
            flags=_re.DOTALL,
        )

    if "<body>" in html:
        return html.replace("<body>", "<body>\n" + nav_html, 1)

    # body has attributes
    idx = html.find("<body ")
    if idx >= 0:
        end = html.find(">", idx)
        if end > 0:
            return html[: end + 1] + "\n" + nav_html + html[end + 1:]

    # Couldn't find body — append nav at the start of html as a safety net.
    return nav_html + html
