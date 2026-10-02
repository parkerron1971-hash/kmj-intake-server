"""
site_news.py — the news feed a practitioner owns outright.

WHY THIS EXISTS. Every other place a small business can publish belongs
to somebody else, and 2026 made that concrete: Instagram publishing needs
an App Review that can be denied without a reason, TikTok forces posts to
SELF_ONLY until an audit passes, X charges per post. Their own site is
the one channel with no gatekeeper, no rate limit, and nothing to revoke
— and it is the only one that compounds, because a page at a stable URL
is still earning search traffic a year after it was written.

So a post written in Grow → Content lands here first, and social becomes
the amplification rather than the destination.

WHAT THIS IS NOT. It deliberately does not hook `_inject_dynamic_sections`
in public_site.py. That injector returns early for composed pages —
modern sites render their own sections from live data at compose time —
so a news block bolted on there would appear on legacy templates only,
which is close to nowhere. These are standalone pages instead: they work
the same for every site regardless of how it was built, and a standalone
indexable page at its own URL is where the search value actually lives.

STORAGE. `businesses.settings.website_content.news`, a JSONB list beside
`testimonials`. No migration — the same shape TestimonialsManager already
writes to, so the frontend half is a settings PATCH like any other.

Each entry:
    {id, title, body, image_url?, published_at, slug?}

`body` is the practitioner's own words and is escaped, never parsed —
we render their paragraphs, we do not accept their markup.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

MAX_POSTS = 200
_SUMMARY_CHARS = 180


def _esc(text: Any) -> str:
    """HTML escape. Mirrors public_site._esc so this module can be
    imported and unit-tested without dragging the router in."""
    if text is None:
        return ""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def slugify(title: str, fallback: str = "post") -> str:
    """A URL-safe slug for a post title.

    Accented characters are folded rather than dropped, so 'Café hours'
    becomes 'cafe-hours' instead of '-hours' — a practitioner whose
    business name carries a diacritic should not get a mangled URL.
    """
    text = unicodedata.normalize("NFKD", str(title or ""))
    text = text.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    text = re.sub(r"-{2,}", "-", text)
    return text[:80] or fallback


def _parse_when(value: Any) -> Optional[datetime]:
    """Best-effort ISO parse. A post whose date we cannot read is not a
    broken post — it sorts last and simply shows no date."""
    if not value:
        return None
    raw = str(value).strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _display_date(when: Optional[datetime]) -> str:
    if not when:
        return ""
    return when.strftime("%B %-d, %Y") if _supports_dash() else when.strftime("%B %d, %Y")


def _supports_dash() -> bool:
    """`%-d` is glibc-only and raises on Windows. Probe once rather than
    shipping a page that renders locally and 500s on the host, or the
    reverse."""
    try:
        datetime(2026, 1, 5).strftime("%-d")
        return True
    except ValueError:
        return False


def normalize_posts(raw: Any) -> List[Dict[str, Any]]:
    """Take whatever is in settings and return renderable posts, newest
    first. Anything without a title AND a body is dropped: a headline
    with no words behind it is a broken page with a real URL, which is
    worse for search than no page at all.

    Slugs are made unique here rather than trusted from storage — two
    posts called "We're hiring" a year apart must not resolve to the
    same page, and the frontend cannot see the whole list when it writes.
    """
    if not isinstance(raw, list):
        return []

    posts: List[Dict[str, Any]] = []
    for item in raw[:MAX_POSTS]:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        body = str(item.get("body") or "").strip()
        if not title or not body:
            continue
        when = _parse_when(item.get("published_at"))
        posts.append({
            "id": str(item.get("id") or ""),
            "title": title,
            "body": body,
            "image_url": str(item.get("image_url") or "").strip() or None,
            "published_at": when,
            "slug": slugify(item.get("slug") or title),
        })

    # Newest first; undated posts sort last instead of crashing the sort.
    posts.sort(key=lambda p: p["published_at"] or datetime.min.replace(tzinfo=timezone.utc),
               reverse=True)

    seen: Dict[str, int] = {}
    for post in posts:
        base = post["slug"]
        if base in seen:
            seen[base] += 1
            post["slug"] = f"{base}-{seen[base]}"
        else:
            seen[base] = 1
    return posts


def find_post(posts: List[Dict[str, Any]], slug: str) -> Optional[Dict[str, Any]]:
    wanted = str(slug or "").strip().lower()
    for post in posts:
        if post["slug"] == wanted:
            return post
    return None


def summarize(body: str, limit: int = _SUMMARY_CHARS) -> str:
    """A meta description: one flat line, cut on a word boundary."""
    flat = re.sub(r"\s+", " ", str(body or "")).strip()
    if len(flat) <= limit:
        return flat
    return flat[:limit].rsplit(" ", 1)[0].rstrip(",.;:") + "…"


def paragraphs(body: str, style: str = "") -> str:
    """The author's line breaks, preserved as paragraphs. Their text is
    escaped first — we render their words, not their markup.

    `style` is empty by default because the other caller (the marketing
    site) brings its own stylesheet, and an inline style would silently
    beat it. The practitioner shell has no stylesheet for these, so it
    passes one in."""
    attr = f' style="{style}"' if style else ""
    blocks = [b.strip() for b in re.split(r"\n\s*\n", str(body or "")) if b.strip()]
    return "".join(
        f"<p{attr}>" + _esc(b).replace("\n", "<br />") + "</p>"
        for b in blocks
    )


def _paragraphs(body: str) -> str:
    """The practitioner-shell form: same markup, with the inline margin
    that shell has always relied on."""
    return paragraphs(body, "margin:0 0 18px;")


def display_date(when: Optional[datetime]) -> str:
    """Public form of _display_date — the marketing site renders the
    same dates in its own shell (marketing_pages.render_news_index)."""
    return _display_date(when)


def _page_shell(title: str, description: str, canonical: str, brand: str,
                body_html: str, head_extra: str = "") -> str:
    """One responsive, self-contained document. No external stylesheet
    and no font fetch — this page has to render the same whether it is
    served under the platform subdomain or a connected custom domain."""
    return (
        "<!DOCTYPE html><html lang=\"en\"><head>"
        '<meta charset="utf-8" />'
        '<meta name="viewport" content="width=device-width, initial-scale=1" />'
        f"<title>{_esc(title)}</title>"
        f'<meta name="description" content="{_esc(description)}" />'
        f'<link rel="canonical" href="{_esc(canonical)}" />'
        f'<meta property="og:title" content="{_esc(title)}" />'
        f'<meta property="og:description" content="{_esc(description)}" />'
        f'<meta property="og:url" content="{_esc(canonical)}" />'
        '<meta property="og:type" content="article" />'
        f"{head_extra}"
        "<style>"
        "*{box-sizing:border-box}"
        "body{margin:0;background:#fff;color:#222;"
        "font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;"
        "line-height:1.65;-webkit-font-smoothing:antialiased}"
        ".wrap{max-width:720px;margin:0 auto;padding:48px 20px 72px}"
        "h1{font-size:34px;line-height:1.2;margin:0 0 10px;color:#111}"
        "h2{font-size:21px;line-height:1.3;margin:0 0 6px}"
        "h2 a{color:#111;text-decoration:none}"
        "h2 a:hover{text-decoration:underline}"
        ".date{font-size:13px;color:#777;margin:0 0 28px}"
        ".entry{padding:26px 0;border-bottom:1px solid #ececec}"
        ".entry:last-child{border-bottom:none}"
        ".entry p{margin:8px 0 0;color:#444}"
        "img{max-width:100%;height:auto;border-radius:10px;display:block}"
        ".back{display:inline-block;margin-top:40px;font-size:14px;text-decoration:none}"
        ".empty{color:#777}"
        "@media(max-width:600px){.wrap{padding:32px 18px 56px}h1{font-size:27px}}"
        "</style></head><body><div class=\"wrap\">"
        f"{body_html}"
        "</div></body></html>"
    )


def render_listing_page(posts: List[Dict[str, Any]], *, business_name: str,
                        origin: str, brand: str = "#222") -> str:
    """The archive. Every entry links to its own indexable page."""
    heading = f"News from {business_name}" if business_name else "News"
    canonical = f"{origin}/news"

    if not posts:
        # A published-but-empty feed is a real state, not an error: the
        # page exists because the site links to it. Say so plainly
        # rather than 404-ing a URL search may already have seen.
        entries = '<p class="empty">Nothing posted yet — check back soon.</p>'
    else:
        rows = []
        for post in posts:
            when = _display_date(post["published_at"])
            date_html = f'<p class="date" style="margin:6px 0 0;">{_esc(when)}</p>' if when else ""
            rows.append(
                '<article class="entry">'
                f'<h2><a href="{origin}/news/{post["slug"]}">{_esc(post["title"])}</a></h2>'
                f'{date_html}'
                f'<p>{_esc(summarize(post["body"]))}</p>'
                "</article>"
            )
        entries = "".join(rows)

    body = (
        f"<h1>{_esc(heading)}</h1>"
        f"{entries}"
        f'<a class="back" style="color:{_esc(brand)};" href="{origin}/">&larr; Back to the site</a>'
    )
    return _page_shell(
        title=f"News — {business_name}" if business_name else "News",
        description=f"The latest from {business_name}." if business_name else "The latest news.",
        canonical=canonical, brand=brand, body_html=body,
    )


def _article_jsonld(post: Dict[str, Any], business_name: str, url: str) -> str:
    """Article schema. AI answer engines read structured data to decide
    which businesses to cite, so a post without it is a post that can be
    read but not attributed."""
    import json

    data: Dict[str, Any] = {
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": post["title"][:110],
        "description": summarize(post["body"]),
        "mainEntityOfPage": {"@type": "WebPage", "@id": url},
    }
    if business_name:
        data["author"] = {"@type": "Organization", "name": business_name}
        data["publisher"] = {"@type": "Organization", "name": business_name}
    if post["published_at"]:
        data["datePublished"] = post["published_at"].isoformat()
    if post["image_url"]:
        data["image"] = post["image_url"]
    # </script> inside the payload would close the block early and spill
    # JSON into the document.
    return ('<script type="application/ld+json">'
            + json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
            + "</script>")


def render_post_page(post: Dict[str, Any], *, business_name: str,
                     origin: str, brand: str = "#222") -> str:
    """One post, at its own address, carrying its own metadata."""
    url = f"{origin}/news/{post['slug']}"
    when = _display_date(post["published_at"])
    date_html = f'<p class="date">{_esc(when)}</p>' if when else ""
    image_html = (
        f'<img src="{_esc(post["image_url"])}" alt="{_esc(post["title"])}" '
        'style="margin:0 0 24px;" />'
        if post["image_url"] else ""
    )
    body = (
        f'<h1>{_esc(post["title"])}</h1>'
        f"{date_html}"
        f"{image_html}"
        f'{_paragraphs(post["body"])}'
        f'<a class="back" style="color:{_esc(brand)};" href="{origin}/news">&larr; All news</a>'
    )
    title = f"{post['title']} — {business_name}" if business_name else post["title"]
    return _page_shell(
        title=title,
        description=summarize(post["body"]),
        canonical=url,
        brand=brand,
        body_html=body,
        head_extra=_article_jsonld(post, business_name, url),
    )
