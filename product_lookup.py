"""
product_lookup.py — SCAN THE SHELF: the public barcode databases
(2026-08-20).

WHAT THIS IS AND, MORE IMPORTANTLY, WHAT IT IS NOT
  A barcode is a global identifier, so somebody somewhere has already
  written down what it is. When they have, a scan can fill in the name,
  the brand, the size and even a product photo for free — no model call,
  no photograph, no typing.

  But coverage is the whole story, and the honest version is this:

    • Food and drink        — good. Open Food Facts is large and open.
    • Cosmetics / general   — thin. The sibling databases exist but are
                              mostly empty; a barbershop's pomade will
                              usually MISS.

  Measured, not assumed: of four real barcodes tried while building
  this, only the grocery item resolved. So this layer is an
  ENRICHMENT, never the path the feature stands on. When it hits, the
  practitioner gets a clean record for nothing. When it misses — which
  is often — the vision read of the actual label takes over, and that
  one works on anything, because it is looking at the thing itself.

  The UI must never let "not in the database" read as "not a product".

WHY IT IS A REGISTRY AND NOT A HARDCODED CALL
  If coverage ever needs to be better, the answer is a commercial
  barcode database, and that should be one entry in _SOURCES rather than
  a rewrite. Same reason the sources are queried CONCURRENTLY: adding a
  fifth must not add four seconds.

WHAT LEAVES THE BUILDING
  A barcode, and nothing else. No business id, no practitioner
  identity, no counts. It goes out from the server rather than the
  browser so a practitioner's own address is never exposed to a third
  party, and the source is named in the response so the app can say
  where the data came from instead of presenting it as our own.

  ODbL data (the Open*Facts family) is attributed in the UI for the
  same reason: it is somebody's work.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger("product_lookup")

# Open Food Facts asks callers to identify themselves. Doing so is both
# good manners and what keeps a shared free resource usable.
_UA = "SolutionistSystem/1.0 (inventory scanner; +https://mysolutionist.app)"

# A whole scan should not wait on somebody else's server. Past this the
# vision read is already the better answer.
_TIMEOUT = 4.0

# The registry. Add a commercial database here and everything else —
# concurrency, caching, normalization, attribution — already works.
_SOURCES: List[Dict[str, str]] = [
    {"key": "openfoodfacts", "host": "world.openfoodfacts.org",
     "label": "Open Food Facts", "covers": "food and drink"},
    {"key": "openbeautyfacts", "host": "world.openbeautyfacts.org",
     "label": "Open Beauty Facts", "covers": "cosmetics and personal care"},
    {"key": "openproductsfacts", "host": "world.openproductsfacts.org",
     "label": "Open Products Facts", "covers": "general goods"},
    {"key": "openpetfoodfacts", "host": "world.openpetfoodfacts.org",
     "label": "Open Pet Food Facts", "covers": "pet food"},
]

_FIELDS = "product_name,brands,quantity,image_front_url,categories"

# Misses are cached too, and for longer than hits. A barcode the world
# does not know today it will not know in ten minutes either, and the
# miss is the common case — caching only the hits would leave the
# expensive path uncached.
_CACHE: Dict[str, Any] = {}
_CACHE_AT: Dict[str, float] = {}
_HIT_TTL = 24 * 3600.0
_MISS_TTL = 6 * 3600.0
_CACHE_MAX = 2000


def _cache_get(code: str):
    at = _CACHE_AT.get(code)
    if at is None:
        return False, None
    hit = _CACHE.get(code)
    ttl = _HIT_TTL if hit else _MISS_TTL
    if (time.time() - at) > ttl:
        _CACHE.pop(code, None)
        _CACHE_AT.pop(code, None)
        return False, None
    return True, hit


def _cache_put(code: str, value):
    if len(_CACHE_AT) >= _CACHE_MAX:
        # Oldest first. A scan session is dozens of codes, not thousands,
        # so this only ever runs on a long-lived process.
        for old in sorted(_CACHE_AT, key=lambda k: _CACHE_AT[k])[:_CACHE_MAX // 4]:
            _CACHE.pop(old, None)
            _CACHE_AT.pop(old, None)
    _CACHE[code] = value
    _CACHE_AT[code] = time.time()


def _clean(s: Any, cap: int) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip()[:cap]


def _first_of(value: Any, cap: int) -> str:
    """The first entry of a field a third party may hand us as either a
    comma-joined string or a list.

    str() on a list yields "['Coca-Cola', 'x']", and splitting THAT on a
    comma gives "['Coca-Cola'" — a bracket and a quote written into
    somebody's catalog. Unpack the list first, then split.
    """
    if isinstance(value, (list, tuple)):
        value = value[0] if value else ""
    if isinstance(value, dict):
        return ""
    return _clean(str(value or "").split(",")[0], cap)


def _has_word(haystack: str, needle: str) -> bool:
    """Does `needle` appear in `haystack` as its own word?"""
    if not needle:
        return True
    return re.search(rf"(?<!\w){re.escape(needle.lower())}(?!\w)",
                     haystack.lower()) is not None


def normalize(raw: Dict[str, Any], source: Dict[str, str], code: str
              ) -> Optional[Dict[str, Any]]:
    """One database's answer → the shape the scan drawer already speaks.
    Pure. Returns None when the row is too empty to be worth showing —
    a record with a barcode and nothing else helps nobody and costs the
    practitioner a form they have to correct."""
    p = raw.get("product") if isinstance(raw, dict) else None
    if not isinstance(p, dict):
        return None
    name = _clean(p.get("product_name"), 200)
    brand = _first_of(p.get("brands"), 120)
    size = _clean(p.get("quantity"), 40)
    if not name:
        return None

    # Databases store "coca-cola"; a practitioner's catalog should read
    # "Coca-Cola". Title-case only when the source clearly shouted or
    # whispered — a name with existing mixed case is left alone, because
    # "iPhone" and "L'Oréal" are right and we would break them.
    if name == name.lower() or name == name.upper():
        name = name.title()

    # Word boundaries, not substrings. A plain `in` check drops the
    # brand whenever it happens to sit inside the name — brand "A" is
    # "in" the word "Cola" — so a real brand quietly disappears from
    # the product a practitioner ends up saving.
    full = name
    if brand and not _has_word(name, brand):
        full = f"{brand} {name}"
    if size and not _has_word(full, size):
        full = f"{full} {size}"

    image = str(p.get("image_front_url") or "").strip()
    if not image.startswith("https://"):
        image = ""

    return {
        "name": _clean(full, 200),
        "brand": brand or None,
        "size": size or None,
        "image_url": image or None,
        "description": _first_of(p.get("categories"), 200),
        "barcode": code,
        "source": source["label"],
        "source_key": source["key"],
    }


async def _ask(client: httpx.AsyncClient, source: Dict[str, str], code: str
               ) -> Optional[Dict[str, Any]]:
    url = f"https://{source['host']}/api/v2/product/{code}.json?fields={_FIELDS}"
    try:
        r = await client.get(url, headers={"User-Agent": _UA})
        if r.status_code != 200:
            return None
        body = r.json()
        if str(body.get("status")) != "1":
            return None
        return normalize(body, source, code)
    except Exception:
        # A database being slow, down, or rude is not an error worth
        # surfacing — it just means we read the label instead.
        return None


async def lookup(code: str) -> Optional[Dict[str, Any]]:
    """Everything the open databases know about this barcode, or None.

    Never raises and never takes longer than the budget: the whole point
    is that a miss costs the practitioner nothing but a fraction of a
    second before the camera's own read takes over.
    """
    if not code:
        return None
    cached, value = _cache_get(code)
    if cached:
        return value

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(_TIMEOUT)) as client:
            # Concurrent, not sequential: four databases must cost one
            # database's worth of waiting, or nobody will keep the
            # feature switched on.
            results = await asyncio.gather(
                *[_ask(client, s, code) for s in _SOURCES],
                return_exceptions=True)
    except Exception as e:
        logger.warning(f"[lookup] {code} failed: {e}")
        return None

    for res in results:
        if isinstance(res, dict) and res:
            _cache_put(code, res)
            logger.info(f"[lookup] {code} found in {res.get('source')}")
            return res
    _cache_put(code, None)
    return None


def sources_note() -> str:
    """What the app tells a practitioner about where a prefill came
    from. Named rather than laundered — the data is somebody's work, and
    a name is also how they judge whether to trust it."""
    return ", ".join(s["label"] for s in _SOURCES)
