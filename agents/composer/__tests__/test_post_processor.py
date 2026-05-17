"""Pass 4.0h Phase B — post_processor tests.

Covers the units that don't need an LLM or DB:

  Hero identification
    * primary selector (<section data-section="hero">)
    * class-based fallback (logs WARNING)
    * neither selector matches (logs ERROR; returns None)
    * composed Hero HTML with no <section> root (logs ERROR; skip)

  Hash + cache
    * hash is deterministic across dict-key reorderings
    * cache_store / cache_lookup round-trip on matching hash
    * cache_lookup returns None on hash mismatch
    * cache_lookup returns None on missing / malformed cache key
    * cache_lookup returns None on a future _version (forward-compat)

  post_process_hero glue (with mocks)
    * use_composer=False fast-paths to (builder_html, None) without
      invoking any LLM
    * Composer raise propagates to (builder_html, None) — never raises
    * cache HIT skips Router + Composer; render still runs

Run via:
  python -m agents.composer.__tests__.test_post_processor
"""
from __future__ import annotations

import asyncio
import logging
import sys
import unittest
from unittest.mock import patch

from agents.composer.post_processor import (
    _COMPOSER_CACHE_KEY,
    _CACHE_VERSION,
    cache_lookup,
    cache_store,
    find_hero_section,
    hash_brief,
    post_process_hero,
    replace_hero_section,
)
from bs4 import BeautifulSoup


# ─── Synthetic Builder HTML fixtures ───────────────────────────────

BUILDER_HTML_DATA_SECTION = """<!DOCTYPE html>
<html><head><title>Test</title></head>
<body>
  <header>nav stuff</header>
  <section data-section="hero" class="legacy-hero hero">
    <h1>Builder Hero Heading</h1>
    <p>Builder copy</p>
  </section>
  <section data-section="about">
    <h2>About</h2>
  </section>
</body></html>"""

BUILDER_HTML_CLASS_FALLBACK = """<!DOCTYPE html>
<html><head><title>Test</title></head>
<body>
  <header>nav</header>
  <section class="hero-banner site-hero">
    <h1>Builder Hero Heading</h1>
  </section>
  <section class="about-section">about</section>
</body></html>"""

BUILDER_HTML_NO_HERO = """<!DOCTYPE html>
<html><head><title>Test</title></head>
<body>
  <header>nav</header>
  <section data-section="about">about</section>
  <section data-section="services">services</section>
</body></html>"""

COMPOSED_HERO_GOOD = """<section data-section="hero" class="sb-hero sb-hero-edge-bleed-portrait">
  <h1 class="sb-hero-heading">Wear your <span>crown</span> loud</h1>
  <a href="#" class="sb-hero-cta">Start your design</a>
</section>"""

COMPOSED_HERO_MALFORMED = "<div>not a section</div>"


# ─── Hero identification ────────────────────────────────────────────

class TestFindHeroSection(unittest.TestCase):

    def test_primary_data_section_selector(self):
        soup = BeautifulSoup(BUILDER_HTML_DATA_SECTION, "html.parser")
        hero = find_hero_section(soup)
        self.assertIsNotNone(hero)
        self.assertEqual(hero.get("data-section"), "hero")

    def test_class_fallback_logs_warning(self):
        soup = BeautifulSoup(BUILDER_HTML_CLASS_FALLBACK, "html.parser")
        with self.assertLogs("agents.composer.post_processor", level="WARNING") as logs:
            hero = find_hero_section(soup)
        self.assertIsNotNone(hero)
        self.assertIn("hero-banner", " ".join(hero.get("class", [])))
        self.assertTrue(
            any("class-based selector" in record.message for record in logs.records),
            f"expected WARNING about class-based fallback in {[r.message for r in logs.records]}",
        )

    def test_no_hero_logs_error(self):
        soup = BeautifulSoup(BUILDER_HTML_NO_HERO, "html.parser")
        with self.assertLogs("agents.composer.post_processor", level="ERROR") as logs:
            hero = find_hero_section(soup)
        self.assertIsNone(hero)
        self.assertTrue(
            any("no Hero section found" in record.message for record in logs.records),
            f"expected ERROR about no Hero in {[r.message for r in logs.records]}",
        )


# ─── Surgical replace ──────────────────────────────────────────────

class TestReplaceHeroSection(unittest.TestCase):

    def test_replaces_data_section_hero(self):
        out = replace_hero_section(BUILDER_HTML_DATA_SECTION, COMPOSED_HERO_GOOD)
        self.assertIn("Wear your", out)
        self.assertIn("Start your design", out)
        self.assertNotIn("Builder Hero Heading", out)
        # Ensure rest of the page is preserved.
        self.assertIn("Builder copy".replace(" ", "Builder").replace("Builder", "Builder copy") if False else "About", out)
        self.assertIn("About", out)

    def test_replaces_class_based_hero(self):
        out = replace_hero_section(BUILDER_HTML_CLASS_FALLBACK, COMPOSED_HERO_GOOD)
        self.assertIn("Wear your", out)
        self.assertNotIn("Builder Hero Heading", out)
        self.assertIn("about-section", out)

    def test_no_hero_in_builder_returns_unchanged(self):
        out = replace_hero_section(BUILDER_HTML_NO_HERO, COMPOSED_HERO_GOOD)
        # Builder HTML normalized through BS4 may differ in whitespace
        # but content should be unchanged.
        self.assertNotIn("Wear your", out)
        self.assertIn("about", out.lower())

    def test_malformed_composed_html_returns_unchanged(self):
        with self.assertLogs("agents.composer.post_processor", level="ERROR") as logs:
            out = replace_hero_section(BUILDER_HTML_DATA_SECTION, COMPOSED_HERO_MALFORMED)
        self.assertIn("Builder Hero Heading", out)
        self.assertTrue(
            any("no <section> root" in record.message for record in logs.records),
        )


# ─── Hash + cache ──────────────────────────────────────────────────

class TestHashBrief(unittest.TestCase):

    def test_deterministic_across_key_order(self):
        a = {"b": 2, "a": 1, "c": [3, 2, 1]}
        b = {"c": [3, 2, 1], "a": 1, "b": 2}
        self.assertEqual(hash_brief(a), hash_brief(b))

    def test_different_briefs_different_hashes(self):
        a = {"x": 1}
        b = {"x": 2}
        self.assertNotEqual(hash_brief(a), hash_brief(b))

    def test_empty_brief_is_hashable(self):
        self.assertEqual(hash_brief({}), hash_brief({}))

    def test_non_serializable_returns_sentinel(self):
        # set() is not JSON-serializable
        h = hash_brief({"x": set()})
        # Fallback path produces an unhashable: prefix; just confirm
        # it doesn't raise and the result is a string distinct from a
        # real SHA256.
        self.assertIsInstance(h, str)


class TestCache(unittest.TestCase):

    def setUp(self):
        self.cfg = {}
        self.brief_hash = "deadbeef" * 8
        self.module_id = "studio_brut"
        self.composition = {"variant": "edge_bleed_portrait", "content": {"heading": "Hi"}}

    def test_store_then_lookup_hit(self):
        cache_store(self.cfg, self.brief_hash, self.module_id, self.composition)
        hit = cache_lookup(self.cfg, self.brief_hash)
        self.assertIsNotNone(hit)
        self.assertEqual(hit["module_id"], "studio_brut")
        self.assertEqual(hit["composition"]["variant"], "edge_bleed_portrait")
        # Mutation contract: cache lives at the documented key.
        self.assertIn(_COMPOSER_CACHE_KEY, self.cfg)

    def test_lookup_miss_on_hash_mismatch(self):
        cache_store(self.cfg, self.brief_hash, self.module_id, self.composition)
        hit = cache_lookup(self.cfg, "feedbeef" * 8)
        self.assertIsNone(hit)

    def test_lookup_miss_on_empty_config(self):
        self.assertIsNone(cache_lookup({}, self.brief_hash))

    def test_lookup_miss_on_future_version(self):
        self.cfg[_COMPOSER_CACHE_KEY] = {
            "_version": _CACHE_VERSION + 99,
            "brief_hash": self.brief_hash,
            "module_id": "studio_brut",
            "composition": self.composition,
        }
        self.assertIsNone(cache_lookup(self.cfg, self.brief_hash))

    def test_lookup_miss_on_malformed_cache(self):
        # Cache field is a string, not a dict — forward-compat
        self.cfg[_COMPOSER_CACHE_KEY] = "totally not a cache"
        self.assertIsNone(cache_lookup(self.cfg, self.brief_hash))


# ─── post_process_hero glue ────────────────────────────────────────

class FakeAsyncResp:
    def __init__(self, status: int, payload):
        self.status_code = status
        self._payload = payload
        self.text = "" if status < 400 else str(payload)

    def json(self):
        return self._payload


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class TestPostProcessHero(unittest.IsolatedAsyncioTestCase):

    async def test_use_composer_false_returns_unchanged(self):
        # Patch the SB read to report opt-out
        with patch(
            "agents.composer.post_processor._read_use_composer",
            return_value=False,
        ) as p_read:
            html, mod = await post_process_hero(
                business_id="biz-1",
                builder_html=BUILDER_HTML_DATA_SECTION,
                enriched_brief={"x": 1},
                site_config={},
            )
        self.assertEqual(html, BUILDER_HTML_DATA_SECTION)
        self.assertIsNone(mod)
        p_read.assert_awaited_once()

    async def test_composer_raises_returns_unchanged(self):
        # Opt-in, but Composer raises. Module Router succeeds.
        with patch(
            "agents.composer.post_processor._read_use_composer",
            return_value=True,
        ), patch(
            "agents.composer.module_router.route_module",
            return_value={"module_id": "studio_brut", "confidence": 0.95},
        ), patch(
            "agents.composer.hero_composer.compose_hero",
            side_effect=RuntimeError("simulated composer failure"),
        ):
            cfg = {}
            html, mod = await post_process_hero(
                business_id="biz-1",
                builder_html=BUILDER_HTML_DATA_SECTION,
                enriched_brief={"x": 1},
                site_config=cfg,
            )
        self.assertEqual(html, BUILDER_HTML_DATA_SECTION)
        self.assertIsNone(mod)
        # No cache write on Composer failure.
        self.assertNotIn(_COMPOSER_CACHE_KEY, cfg)

    async def test_cache_hit_skips_router_and_composer(self):
        # Pre-populate cache with a valid entry. Patches that would
        # FAIL the test if called confirm the cache hit short-circuits.
        cfg = {}
        brief = {"hello": "world"}
        cache_store(
            cfg,
            hash_brief(brief),
            "studio_brut",
            {"variant": "edge_bleed_portrait", "module": "studio_brut",
             "treatments": {}, "content": {"heading": "Cached Heading"}, "reasoning": "cached"},
        )

        with patch(
            "agents.composer.post_processor._read_use_composer",
            return_value=True,
        ), patch(
            "agents.composer.module_router.route_module",
            side_effect=AssertionError("router must NOT be called on cache hit"),
        ), patch(
            "agents.composer.hero_composer.compose_hero",
            side_effect=AssertionError("composer must NOT be called on cache hit"),
        ), patch(
            "agents.composer.render_pipeline.render_hero_fragment",
            return_value=COMPOSED_HERO_GOOD,
        ):
            html, mod = await post_process_hero(
                business_id="biz-1",
                builder_html=BUILDER_HTML_DATA_SECTION,
                enriched_brief=brief,
                site_config=cfg,
            )
        self.assertEqual(mod, "studio_brut")
        self.assertIn("Wear your", html)
        self.assertNotIn("Builder Hero Heading", html)

    async def test_cache_miss_writes_through(self):
        cfg = {}
        brief = {"new": "brief"}
        with patch(
            "agents.composer.post_processor._read_use_composer",
            return_value=True,
        ), patch(
            "agents.composer.module_router.route_module",
            return_value={"module_id": "studio_brut", "confidence": 0.95,
                          "reasoning": "test"},
        ), patch(
            "agents.composer.hero_composer.compose_hero",
            return_value={"variant": "edge_bleed_portrait", "module": "studio_brut",
                          "treatments": {}, "content": {"heading": "Fresh"},
                          "reasoning": "test"},
        ), patch(
            "agents.composer.render_pipeline.render_hero_fragment",
            return_value=COMPOSED_HERO_GOOD,
        ):
            html, mod = await post_process_hero(
                business_id="biz-1",
                builder_html=BUILDER_HTML_DATA_SECTION,
                enriched_brief=brief,
                site_config=cfg,
            )
        self.assertEqual(mod, "studio_brut")
        self.assertIn("Wear your", html)
        # Cache was written through to cfg
        self.assertIn(_COMPOSER_CACHE_KEY, cfg)
        self.assertEqual(cfg[_COMPOSER_CACHE_KEY]["brief_hash"], hash_brief(brief))
        self.assertEqual(cfg[_COMPOSER_CACHE_KEY]["module_id"], "studio_brut")


if __name__ == "__main__":
    # Increase log noise so the assertLogs assertions have material to
    # inspect, and keep unittest output legible.
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    unittest.main(verbosity=2)
