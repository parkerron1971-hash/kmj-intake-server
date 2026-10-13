"""Build the Love City Church site (lovecityc.com, Muskegon, MI).

Hand-built, like sites/kmj-creative-solutions/. Installing it is NOT a step
here: site_sync.py renders these pages on every boot through render_pages()
and writes them into the business_sites row whose slug is SLUG, but only
when that row belongs to BUSINESS_ID.

    python sites/love-city-church/build.py [--inline]

Writes sites/love-city-church/dist/<page>.html, the assembled pages, for a
local look in a browser (--inline puts the images in as data URIs).

BUSINESS_ID is a PLACEHOLDER until the church's Solutionist account exists.
site_sync refuses a row whose business_id doesn't match, and does nothing
when there is no row, so the placeholder can never install anywhere. When
the account exists, put its id in BUSINESS_ID; the forms post to it too.

Serve-time tokens left in the HTML on purpose (public_site.py fills them):
  {{BUSINESS_EMAIL}}       the church's verified sending address; with none,
                           the element marked data-needs-email is removed
  {{PRODUCTS_SECTION}} {{GALLERY_SECTION}} {{TESTIMONIALS_SECTION}}
                           kept inside an HTML comment in the footer, so the
                           platform fills them in place instead of appending
                           sections before </body>
Build-time tokens (filled here):
  {{IMG_<NAME>}}           the URL of assets/<name>.webp ({{IMG_LOGO_INK}} is
                           logo-ink.webp), served by
                           GET {{API_BASE}}/public/site-assets/{slug}/{file}
                           (data URIs with --inline). Photos are the church's
                           own, from its Facebook page, in the site's plum
                           duotone.
  {{API_BASE}} {{BUSINESS_ID}} and the outside links in LINKS

Scripts: site.js (the phone menu) goes on every page; forms.js (the one
place the connect card and prayer request are submitted) goes on any page
with a data-church-form.
"""
from __future__ import annotations

import base64
import hashlib
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

SLUG = "love-city-church"
# PLACEHOLDER: the church's Solutionist account doesn't exist yet. Replace
# with its business id once Kevin has created it.
BUSINESS_ID = "PLACEHOLDER-love-city-church-account-not-created-yet"
API_BASE = "https://kmj-intake-server-production.up.railway.app"

PAGES = {
    "home": ("Love City Church | Muskegon, Michigan",
             "A loving church in Muskegon, empowered to make a difference in the lives of all people. "
             "Sundays at 11am at 1084 Allen Ave, and Thursdays at 6pm."),
    "visit": ("Plan your visit | Love City Church",
              "Service times, what to expect, and how to find Love City Church at 1084 Allen Ave, Muskegon, MI."),
}

def _assets() -> dict:
    """Every assets/<name>.webp as the build-time token IMG_<NAME>
    (church-family.webp is {{IMG_CHURCH_FAMILY}})."""
    names = sorted(n for n in os.listdir(os.path.join(HERE, "assets")) if n.endswith(".webp"))
    return {"IMG_" + n[:-5].upper().replace("-", "_"): n for n in names}

_ADDRESS_Q = "1084+Allen+Ave%2C+Muskegon%2C+MI+49442"
LINKS = {
    "MAPS_URL": f"https://www.google.com/maps/dir/?api=1&amp;destination={_ADDRESS_Q}",
    "MAPS_EMBED": f"https://www.google.com/maps?q={_ADDRESS_Q}&amp;output=embed",
    "FACEBOOK_URL": "https://www.facebook.com/lovecitynation/",
    "STORE_URL": "https://lovecity.printify.me/",
    "SUBSPLASH_LATEST": "https://subsplash.com/u/-7MJWGR/media/embed/d/*",
    "SUBSPLASH_GIVE": "https://subsplash.com/u/-7MJWGR/give?embed=true",
    "SERMON_LIBRARY": "https://subsplash.com/u/cityofloveministries/media",
}

SERVE_TIME_TOKENS = {"BUSINESS_EMAIL", "PRODUCTS_SECTION", "GALLERY_SECTION", "TESTIMONIALS_SECTION"}

FONTS = "https://fonts.googleapis.com/css2?family=Archivo:wdth,wght@62..125,400..900&amp;display=swap"
THEME_COLOR = "#1C0B1F"


def _read(name: str) -> str:
    with open(os.path.join(HERE, name), encoding="utf-8") as f:
        return f.read()


def _asset_ref(name: str, inline: bool) -> str:
    with open(os.path.join(HERE, "assets", name), "rb") as f:
        data = f.read()
    if inline:
        return "data:image/webp;base64," + base64.b64encode(data).decode("ascii")
    # The content hash busts caches when the file changes.
    return f"{API_BASE}/public/site-assets/{SLUG}/{name}?v={hashlib.sha256(data).hexdigest()[:10]}"


def _mark_current(nav: str, page: str) -> str:
    """aria-current on the nav link for the page being built."""
    if page == "home":
        return nav
    return nav.replace(f'href="/{page}"', f'href="/{page}" aria-current="page"')


def assemble(page: str, parts: dict, refs: dict) -> str:
    title, desc = PAGES[page]
    body = _read(f"{page}.html")
    scripts = f"<script>\n{parts['site_js']}</script>\n"
    if "data-church-form" in body:
        scripts += f"<script>\n{parts['forms_js']}</script>\n"
    html = (
        "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n"
        "<meta charset=\"utf-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        f"<title>{title}</title>\n"
        f"<meta name=\"description\" content=\"{desc}\">\n"
        f"<meta name=\"theme-color\" content=\"{THEME_COLOR}\">\n"
        # Before first paint, so the phone menu never flashes open.
        "<script>document.documentElement.classList.add('js')</script>\n"
        "<link rel=\"preconnect\" href=\"https://fonts.googleapis.com\">\n"
        "<link rel=\"preconnect\" href=\"https://fonts.gstatic.com\" crossorigin>\n"
        f"<link rel=\"stylesheet\" href=\"{FONTS}\">\n"
        f"<style>\n{parts['css']}\n</style>\n"
        "</head>\n<body>\n"
        f"{_mark_current(parts['nav'], page)}\n<main id=\"main\">\n{body}\n</main>\n{parts['footer']}\n"
        f"{scripts}"
        "</body>\n</html>\n"
    )
    for token, value in refs.items():
        html = html.replace("{{" + token + "}}", value)
    leftover = sorted(set(re.findall(r"\{\{([A-Z_]+)\}\}", html)) - SERVE_TIME_TOKENS)
    if leftover:
        raise SystemExit(f"{page}: unfilled tokens {leftover}")
    return html


def render_pages(inline: bool = False) -> dict:
    """The site_sync contract: every page, assembled, keyed by page id."""
    parts = {
        "css": _read("site.css"),
        "nav": _read("_nav.html"),
        "footer": _read("_footer.html"),
        "site_js": _read("site.js"),
        "forms_js": _read("forms.js"),
    }
    refs = {token: _asset_ref(name, inline) for token, name in _assets().items()}
    refs.update(LINKS)
    refs.update({"API_BASE": API_BASE, "BUSINESS_ID": BUSINESS_ID})
    return {p: assemble(p, parts, refs) for p in PAGES}


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
    print("install happens on deploy (site_sync.py), once BUSINESS_ID is the church's real id")


if __name__ == "__main__":
    main()
