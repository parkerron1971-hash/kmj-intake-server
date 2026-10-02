"""Build the KMJ Creative Solutions site.

Installing it is NOT a step here: site_sync.py renders these pages on
every boot through render_pages() and writes them into the business_sites
row when their hash changed. Merge → deploy → live.

    python sites/kmj-creative-solutions/build.py [--inline]

Writes:
  sites/kmj-creative-solutions/dist/{home,about,services,contact}.html
      — the assembled pages, for a local look in a browser
  supabase/ROLLBACK-2026-09-03-kmj-site-manual.sql
      — restores the previous html_content / generated_pages / html_source
        from the backup site_sync keeps under site_config.manual_backup

Serve-time tokens left in the HTML on purpose (public_site.py fills them):
  {{BUSINESS_EMAIL}}       the business's verified sending address
  {{PRODUCTS_SECTION}}     live products flagged display_on_website
  {{GALLERY_SECTION}} / {{TESTIMONIALS_SECTION}}
                           kept inside an HTML comment so nothing is appended
Build-time tokens (filled here):
  {{LOGO}} {{SIGNATURE}}   URLs of assets/logo.webp and assets/signature.webp,
                           served by GET /public/site-assets/{slug}/{file}
                           (data URIs with --inline, for a local look at dist/)
  {{PORTRAIT}}             the founder art block (a photo once Kevin sends one)
  {{API_BASE}} {{BUSINESS_ID}} {{SOLUTIONIST_URL}}
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))

SLUG = "kmj-creative-solutions"
BUSINESS_ID = "12773842-3cc6-41a7-9094-b8606e3f7549"
API_BASE = "https://kmj-intake-server-production.up.railway.app"
SOLUTIONIST_URL = "https://mysolutionist.app"
DATE = "2026-09-03"
DOLLAR = "$kmj$"

PAGES = {
    "home": ("KMJ Creative Solutions — Elevate Your Vision, Amplify Your Impact",
             "A solutionist practice. Coaching, consulting, and creative direction for founders and leaders who need clarity on the idea, the offer, and the shift in front of them."),
    "about": ("About Kevin McCloud Jr. — KMJ Creative Solutions",
              "Ten years in pastoral ministry, a practice in creative counsel, and the Solutionist System built from it."),
    "services": ("Services — KMJ Creative Solutions",
                 "Embrace the Shift, the ninety-day intensive. Clarity Sessions for a business in motion. Creative direction when the idea needs a face."),
    "contact": ("Contact — KMJ Creative Solutions",
                "Book a thirty-minute discovery call, or write and tell me where you stand."),
}

FONTS = ("https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,500;12..96,700;12..96,800"
         "&amp;family=Cormorant+Garamond:ital,wght@1,500&amp;family=Work+Sans:wght@400;500;600&amp;display=swap")


def _read(name: str) -> str:
    with open(os.path.join(HERE, name), encoding="utf-8") as f:
        return f.read()


def _data_uri(name: str) -> str:
    with open(os.path.join(HERE, "assets", name), "rb") as f:
        return "data:image/webp;base64," + base64.b64encode(f.read()).decode("ascii")


def _asset_url(name: str) -> str:
    """Served by public_site.GET /public/site-assets/{slug}/{file}. The
    content hash in the query busts caches when the file changes."""
    with open(os.path.join(HERE, "assets", name), "rb") as f:
        digest = hashlib.sha256(f.read()).hexdigest()[:10]
    return f"{API_BASE}/public/site-assets/{SLUG}/{name}?v={digest}"


def _image_refs(inline: bool):
    if inline:
        return _data_uri("logo.webp"), _data_uri("signature.webp")
    return _asset_url("logo.webp"), _asset_url("signature.webp")


def _photo_refs(inline: bool):
    """Kevin's portrait (assets/kevin.webp, a transparent cut-out) and the
    Solutionist System dashboard (assets/dashboard.webp)."""
    if inline:
        return _data_uri("kevin.webp"), _data_uri("dashboard.webp")
    return _asset_url("kevin.webp"), _asset_url("dashboard.webp")


def assemble(page: str, css: str, nav: str, footer: str, logo: str, signature: str,
             kevin: str = "", dashboard: str = "") -> str:
    if not kevin or not dashboard:
        kevin, dashboard = _photo_refs(inline=logo.startswith("data:"))
    title, desc = PAGES[page]
    body = _read(f"{page}.html")
    html = (
        "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n"
        "<meta charset=\"utf-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        f"<title>{title}</title>\n"
        f"<meta name=\"description\" content=\"{desc}\">\n"
        "<link rel=\"preconnect\" href=\"https://fonts.googleapis.com\">\n"
        "<link rel=\"preconnect\" href=\"https://fonts.gstatic.com\" crossorigin>\n"
        f"<link rel=\"stylesheet\" href=\"{FONTS}\">\n"
        f"<style>\n{css}\n</style>\n"
        "</head>\n<body>\n"
        f"{nav}\n<main>\n{body}\n</main>\n{footer}\n"
        "</body>\n</html>\n"
    )
    html = (html.replace("{{LOGO}}", logo)
                .replace("{{SIGNATURE}}", signature)
                .replace("{{KEVIN}}", kevin)
                .replace("{{DASHBOARD}}", dashboard)
                .replace("{{API_BASE}}", API_BASE)
                .replace("{{BUSINESS_ID}}", BUSINESS_ID)
                .replace("{{SOLUTIONIST_URL}}", SOLUTIONIST_URL))
    leftover = sorted(set(re.findall(r"\{\{([A-Z_]+)\}\}", html))
                      - {"BUSINESS_EMAIL", "PRODUCTS_SECTION", "GALLERY_SECTION", "TESTIMONIALS_SECTION"})
    if leftover:
        raise SystemExit(f"{page}: unfilled tokens {leftover}")
    if DOLLAR in html:
        raise SystemExit(f"{page}: contains the SQL quote tag {DOLLAR}")
    return html


def render_pages(inline: bool = False) -> dict:
    """The site_sync contract: every page, assembled, keyed by page id."""
    css = _read("site.css")
    nav = _read("_nav.html")
    footer = _read("_footer.html")
    logo, signature = _image_refs(inline)
    kevin, dashboard = _photo_refs(inline)
    return {p: assemble(p, css, nav, footer, logo, signature, kevin, dashboard) for p in PAGES}


def main() -> None:
    inline = "--inline" in sys.argv
    pages = render_pages(inline)

    dist = os.path.join(HERE, "dist")
    os.makedirs(dist, exist_ok=True)
    for p, html in pages.items():
        with open(os.path.join(dist, f"{p}.html"), "w", encoding="utf-8") as f:
            f.write(html)
        print(f"{p}: {len(html):,} bytes")
    if inline:
        print("--inline: dist/ has data-URI images for a local look")
        return

    rollback_sql = f"""-- ROLLBACK-{DATE}-kmj-site-manual.sql
-- Puts back the page set site_sync replaced when it first installed the
-- hand-built site (kept under site_config.manual_backup). Set SITE_SYNC=off
-- on Railway first, or the next boot installs it again.
BEGIN;

UPDATE business_sites
SET
  html_content = site_config->'manual_backup'->>'html_content',
  site_config = (site_config
    || jsonb_build_object(
      'html_source', COALESCE(site_config->'manual_backup'->'html_source', 'null'::jsonb),
      'generated_pages', COALESCE(site_config->'manual_backup'->'generated_pages', '{{}}'::jsonb),
      'site_pages', COALESCE(site_config->'manual_backup'->'site_pages', 'null'::jsonb)
    )) - 'manual_backup',
  updated_at = now()
WHERE slug = '{SLUG}' AND site_config ? 'manual_backup';

-- Expect: UPDATE 1
COMMIT;
"""
    sb = os.path.join(ROOT, "supabase")
    with open(os.path.join(sb, f"ROLLBACK-{DATE}-kmj-site-manual.sql"), "w", encoding="utf-8") as f:
        f.write(rollback_sql)
    print(f"wrote supabase/ROLLBACK-{DATE}-kmj-site-manual.sql; install happens on deploy (site_sync.py)")


if __name__ == "__main__":
    main()
