"""Build the Love City Church site (lovecityc.com, Muskegon, MI).

Hand-built, like sites/kmj-creative-solutions/. Installing it is NOT a step
here: site_sync.py renders these pages on every boot through render_pages()
and writes them into the business_sites row whose slug is SLUG, but only
when that row belongs to BUSINESS_ID.

    python sites/love-city-church/build.py [--inline]

Writes sites/love-city-church/dist/<page>.html, the assembled pages, for a
local look in a browser (--inline puts the images in as data URIs).

BUSINESS_ID is Love City Church's Solutionist business; the forms post to
it too. site_sync refuses a row whose business_id doesn't match, and does
nothing when there is no row.

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
  {{MARK}} {{MARK_MASK}}   the church's heart mark (mark.svg), inline or as a
                           CSS mask; {{MARK_SOLID_MASK}} its filled
                           silhouette (mark-solid.svg)
  {{API_BASE}} {{BUSINESS_ID}} and the outside links in LINKS

REDIRECTS maps the old site's addresses to these pages (site_sync stores
them with the pages).

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
from urllib.parse import quote

HERE = os.path.dirname(os.path.abspath(__file__))

SLUG = "love-city-church"
# Love City Church's business. Its business_sites row (slug SLUG) was made
# through Giving.
BUSINESS_ID = "009e9a2c-3e81-4bfc-a92a-205a8806aa99"
API_BASE = "https://kmj-intake-server-production.up.railway.app"

PAGES = {
    "home": ("Love City Church | Muskegon, Michigan",
             "A loving church in Muskegon, empowered to make a difference in the lives of all people. "
             "Sunday service at 11am at 1084 Allen Ave, Muskegon, MI."),
    "visit": ("Plan your visit | Love City Church",
              "Service times, what to expect, and how to find Love City Church at 1084 Allen Ave, Muskegon, MI."),
    "about": ("About us | Love City Church",
              "Our vision, the eight C.I.T.Y. L.O.V.E. culture keys, and our senior leaders, Pastor Kevin McCloud Jr. and Lady Jessica McCloud."),
    "beliefs": ("What we believe | Love City Church",
                "The core beliefs of Love City Church, rooted in the foundational truths of the Bible."),
    "sermons": ("Sermons | Love City Church",
                "Watch the latest message and every sermon series from the Love City Experience."),
    "give": ("Give | Love City Church",
             "Give online to Love City Church: tithes, offering, outreach and the youth department."),
    "ministries": ("Ministries | Love City Church",
                   "Love Works Food Pantry, youth, Sisters in the City, pastoral care, Next Step, Leaderschool, and ways to serve."),
    "events": ("Events | Love City Church",
               "What happens every week at Love City Church in Muskegon, and moments from our church family."),
    "connect": ("Connect | Love City Church",
                "Fill out a connect card or send a prayer request. We'd love to meet you."),
    # /watch, not /live: GET /live is an authenticated API route registered
    # before the public-site catch-all (live_router.py), so it 401s.
    "watch": ("Watch live | Love City Church",
             "Join Love City Church online, Sundays at 11am and Thursdays at 6pm."),
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
    "SERMON_LIBRARY": "https://subsplash.com/u/cityofloveministries/media",
}

# The old SnapPages site's addresses (its sitemap, and the sermon library
# under /media), each sent where that content lives now. site_sync stores
# them; public_site answers each with a 301 wherever the site would
# otherwise 404, keeping the visitor's own ?utm_… parameters. Old forms land
# on the connect card with the same interest ticked. /my-love-nation, the
# old members-only page, has no home here and stays a 404. /live is not
# here: GET /live is an API route ahead of the site, and redirecting it
# safely needs the Worker to vouch for the host (see the worklog).
REDIRECTS = {
    "/mission-and-vision": "/about",
    "/our-senior-leadership": "/about#pastors",
    "/what-we-believe": "/beliefs",
    "/i-m-new": "/visit",
    "/welcomehome": "/visit",
    "/services-and-events": "/events",
    "/citynewsletter": "/events",
    "/awards": "/events",
    "/harvestdinner": "/events",
    "/bible-reading-group-signup": "/events",
    "/media": "/sermons",
    "/media/*": "/sermons",
    "/subsplash-media": "/sermons",
    "/connect-with-us": "/connect#connect-card",
    "/booking": "/connect#connect-card",
    "/prayer-request": "/connect#prayer",
    "/membership-form-update": "/connect?interest=membership#connect-card",
    "/baptism": "/connect?interest=baptism#connect-card",
    "/membercare": "/connect?interest=pastoral-care#connect-card",
    "/volunteer": "/connect?interest=serve#connect-card",
    "/ministryworks": "/connect?interest=serve#connect-card",
    "/city-serve": "/connect?interest=serve#connect-card",
    "/ns-sign-up": "/connect?interest=next-step#connect-card",
    "/next-step-ministry-training": "/ministries#training-title",
    "/leaderschool": "/ministries#training-title",
    "/missions": "/ministries#love-works",
    "/children": "/ministries",
    "/preschool": "/ministries",
    "/students": "/ministries",
    "/young-adults": "/ministries",
    "/men": "/ministries",
    "/women": "/ministries",
    "/small-groups": "/ministries",
    "/small-groups-20-groups": "/ministries",
    "/small-groups-less-than-20-groups": "/ministries",
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


def _mark_refs() -> dict:
    """The church's heart mark (mark.svg, traced from its own artwork): the
    heart with its side towers, and the centre tower, as two paths.
    {{MARK}} is the inline SVG (coloured and animated by the CSS);
    {{MARK_MASK}} is the same shape as a CSS mask, for small repeats."""
    def as_mask(svg: str) -> str:
        viewbox = re.search(r'viewBox="([^"]+)"', svg).group(1)
        d = "".join(re.findall(r' d="([^"]+)"', svg))
        mask = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{viewbox}"><path d="{d}"/></svg>'
        return 'url("data:image/svg+xml,' + quote(mask, safe=" =:/") + '")'

    svg = _read("mark.svg").strip()
    # mark-solid.svg: the same heart's silhouette, filled, for the
    # heart-shaped window that opens Home's photo-wall scene
    return {"MARK": svg, "MARK_MASK": as_mask(svg), "MARK_SOLID_MASK": as_mask(_read("mark-solid.svg"))}


def _mark_current(nav: str, page: str) -> str:
    """aria-current on the nav link for the page being built."""
    if page == "home":
        return nav.replace('<a href="/">Home</a>', '<a href="/" aria-current="page">Home</a>')
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
    refs.update(_mark_refs())
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
    print(f"install happens on deploy (site_sync.py), into the {SLUG} row")


if __name__ == "__main__":
    main()
