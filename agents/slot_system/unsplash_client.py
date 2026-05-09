"""Pass 4.0b.5 PART 2 — Unsplash retrieval for atmosphere slots.

Two surfaces:

  query_unsplash(query, orientation, min_width, min_relevance_score)
    Hits GET /search/photos and returns the most relevant result that
    clears the dimension threshold, plus an attribution payload. Soft-
    fails on missing API key, HTTP error, 429 rate limit, or no
    qualifying results — returns None rather than raising. Caller
    interprets None as 'fall back to DALL-E or placeholder'.

  build_unsplash_query(slot_name, enriched_brief, designer_pick, business)
    Composes a focused 3–6 word query from slot intent + business
    subject (extracted from name + description + content_archetype) +
    mood modifier (extracted from inferred_vibe + brand_metaphor +
    sub_strand_id). Pure string composition — no IO.

Attribution: the credit URL carries Unsplash UTM parameters per their
attribution requirements
(https://help.unsplash.com/en/articles/2511315-guideline-attribution).
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger(__name__)

UNSPLASH_API_BASE = "https://api.unsplash.com"
UNSPLASH_UTM = "utm_source=solutionist_studio&utm_medium=referral"
HTTP_TIMEOUT = 15.0


# ─── Live retrieval ──────────────────────────────────────────────────

def query_unsplash(
    query: str,
    orientation: str = "landscape",
    min_width: int = 1200,
    min_relevance_score: float = 0.5,
    result_index: int = 0,
) -> Optional[Dict[str, Any]]:
    """Query Unsplash for the most relevant photo matching the query.

    `orientation` is one of {"landscape", "portrait", "squarish"}.
    Unsplash's search API returns results ordered by relevance and
    does NOT expose a per-result relevance score, so we rely on the
    ordering and filter only on the dimension threshold. The
    `min_relevance_score` parameter is kept for forward-compat — it's
    surfaced in the returned payload (as a synthetic rank-derived
    value) but never used to drop a result today.

    `result_index` (Pass 4.0b.5 PART 5) selects which qualifying result
    to return — 0 returns the most relevant (default), 1 the second,
    etc. Used by the /reroll endpoint to walk the qualifying results
    list across rerolls (per_page=10 lets us reroll up to 9 times on
    the same query before paginating). When result_index exceeds the
    qualifying-results length, the function returns None.

    Returns None when:
      - UNSPLASH_ACCESS_KEY is not set
      - query is empty
      - the HTTP call fails (any exception)
      - Unsplash returns 429 rate-limit
      - no results clear the min_width filter
      - result_index >= number of qualifying results
    """
    api_key = os.environ.get("UNSPLASH_ACCESS_KEY")
    if not api_key:
        logger.warning("[unsplash] UNSPLASH_ACCESS_KEY not set; skipping query")
        return None
    q = (query or "").strip()
    if not q:
        return None

    if orientation not in ("landscape", "portrait", "squarish"):
        orientation = "landscape"

    try:
        with httpx.Client(timeout=HTTP_TIMEOUT) as client:
            resp = client.get(
                f"{UNSPLASH_API_BASE}/search/photos",
                params={
                    "query": q,
                    "orientation": orientation,
                    "per_page": 10,
                    "order_by": "relevant",
                },
                headers={"Authorization": f"Client-ID {api_key}"},
            )
        if resp.status_code == 429:
            logger.warning(
                f"[unsplash] rate-limited (429) on query={q!r}; returning None"
            )
            return None
        resp.raise_for_status()
    except Exception as e:
        logger.warning(
            f"[unsplash] query failed ({type(e).__name__}: {e}); query={q!r}"
        )
        return None

    try:
        data = resp.json()
    except Exception as e:
        logger.warning(f"[unsplash] JSON parse failed: {e}")
        return None

    results = data.get("results") or []
    qualified = [
        r for r in results
        if isinstance(r, dict) and (r.get("width") or 0) >= min_width
    ]
    if not qualified:
        logger.info(
            f"[unsplash] no result cleared min_width={min_width} for query={q!r} "
            f"(total returned={len(results)})"
        )
        return None

    # Honor result_index for reroll variety. Clamp to non-negative;
    # return None when the index runs past the qualifying list (caller
    # interprets as 'no more variety on this query').
    idx = max(0, int(result_index or 0))
    if idx >= len(qualified):
        logger.info(
            f"[unsplash] result_index={idx} exceeds qualifying count "
            f"{len(qualified)} for query={q!r}"
        )
        return None
    top = qualified[idx]
    rank = results.index(top) if top in results else idx
    # Synthetic relevance score: rank-derived, in [0, 1]. 1.0 means top
    # of the unfiltered list. Lets future code threshold on it without
    # relying on Unsplash exposing a real score.
    synthetic_relevance = max(0.0, 1.0 - (rank / 10.0))

    user = top.get("user") or {}
    profile_html = ((user.get("links") or {}).get("html") or "").strip()
    profile_with_utm = (
        f"{profile_html}{'&' if '?' in profile_html else '?'}{UNSPLASH_UTM}"
        if profile_html else ""
    )

    urls = top.get("urls") or {}
    return {
        "url": urls.get("regular"),
        "url_full": urls.get("full"),
        "credit": {
            "name": user.get("name") or user.get("username") or "Unsplash photographer",
            "url": profile_with_utm,
            "username": user.get("username") or "",
        },
        "width": top.get("width"),
        "height": top.get("height"),
        "relevance_score": synthetic_relevance,
        "unsplash_id": top.get("id"),
    }


# ─── Query composition ───────────────────────────────────────────────

# Per-slot search patterns. Subject + mood get formatted in. Each
# pattern stays at 3–6 words after substitution to maximize Unsplash
# relevance (their docs note 1–4 word queries beat long ones).
_SLOT_QUERY_PATTERNS = {
    "hero_main": "{subject} interior {mood}",
    "chamber_main": "{subject} detail {mood}",
    "gallery_1": "{subject} workspace {mood}",
    "gallery_2": "{subject} tools detail {mood}",
    "gallery_3": "{subject} environment {mood}",
    "gallery_4": "{subject} portrait {mood}",
}

# Business-type extraction. First match wins. Keys are checked as
# substrings in business_name + description (lowercased). Values are
# the curated Unsplash-friendly search subject — sometimes a single
# word, sometimes a 2-word noun phrase that beats the bare keyword.
_BUSINESS_TYPE_KEYWORDS = (
    ("barbershop", "barbershop"),
    ("barber", "barbershop"),
    ("salon", "salon"),
    ("spa", "spa"),
    ("yoga", "yoga studio"),
    ("fitness", "fitness studio"),
    ("wellness", "wellness studio"),
    ("clinic", "clinic"),
    ("law firm", "law office"),
    ("attorney", "law office"),
    ("consulting", "consulting office"),
    ("consultancy", "consulting office"),
    ("agency", "creative agency"),
    ("design studio", "design studio"),
    ("photography", "photography studio"),
    ("gallery", "art gallery"),
    ("boutique", "boutique"),
    ("cafe", "cafe interior"),
    ("coffee", "coffee shop"),
    ("restaurant", "restaurant interior"),
    ("bakery", "bakery"),
    ("bookstore", "bookstore"),
    ("school", "school"),
    ("academy", "academy"),
    ("ministry", "sanctuary"),
    ("church", "church interior"),
)

_ARCHETYPE_DEFAULT_SUBJECT = {
    "service_business": "service workspace",
    "knowledge_brand": "library desk books",
    "ministry": "sanctuary",
    "trading_practice": "office desk",
    "creative_agency": "creative studio",
    "coaching_practice": "office space",
    "product_business": "product detail",
    "community_platform": "community gathering",
}

# Inferred-vibe word → Unsplash mood phrase. Multiple matches stack
# (joined by space, capped at 2 phrases).
_VIBE_TO_MOOD = (
    ("regal", "moody dark"),
    ("royal", "moody dark"),
    ("luxury", "moody luxury"),
    ("premium", "moody luxury"),
    ("noir", "moody dark"),
    ("masculine", "masculine"),
    ("feminine", "soft"),
    ("heritage", "vintage"),
    ("authority", "cinematic"),
    ("ceremonial", "cinematic dim"),
    ("cinematic", "cinematic"),
    ("editorial", "editorial"),
    ("minimal", "minimal"),
    ("warm", "warm sunlit"),
    ("organic", "natural"),
    ("wellness", "soft natural"),
    ("bold", "high contrast"),
    ("brutalist", "raw concrete"),
    ("retrotech", "retro tech"),
    ("playful", "bright"),
    ("vintage", "vintage"),
)


def _extract_subject(
    business_name: str,
    description: str,
    archetype: str,
) -> str:
    text = f"{business_name or ''} {description or ''}".lower()
    for kw, mapped in _BUSINESS_TYPE_KEYWORDS:
        if kw in text:
            return mapped
    return _ARCHETYPE_DEFAULT_SUBJECT.get(
        (archetype or "").strip(),
        "workspace",
    )


_MOOD_WORD_CAP = 2  # the per-slot patterns already add 1-3 words; cap mood at 2 to stay under 6 total


def _extract_mood(enriched_brief: Optional[Dict], designer_pick: Optional[Dict]) -> str:
    """Build a 1–2 word mood modifier from inferred_vibe (primary),
    brand_metaphor, and designer's accent_style / sub_strand_id
    (secondary). Word-level dedup so phrases like 'moody dark' +
    'moody luxury' don't yield 'moody dark moody luxury' — instead
    flatten to unique words and keep the first _MOOD_WORD_CAP.

    Capping at 2 words keeps total Unsplash queries to 3–6 words even
    for the longest pattern (gallery_2: '{subject} tools detail {mood}'
    = 3 fixed + 2 mood = 5 words)."""
    enriched_brief = enriched_brief or {}
    designer_pick = designer_pick or {}
    sources = " ".join([
        str(enriched_brief.get("inferred_vibe") or ""),
        str(enriched_brief.get("brand_metaphor") or ""),
        str(designer_pick.get("accent_style") or ""),
        str(designer_pick.get("sub_strand_id") or ""),
    ]).lower()

    # Walk the vocab in declared order; collect phrase matches; then
    # flatten to ordered unique words. Earlier matches win the slot
    # since the vocab is roughly priority-ordered (signature mood
    # words first).
    phrases: list = []
    for vibe_word, mood_phrase in _VIBE_TO_MOOD:
        if vibe_word in sources and mood_phrase not in phrases:
            phrases.append(mood_phrase)

    seen: set = set()
    words_ordered: list = []
    for phrase in phrases:
        for w in phrase.split():
            if w not in seen:
                seen.add(w)
                words_ordered.append(w)
            if len(words_ordered) >= _MOOD_WORD_CAP:
                break
        if len(words_ordered) >= _MOOD_WORD_CAP:
            break

    if not words_ordered:
        return "cinematic"
    return " ".join(words_ordered)


def build_unsplash_query(
    slot_name: str,
    enriched_brief: Optional[Dict[str, Any]],
    designer_pick: Optional[Dict[str, Any]],
    business: Optional[Dict[str, Any]],
) -> str:
    """Compose an Unsplash query string for a slot.

    Pattern: per-slot template with {subject} + {mood} substitution.
    Subject is the business type (extracted from name + description,
    fallback to content_archetype default). Mood is a 1–2 phrase
    distillation of inferred_vibe + brand_metaphor + designer's
    accent_style / sub_strand_id.

    Falls back to a generic 'workspace cinematic' for unknown slots
    so the caller never gets an empty query.
    """
    business = business or {}
    enriched_brief = enriched_brief or {}
    business_name = str(business.get("name") or "")
    description = str(
        business.get("elevator_pitch")
        or business.get("description")
        or business.get("tagline")
        or ""
    )
    archetype = str(enriched_brief.get("content_archetype") or "")

    subject = _extract_subject(business_name, description, archetype)
    mood = _extract_mood(enriched_brief, designer_pick)

    pattern = _SLOT_QUERY_PATTERNS.get(slot_name, "{subject} {mood}")
    return pattern.format(subject=subject, mood=mood).strip()
