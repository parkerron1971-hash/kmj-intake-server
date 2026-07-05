"""
reference_analyzer.py — Smart Sites Arc 5 "Design Depth".

ACTUALLY STUDY the reference sites an owner names in the design
interview (site_prefs.inspiration_urls): fetch each one and extract
deterministic design evidence — palette, typography classes, density,
and how the site describes itself — with NO LLM involved. The result
feeds the DRL intake text and the DRO authoring prompt as DIRECTION
EVIDENCE (mood / contrast / type feel), never as a copy source.

Security stance (these are owner-supplied URLs fetched server-side, so
SSRF is the threat model):
  - http/https only, default ports only (80/443), no raw-IP hosts
  - hostname is RESOLVED and every address checked: private / loopback /
    link-local / reserved / multicast / unspecified all rejected
    (covers 10.x, 172.16-31, 192.168.x, 127.x, 169.254.x + the cloud
    metadata IP, ::1, fc00::/7, fe80::/10)
  - redirects followed manually (≤3 hops) with EVERY hop re-guarded
  - 8s timeout per fetch, body read capped at 600KB, text/html only
    (linked stylesheets: at most 2, same guards, text/css)

FAIL SOFT everywhere: a dead / hostile / non-HTML URL yields
{url, ok: False, error} and never blocks a compose.
"""
from __future__ import annotations

import ipaddress
import logging
import re
import socket
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

import httpx

logger = logging.getLogger("reference_analyzer")

MAX_URLS = 3
FETCH_TIMEOUT_S = 8.0
MAX_REDIRECTS = 3
MAX_BYTES = 600 * 1024
MAX_STYLESHEETS = 2
_UA = ("Mozilla/5.0 (compatible; SolutionistDesignStudy/1.0; "
       "+https://mysolutionist.app)")


# ─── SSRF guard ───────────────────────────────────────────────────────

def _ip_blocked(addr: str) -> bool:
    """True when an address must never be fetched server-side."""
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return True                     # unparseable → refuse
    return bool(ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_reserved or ip.is_multicast or ip.is_unspecified)


def guard_url(url: str, *, resolve: bool = True) -> Optional[str]:
    """SSRF check for one URL. Returns an error string, or None when the
    URL is safe to fetch. `resolve=False` skips the DNS step (unit tests
    without network); the scheme/port/raw-IP checks always run."""
    try:
        p = urlparse(str(url or "").strip())
    except ValueError:
        return "unparseable URL"
    if p.scheme not in ("http", "https"):
        return "only http/https URLs are fetched"
    host = (p.hostname or "").lower()
    if not host:
        return "no hostname"
    if p.port not in (None, 80, 443):
        return f"port {p.port} not allowed"
    try:
        ipaddress.ip_address(host)
        return "raw-IP hosts not allowed"
    except ValueError:
        pass                            # not an IP literal — good
    if resolve:
        try:
            infos = socket.getaddrinfo(
                host, p.port or (443 if p.scheme == "https" else 80),
                proto=socket.IPPROTO_TCP)
        except (socket.gaierror, OSError):
            return "hostname did not resolve"
        for info in infos:
            if _ip_blocked(info[4][0]):
                return "resolves to a private/reserved address"
    return None


# ─── Guarded fetch (manual redirects, capped read) ────────────────────

def _fetch_capped(client: httpx.Client, url: str,
                  want: str = "html") -> Tuple[str, str]:
    """GET with every redirect hop re-guarded, content-type enforced and
    the body read capped at MAX_BYTES. Returns (final_url, text).
    Raises ValueError on any refusal/failure."""
    cur = url
    for _hop in range(MAX_REDIRECTS + 1):
        err = guard_url(cur)
        if err:
            raise ValueError(err)
        with client.stream("GET", cur, headers={
                "User-Agent": _UA,
                "Accept": ("text/html,application/xhtml+xml;q=0.9,*/*;q=0.5"
                           if want == "html" else "text/css,*/*;q=0.5")}) as resp:
            if resp.status_code in (301, 302, 303, 307, 308):
                loc = resp.headers.get("location")
                if not loc:
                    raise ValueError("redirect without a Location header")
                cur = urljoin(cur, loc)
                continue
            if resp.status_code >= 400:
                raise ValueError(f"HTTP {resp.status_code}")
            ctype = (resp.headers.get("content-type") or "").lower()
            if want == "html" and "text/html" not in ctype:
                raise ValueError(f"not text/html ({ctype.split(';')[0] or 'no content-type'})")
            if want == "css" and not ("css" in ctype or ctype.startswith("text/")):
                raise ValueError(f"not a stylesheet ({ctype.split(';')[0]})")
            chunks: List[bytes] = []
            total = 0
            for chunk in resp.iter_bytes():
                chunks.append(chunk)
                total += len(chunk)
                if total >= MAX_BYTES:
                    break
            body = b"".join(chunks)[:MAX_BYTES]
            enc = resp.charset_encoding or "utf-8"
            return cur, body.decode(enc, errors="replace")
    raise ValueError(f"more than {MAX_REDIRECTS} redirects")


# ─── Palette extraction (deterministic) ───────────────────────────────

_STYLE_BLOCK_RE = re.compile(r"<style[^>]*>(.*?)</style>", re.I | re.S)
_STYLE_ATTR_RE = re.compile(r"""style\s*=\s*("[^"]*"|'[^']*')""", re.I)
_HEX_RE = re.compile(r"#([0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b")
_LINK_TAG_RE = re.compile(r"<link\b[^>]*>", re.I)
_HREF_RE = re.compile(r"""href\s*=\s*["']([^"']+)["']""", re.I)
_SCRIPT_RE = re.compile(r"<script[^>]*>.*?</script>", re.I | re.S)
_TAG_RE = re.compile(r"<[^>]+>")


def _hex_to_rgb(h: str) -> Tuple[int, int, int]:
    h = h.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _luminance(rgb: Tuple[int, int, int]) -> float:
    chan = []
    for c in rgb:
        c = c / 255.0
        chan.append(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4)
    return 0.2126 * chan[0] + 0.7152 * chan[1] + 0.0722 * chan[2]


def _hsv(rgb: Tuple[int, int, int]) -> Tuple[float, float, float]:
    """HSV, hue in degrees. HSV saturation (not HLS) — HLS saturation
    explodes toward 1.0 for near-white/near-black shades, which would
    misclassify a cream page ground as 'high saturation'."""
    import colorsys
    r, g, b = (c / 255.0 for c in rgb)
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    return h * 360.0, s, v


def _classify_hex(hexv: str) -> Dict[str, str]:
    rgb = _hex_to_rgb(hexv)
    lum = _luminance(rgb)
    hue, sat, _v = _hsv(rgb)
    ground = "dark" if lum < 0.35 else "light"
    saturation = "low" if sat < 0.18 else ("medium" if sat < 0.55 else "high")
    if sat < 0.12:
        warmth = "neutral"
    elif hue < 80 or hue >= 320:
        warmth = "warm"
    else:
        warmth = "cool"
    return {"ground": ground, "saturation": saturation, "warmth": warmth}


def _collect_css_text(html: str, base_url: str,
                      client: Optional[httpx.Client]) -> str:
    """Inline <style> blocks + style= attributes + (at most 2) linked
    stylesheets, each fetched under the same SSRF guards. Fail-soft."""
    parts: List[str] = [m.group(1) for m in _STYLE_BLOCK_RE.finditer(html)]
    parts += [m.group(1)[1:-1] for m in _STYLE_ATTR_RE.finditer(html)]
    if client is not None:
        fetched = 0
        for tag in _LINK_TAG_RE.finditer(html):
            t = tag.group(0)
            if "stylesheet" not in t.lower():
                continue
            m = _HREF_RE.search(t)
            if not m:
                continue
            href = urljoin(base_url, m.group(1))
            if "fonts.googleapis.com" in href:
                continue                    # font CSS handled by name, below
            try:
                _fu, css = _fetch_capped(client, href, want="css")
                parts.append(css)
                fetched += 1
            except Exception as e:
                logger.info(f"[refstudy] stylesheet skipped ({href[:80]}): {e}")
            if fetched >= MAX_STYLESHEETS:
                break
    return "\n".join(parts)


def _bucket(rgb: Tuple[int, int, int]) -> Tuple[int, int, int]:
    """Quantize to merge near-identical shades (32-step per channel)."""
    return tuple(c // 32 for c in rgb)  # type: ignore[return-value]


def extract_palette(css_text: str) -> Dict[str, Any]:
    """Frequency-counted, near-identical-deduped hex palette + an overall
    read of what the color world is doing."""
    counts: Counter = Counter()
    for m in _HEX_RE.finditer(css_text):
        h = m.group(1).lower()
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        counts["#" + h] += 1
    if not counts:
        return {"hexes": [], "read": "unknown"}

    buckets: Dict[Tuple[int, int, int], List[Tuple[str, int]]] = {}
    for hexv, n in counts.items():
        buckets.setdefault(_bucket(_hex_to_rgb(hexv)), []).append((hexv, n))
    merged: List[Tuple[str, int]] = []
    for members in buckets.values():
        members.sort(key=lambda t: -t[1])
        rep = members[0][0]                       # most frequent shade wins
        merged.append((rep, sum(n for _h, n in members)))
    merged.sort(key=lambda t: -t[1])

    hexes = [{"hex": h, "count": n, **_classify_hex(h)} for h, n in merged[:6]]

    total = sum(n for _h, n in merged) or 1
    dark_share = sum(h["count"] for h in hexes if h["ground"] == "dark") / total
    vivid = [h for h in hexes if h["saturation"] == "high"]
    vivid_share = sum(h["count"] for h in vivid) / total
    warm_n = sum(h["count"] for h in hexes if h["warmth"] == "warm")
    cool_n = sum(h["count"] for h in hexes if h["warmth"] == "cool")
    if dark_share > 0.45:
        read = "dark moody" + (" with vivid accents" if vivid else ", low-key")
    elif vivid_share >= 0.5 and len(vivid) >= 2:
        read = "high-saturation playful"
    elif warm_n >= cool_n:
        read = "warm paper" if not vivid else "warm light with a vivid accent"
    else:
        read = "cool light" if not vivid else "cool light with a vivid accent"
    return {"hexes": hexes, "read": read}


# ─── Typography extraction ────────────────────────────────────────────

_FONT_FAMILY_RE = re.compile(r"font-family\s*:\s*([^;}{!]+)", re.I)
_GFONTS_RE = re.compile(r"fonts\.googleapis\.com/css2?\?([^\"'\s>]+)", re.I)
_GENERIC_FAMILIES = {"serif", "sans-serif", "monospace", "cursive", "fantasy",
                     "system-ui", "ui-serif", "ui-sans-serif", "ui-monospace",
                     "inherit", "initial", "unset", "var"}
_SERIF_NAMES = ("georgia", "times", "garamond", "playfair", "merriweather",
                "lora", "caslon", "baskerville", "cormorant", "crimson",
                "spectral", "freight", "tiempos", "canela", "didot", "bodoni",
                "newsreader", "fraunces", "source serif", "pt serif",
                "noto serif", "roboto slab", "domine", "bitter", "cardo",
                "vollkorn", "prata", "eb garamond", "dm serif", "charter",
                "book antiqua", "palatino")
_MONO_NAMES = ("mono", "courier", "consolas", "menlo", "code", "monaco")
_DISPLAY_NAMES = ("anton", "bebas", "abril", "righteous", "lobster",
                  "pacifico", "monoton", "bungee", "archivo black", "syne",
                  "clash", "chillax", "unbounded", "bricolage", "display")


def classify_font(family: str) -> str:
    f = family.strip().strip("'\"").lower()
    if any(w in f for w in _MONO_NAMES):
        return "mono"
    # Serif before display: "Playfair Display" / "DM Serif Display" are
    # serifs whose NAME contains the word display.
    if any(w in f for w in _SERIF_NAMES) or ("serif" in f and "sans" not in f):
        return "serif"
    if any(w in f for w in _DISPLAY_NAMES):
        return "display"
    return "sans"


def extract_fonts(html: str, css_text: str) -> List[Dict[str, str]]:
    families: List[str] = []

    def _add(name: str) -> None:
        n = name.strip().strip("'\"").strip()
        if not n or n.lower() in _GENERIC_FAMILIES or n.lower().startswith("var("):
            return
        low = n.lower()
        if "icon" in low or "awesome" in low or "emoji" in low:
            return
        if all(n.lower() != f.lower() for f in families):
            families.append(n)

    # Google Fonts <link> families — the strongest signal of intent.
    for m in _GFONTS_RE.finditer(html):
        for param in m.group(1).replace("&amp;", "&").split("&"):
            if param.lower().startswith("family="):
                fam = param.split("=", 1)[1].split(":")[0].replace("+", " ")
                _add(fam)
    # font-family stacks (first non-generic family per declaration).
    for m in _FONT_FAMILY_RE.finditer(css_text):
        for token in m.group(1).split(","):
            t = token.strip().strip("'\"").strip()
            if t and t.lower() not in _GENERIC_FAMILIES and not t.lower().startswith("var("):
                _add(t)
                break
    return [{"family": f[:60], "class": classify_font(f)} for f in families[:8]]


# ─── Density signals ──────────────────────────────────────────────────

_IMG_RE = re.compile(r"<img\b", re.I)
_MAXW_RE = re.compile(r"max-width\s*:\s*(\d+(?:\.\d+)?)\s*(px|rem|em)", re.I)


def extract_density(html: str, css_text: str) -> Dict[str, Any]:
    body = _SCRIPT_RE.sub(" ", html)
    body = _STYLE_BLOCK_RE.sub(" ", body)
    text = " ".join(_TAG_RE.sub(" ", body).split())
    images = len(_IMG_RE.findall(html))
    widths = []
    for m in _MAXW_RE.finditer(css_text):
        v = float(m.group(1))
        widths.append(v if m.group(2).lower() == "px" else v * 16)
    content_widths = sorted(w for w in widths if 320 <= w <= 2200)
    max_width_px = int(content_widths[len(content_widths) // 2]) if content_widths else None

    text_len = len(text)
    if text_len > 12000 or images > 25:
        label = "dense"
    elif text_len < 3000 and images < 8:
        label = "spare"
    else:
        label = "balanced"
    if label == "balanced" and max_width_px and max_width_px <= 760 and text_len < 6000:
        label = "spare"                        # narrow measure + modest copy
    return {"label": label, "images": images, "text_chars": text_len,
            "max_width_px": max_width_px}


# ─── Title / meta description ─────────────────────────────────────────

_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
_META_DESC_RE = re.compile(
    r"""<meta\b[^>]*name\s*=\s*["']description["'][^>]*>""", re.I)
_CONTENT_RE = re.compile(r"""content\s*=\s*["']([^"']*)["']""", re.I)


def _unescape(s: str) -> str:
    import html as _h
    return _h.unescape(s)


def extract_identity(html: str) -> Tuple[str, str]:
    title = ""
    m = _TITLE_RE.search(html)
    if m:
        title = _unescape(" ".join(m.group(1).split()))[:160]
    description = ""
    m = _META_DESC_RE.search(html)
    if m:
        c = _CONTENT_RE.search(m.group(0))
        if c:
            description = _unescape(" ".join(c.group(1).split()))[:300]
    return title, description


# ─── Per-URL analysis + public entry point ────────────────────────────

def analyze_html(url: str, html: str,
                 client: Optional[httpx.Client] = None,
                 base_url: Optional[str] = None) -> Dict[str, Any]:
    """Deterministic extraction over an already-fetched document.
    Split out so smoke tests can run on local fixtures with no network."""
    css_text = _collect_css_text(html, base_url or url, client)
    title, description = extract_identity(html)
    return {
        "url": url,
        "ok": True,
        "palette": extract_palette(css_text),
        "fonts": extract_fonts(html, css_text),
        "density": extract_density(html, css_text),
        "title": title,
        "description": description,
    }


def analyze_references(urls: List[str]) -> List[Dict[str, Any]]:
    """Study up to MAX_URLS owner-named reference sites. Every failure is
    contained to its own {url, ok: False, error} entry."""
    results: List[Dict[str, Any]] = []
    todo = [str(u).strip() for u in (urls or []) if str(u or "").strip()][:MAX_URLS]
    if not todo:
        return results
    try:
        client = httpx.Client(timeout=FETCH_TIMEOUT_S, follow_redirects=False)
    except Exception as e:                      # pragma: no cover
        return [{"url": u, "ok": False, "error": f"http client unavailable: {e}"}
                for u in todo]
    with client:
        for url in todo:
            try:
                final_url, html = _fetch_capped(client, url, want="html")
                results.append(analyze_html(url, html, client=client,
                                            base_url=final_url))
            except Exception as e:
                logger.info(f"[refstudy] {url[:100]} skipped: {e}")
                results.append({"url": url, "ok": False, "error": str(e)[:200]})
    return results


def compact_summary(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The trimmed shape prompts consume — direction evidence only."""
    out: List[Dict[str, Any]] = []
    for r in results or []:
        if not (isinstance(r, dict) and r.get("ok")):
            continue
        pal = r.get("palette") or {}
        fonts = r.get("fonts") or []
        out.append({
            "url": str(r.get("url") or "")[:120],
            "palette_read": pal.get("read") or "unknown",
            "top_colors": [h.get("hex") for h in (pal.get("hexes") or [])[:4]],
            "font_classes": sorted({f.get("class") for f in fonts if f.get("class")}),
            "font_families": [f.get("family") for f in fonts[:4]],
            "density": (r.get("density") or {}).get("label") or "unknown",
            "describes_itself_as": (r.get("description") or r.get("title") or "")[:200],
        })
        if len(out) >= MAX_URLS:
            break
    return out
