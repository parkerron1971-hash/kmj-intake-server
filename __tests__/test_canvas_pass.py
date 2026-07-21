"""Canvas Pass (Phase 1) tests — docs/CANVAS_PASS.md.

Covers every deterministic part of the canvas path: the brief compile,
the plan split + marquee owner-wiring, block pre-render + placement
tokens, chunking, the canvas contract validator, the JS armor, assembly
anatomy, the page-wide fact-checker, the degradation ladder, the three
substance invariants, the mono-accent guard, and the composer wiring.

ALL LLM calls are mocked (canvas._call_llm) — no live network.
"""
import itertools
import os
import re
import unittest
from types import SimpleNamespace
from unittest import mock

import brand_dna
import canvas
import canvas_brief


# ─── Shared fixtures ─────────────────────────────────────────────────

PARA_HERO = (" ".join(["The morning light crosses the bench while "
                       "joints are cut by hand and every surface is "
                       "finished until it holds a quiet sheen"] * 7))
PARA_ABOUT = (" ".join(["A two person workshop grew out of a garage "
                        "and still measures twice before any cut "
                        "because furniture should outlive its maker "
                        "by several calm generations"] * 7))
PARA_CTA = (" ".join(["Bring a room a piece that earns its place and "
                      "watch it gather the small marks of a life well "
                      "lived around it over the years"] * 7))


def _ctx(gallery=False, tone_words=None, motion="standard"):
    dna = brand_dna.build_brand_dna("biz-canvas", {})
    dna["motion"] = motion
    return {
        "dna": dna,
        "bundle": {
            "business": {"tagline": "Handmade oak furniture"},
            "voice": {"tone_words": tone_words if tone_words is not None
                      else ["warm", "honest", "crafted", "quiet", "premium"]},
            "practitioner_intelligence": {
                "about_business": "A two-person workshop making oak "
                                  "furniture by hand."},
        },
        "business": {"id": "biz-canvas", "name": "Oak & Ash",
                     "type": "furniture maker", "slug": "oakash",
                     "created_at": ""},
        "site_prefs": {"offer": "Bespoke oak tables and shelving",
                       "avoid": ["glossy stock photos", " jargon "]},
        "offerings": [{"name": "Dining table", "price": 1800,
                       "description": "Solid oak, ten-year warranty"}],
        "testimonials": [], "gallery": ([{"url": "https://img.example/1.jpg"}]
                                        if gallery else []),
        "faq": [], "booking": {"enabled": False, "url": ""},
        "store": {"enabled": False, "url": "", "items": []},
        "contact": {"email": "hi@oakash.example"},
        "footer": {}, "settings": {}, "site": {}, "connections": [],
        "cta_goal": "", "public_modules": [], "voice_profile": {},
        "business_picture": "", "motion_tokens": None, "rhythm_scale": None,
        "hero_spec": None, "motion_spec": None, "nav_spec": None,
    }


def _dro(loud_where="", signature_move=""):
    decisions = {
        "hero_concept": {"concept_statement": "Grain as landscape",
                         "direction": "artifact_showcase"},
        "tension": {"pole_a": "rustic", "pole_b": "refined"},
        "first_impression": {"feel_in_3s": "calm weight"},
        "rule_break": {"what": "", "where": ""},
        "motion": {"signature_move": signature_move},
        "palette": {"base": "dark", "temperature": "warm",
                    "accent_strategy": "balanced"},
    }
    if loud_where:
        decisions["_owner_loud_where"] = loud_where
    return {"id": "dro-1", "decisions": decisions}


def _spec():
    return [
        {"module": "hero", "variant": "cinematic",
         "content": {"headline": "Furniture that outlives trends",
                     "subheadline": "Made slowly in our workshop",
                     "cta_label": "Commission"}},
        {"module": "offerings", "variant": "featured",
         "content": {"headline": "The work"}},
        {"module": "about", "variant": "narrative",
         "content": {"headline": "The workshop"}},
        {"module": "cta", "variant": "banner",
         "content": {"headline": "Commission a piece",
                     "cta_label": "Begin"}},
        {"module": "contact", "variant": "split", "content": {}},
    ]


def _uid_cycle(*hexes):
    """Deterministic canvas.uuid4 replacement (plan uids in order)."""
    cyc = itertools.cycle(hexes)
    return lambda: SimpleNamespace(hex=next(cyc))


_UID_RE = re.compile(
    r'AUTHOR <section id="([^"]+)" class="atl-(\w{8})[^"]*"> — the (\w+) section')


def _mock_llm(paras=None, js=True, fail_chunks=(), invalid_chunks=()):
    """A canvas._call_llm replacement that authors VALID chunks from the
    prompt itself (uids, dom ids, modules, block tokens all parsed out).
    paras: {module: paragraph text}; fail_chunks: chunk indexes whose
    every call (initial AND repair) returns None; invalid_chunks: chunk
    indexes always answered with junk. A chunk is identified by the first
    uid in its prompt, so a repair retry maps to the same index."""
    paras = dict(paras or {})
    calls = {"n": 0}
    chunk_ordinals: dict = {}

    def _call(system, user, business_id):
        calls["n"] += 1
        sections = _UID_RE.findall(user)
        key = sections[0][1] if sections else f"call{calls['n']}"
        if key not in chunk_ordinals:
            chunk_ordinals[key] = len(chunk_ordinals)
        if chunk_ordinals[key] in fail_chunks:
            return None
        if chunk_ordinals[key] in invalid_chunks:
            return "no delimiters here at all"
        tokens = re.findall(r"BLOCK TOKEN (<!--SX_BLOCK:[\w:]+-->)", user)
        html_parts, css_parts = [], []
        ti = 0
        for k, (dom_id, uid, mid) in enumerate(sections):
            para = paras.get(mid, PARA_HERO if mid == "hero"
                             else PARA_ABOUT if mid == "about" else PARA_CTA)
            h = "h1" if mid == "hero" else "h2"
            bits = [f'<{h} data-override-target="{mid}/headline">'
                    f'{"Furniture that outlives trends" if mid == "hero" else "The " + mid}'
                    f'</{h}>',
                    f'<p data-override-target="{mid}/custom_1">{para}</p>']
            if mid == "hero":
                bits.append('<p data-override-target="hero/subheadline">'
                            'Made slowly in our workshop</p>')
                bits.append('<a class="sxm-cta" href="#contact" '
                            'data-override-target="hero/cta_label">Commission</a>')
            if mid == "cta":
                bits.append('<a class="sxm-cta" href="#contact" '
                            'data-override-target="cta/cta_label">Begin</a>')
            html_parts.append(
                f'<section id="{dom_id}" class="atl-{uid} sxm-{mid}">'
                + "".join(bits) + "</section>")
            # block tokens interleaved between sections, in prompt order
            while ti < len(tokens) and k < len(sections) - 1:
                html_parts.append(tokens[ti])
                ti += 1
            css_parts.append(
                f".atl-{uid} {{ padding: var(--sx-section-pad) var(--sx-gutter); overflow: hidden; }}\n"
                f".atl-{uid} {h} {{ font-family: var(--sx-font-heading); color: var(--sx-text); }}\n"
                f".atl-{uid} p {{ color: var(--sx-muted); }}")
        while ti < len(tokens):
            html_parts.append(tokens[ti])
            ti += 1
        css_parts.append("@media (max-width: 760px) { "
                         + f".atl-{sections[0][1]} " + "{ padding: 64px var(--sx-gutter); } }")
        out = ("<!--HTML-->\n" + "\n".join(html_parts)
               + "\n<!--CSS-->\n" + "\n".join(css_parts))
        if js and "<!--JS-->" in user:
            out += ("\n<!--JS-->\n(function(){var b=document.querySelector("
                    "'.sxm-cta');if(b){b.addEventListener('click',function(){"
                    "b.classList.add('clicked');});}})();")
        return out

    return _call, calls


def _run_ok(extra_spec=None, ctx=None, dro=None):
    """A full run_canvas happy path with the mock LLM. Returns
    (out, plan, blocks) with plan/blocks rebuilt under the same uid
    sequence."""
    ctx = ctx or _ctx()
    spec = extra_spec or _spec()
    with mock.patch.object(canvas, "uuid4", _uid_cycle("aaaa0001", "bbbb0002",
                                                       "cccc0003", "dddd0004",
                                                       "eeee0005", "ffff0006")):
        llm, _calls = _mock_llm()
        with mock.patch.object(canvas, "_call_llm", llm):
            out = canvas.run_canvas(spec, ctx, dro or _dro(), "biz-canvas")
    with mock.patch.object(canvas, "uuid4", _uid_cycle("aaaa0001", "bbbb0002",
                                                       "cccc0003", "dddd0004",
                                                       "eeee0005", "ffff0006")):
        plan = canvas.canvas_plan(spec, ctx, dro or _dro())
    blocks = canvas.prerender_data_sections(plan, ctx)
    return out, plan, blocks


# ─── Brief compile ───────────────────────────────────────────────────

class TestBriefCompile(unittest.TestCase):
    def test_overview_brand_plan_rules(self):
        brief = canvas_brief.compile_canvas_brief(_ctx(), _dro(), _spec())
        self.assertIn("CANVAS BRIEF — Oak & Ash", brief)
        self.assertIn("what they offer: Bespoke oak tables and shelving", brief)
        self.assertIn("the verbs", brief)                    # real tone words
        self.assertIn("--sx-accent = #", brief)              # accent hex by role
        self.assertIn("type pairing: display", brief)
        # section plan with the authored/block split + placement tokens
        self.assertIn("hero [AUTHORED]", brief)
        self.assertIn("offerings [IMMUTABLE BLOCK — token "
                      "<!--SX_BLOCK:offerings-->]", brief)
        # interactions budget + do/don't
        self.assertIn("INTERACTIONS BUDGET", brief)
        self.assertIn("ONE signature interaction maximum", brief)
        self.assertIn("DON'T (owner's avoid list): glossy stock photos", brief)
        self.assertIn("calm weight", brief)                  # first_impression
        self.assertIn("REAL OR REMOVED", brief)              # doctrine one-liner

    def test_loud_moment_from_loud_where(self):
        brief = canvas_brief.compile_canvas_brief(_ctx(), _dro(loud_where="motion"),
                                                  _spec())
        self.assertIn("loud moment at: motion", brief)

    def test_deterministic_and_failsoft(self):
        a = canvas_brief.compile_canvas_brief(_ctx(), _dro(), _spec())
        b = canvas_brief.compile_canvas_brief(_ctx(), _dro(), _spec())
        self.assertEqual(a, b)
        minimal = canvas_brief.compile_canvas_brief(None, None, None)  # type: ignore
        self.assertIn("CANVAS BRIEF", minimal)               # never raises


# ─── Plan split (§3.2) ───────────────────────────────────────────────

class TestPlanSplit(unittest.TestCase):
    def test_roles(self):
        spec = _spec() + [
            {"module": "testimonials", "variant": "marquee", "content": {}},
            {"module": "interstitial", "variant": "statement",
             "content": {"text": "A pause"}},
            {"module": "interstitial", "variant": "marquee",
             "content": {"words": "a • b • c • d"}},
        ]
        plan = canvas.canvas_plan(spec, _ctx(), _dro())
        roles = {s["module"] + ":" + s["variant"]: s["role"]
                 for s in plan["sections"]}
        self.assertEqual(roles["hero:cinematic"], "authored")
        self.assertEqual(roles["about:narrative"], "authored")
        self.assertEqual(roles["cta:banner"], "authored")
        self.assertEqual(roles["offerings:featured"], "block")
        self.assertEqual(roles["testimonials:marquee"], "block")
        self.assertEqual(roles["contact:split"], "block")
        self.assertEqual(roles["interstitial:statement"], "authored")
        self.assertEqual(roles["interstitial:marquee"], "block")
        # authored sections get uids; blocks don't
        for s in plan["sections"]:
            self.assertEqual(bool(s.get("uid")), s["role"] == "authored")

    def test_gallery_role_by_photos(self):
        spec = [{"module": "gallery", "variant": "grid", "content": {}}]
        awaiting = canvas.canvas_plan(spec, _ctx(gallery=False), None)
        self.assertEqual(awaiting["sections"][0]["role"], "authored")
        photos = canvas.canvas_plan(spec, _ctx(gallery=True), None)
        self.assertEqual(photos["sections"][0]["role"], "block")

    def test_unknown_module_is_block(self):
        spec = [{"module": "mystery", "variant": "x", "content": {}}]
        plan = canvas.canvas_plan(spec, _ctx(), None)
        self.assertEqual(plan["sections"][0]["role"], "block")


# ─── Marquee owner-wiring (§10.2) ────────────────────────────────────

class TestMarqueeWiring(unittest.TestCase):
    def test_wired_when_loud_motion(self):
        plan = canvas.canvas_plan(_spec(), _ctx(), _dro(loud_where="motion"))
        self.assertTrue(plan["marquee_wired"])
        seams = [s for s in plan["sections"] if s["module"] == "interstitial"]
        self.assertEqual(len(seams), 1)
        self.assertEqual(seams[0]["variant"], "marquee")
        self.assertEqual(seams[0]["role"], "block")
        self.assertIn("Warm", seams[0]["content"]["words"])
        # placement: not first, not directly before contact
        self.assertGreater(seams[0]["index"], 0)
        self.assertNotEqual(plan["sections"][seams[0]["index"] + 1]["module"],
                            "contact")

    def test_signature_move_calls_for_it(self):
        plan = canvas.canvas_plan(_spec(), _ctx(),
                                  _dro(signature_move="a slow marquee of values"))
        self.assertTrue(plan["marquee_wired"])

    def test_not_wired_without_call(self):
        plan = canvas.canvas_plan(_spec(), _ctx(), _dro())
        self.assertFalse(plan["marquee_wired"])

    def test_not_wired_when_stilled_or_thin(self):
        self.assertFalse(canvas.canvas_plan(
            _spec(), _ctx(motion="subtle"), _dro(loud_where="motion"))["marquee_wired"])
        self.assertFalse(canvas.canvas_plan(
            _spec(), _ctx(tone_words=["warm", "honest"]),
            _dro(loud_where="motion"))["marquee_wired"])

    def test_never_duplicated(self):
        spec = _spec()[:2] + [{"module": "interstitial", "variant": "marquee",
                               "content": {"words": "a"}}] + _spec()[2:]
        plan = canvas.canvas_plan(spec, _ctx(), _dro(loud_where="motion"))
        self.assertFalse(plan["marquee_wired"])
        self.assertEqual(sum(1 for s in plan["sections"]
                             if s["variant"] == "marquee"), 1)


# ─── Pre-rendered blocks + tokens (§3.3) ─────────────────────────────

class TestPrerenderBlocks(unittest.TestCase):
    def test_blocks_carry_real_data_and_tokens(self):
        ctx = _ctx()
        plan = canvas.canvas_plan(_spec(), ctx, _dro())
        blocks = canvas.prerender_data_sections(plan, ctx)
        mods = {b["module"]: b for b in blocks.values()}
        self.assertIn("offerings", mods)
        self.assertIn("contact", mods)
        self.assertEqual(mods["offerings"]["token"], "<!--SX_BLOCK:offerings-->")
        self.assertIn("Dining table", mods["offerings"]["html"])   # real rows
        self.assertTrue(mods["offerings"]["css"])

    def test_empty_module_drops_section(self):
        ctx = _ctx()
        ctx["offerings"] = []          # the registry's self-drop rule
        spec = [s for s in _spec() if s["module"] != "contact"]
        plan = canvas.canvas_plan(spec, ctx, None)
        canvas.prerender_data_sections(plan, ctx)
        self.assertNotIn("offerings", [s["module"] for s in plan["sections"]])


# ─── Chunking (§3.4) ─────────────────────────────────────────────────

class TestChunkSpans(unittest.TestCase):
    def test_two_chunks_for_four_authored(self):
        plan = canvas.canvas_plan(_spec(), _ctx(), _dro())
        spans = canvas.chunk_spans(plan)
        self.assertEqual(len(spans), 2)
        # chunk A: hero + the offerings token between the authored sections
        self.assertEqual([s["module"] for s in spans[0]],
                         ["hero", "offerings", "about"])
        # trailing block rides the last chunk
        self.assertEqual([s["module"] for s in spans[1]], ["cta", "contact"])

    def test_three_chunks_when_long(self):
        spec = _spec() + [
            {"module": "interstitial", "variant": "statement",
             "content": {"text": "One"}},
            {"module": "gallery", "variant": "grid", "content": {}},
        ]
        plan = canvas.canvas_plan(spec, _ctx(), _dro())   # 5 authored
        spans = canvas.chunk_spans(plan)
        self.assertEqual(len(spans), 3)
        # every section covered exactly once, in order
        flat = [s["module"] for sp in spans for s in sp]
        self.assertEqual(flat, [s["module"] for s in plan["sections"]])


# ─── The canvas contract validator (§4) ──────────────────────────────

class TestChunkValidation(unittest.TestCase):
    def _span(self):
        ctx = _ctx()
        plan = canvas.canvas_plan(_spec(), ctx, _dro())
        blocks = canvas.prerender_data_sections(plan, ctx)
        span = plan["sections"][:3]        # hero / offerings(block) / about
        return ctx, plan, blocks, span

    def _valid(self, span):
        uids = {s["module"]: s["uid"] for s in span if s["role"] == "authored"}
        html = (
            f'<section id="top" class="atl-{uids["hero"]}">'
            '<h1 data-override-target="hero/headline">Furniture that outlives trends</h1>'
            '<p data-override-target="hero/subheadline">Made slowly</p>'
            f'<p data-override-target="hero/custom_1">{PARA_HERO}</p>'
            '<a href="#contact" data-override-target="hero/cta_label">Commission</a>'
            '</section>\n<!--SX_BLOCK:offerings-->\n'
            f'<section id="about" class="atl-{uids["about"]}">'
            '<h2 data-override-target="about/headline">The workshop</h2>'
            f'<p data-override-target="about/custom_1">{PARA_ABOUT}</p>'
            '</section>')
        css = (f'.atl-{uids["hero"]} {{ padding: var(--sx-section-pad) var(--sx-gutter); }}\n'
               f'.atl-{uids["hero"]} h1 {{ font-family: var(--sx-font-heading); color: var(--sx-text); }}\n'
               f'.atl-{uids["about"]} p {{ color: var(--sx-muted); }}\n'
               '@media (max-width: 760px) { '
               f'.atl-{uids["hero"]} {{ padding: 64px var(--sx-gutter); }} }}')
        return html, css

    def test_valid_chunk_passes(self):
        ctx, plan, blocks, span = self._span()
        html, css = self._valid(span)
        ok, problems = canvas.validate_chunk(html, css, "", span, blocks, ctx)
        self.assertTrue(ok, problems)

    def _fails(self, html, css, js=""):
        ctx, plan, blocks, span = self._span()
        ok, problems = canvas.validate_chunk(html, css, js, span, blocks, ctx)
        self.assertFalse(ok)
        return " | ".join(problems)

    def test_hex_banned(self):
        html, css = self._valid(self._span()[3])
        probs = self._fails(html, css + "\n.x { color: #fff; }".replace(
            ".x", f'.atl-{self._span()[3][0]["uid"]} p'))
        self.assertIn("hex color literal", probs)

    def test_unscoped_css(self):
        html, css = self._valid(self._span()[3])
        probs = self._fails(html, css + "\nh1 { color: red; }")
        self.assertIn("unscoped selector", probs)

    def test_invented_digit(self):
        html, css = self._valid(self._span()[3])
        html = html.replace("Made slowly", "Trusted by 40 clients")
        probs = self._fails(html, css)
        self.assertIn("number '40' rendered but not present", probs)

    def test_block_token_missing(self):
        html, css = self._valid(self._span()[3])
        html = html.replace("<!--SX_BLOCK:offerings-->", "")
        probs = self._fails(html, css)
        self.assertIn("must appear exactly once", probs)

    def test_block_token_nested(self):
        html, css = self._valid(self._span()[3])
        html = html.replace("</h1>", "</h1><!--SX_BLOCK:offerings-->")
        html = html.replace("\n<!--SX_BLOCK:offerings-->\n", "\n")
        probs = self._fails(html, css)
        self.assertIn("nested inside a section", probs)

    def test_inline_handler_banned(self):
        html, css = self._valid(self._span()[3])
        html = html.replace("<h1 ", '<h1 onclick="go()" ')
        probs = self._fails(html, css)
        self.assertIn("inline event handler banned", probs)

    def test_missing_override_target(self):
        html, css = self._valid(self._span()[3])
        html = html.replace(' data-override-target="hero/subheadline"', "")
        probs = self._fails(html, css)
        self.assertIn("missing data-override-target", probs)

    def test_invented_text_needs_custom_target(self):
        html, css = self._valid(self._span()[3])
        html = html.replace("</section>\n<!--SX_BLOCK:offerings-->",
                            "<p>untargeted invented line</p></section>\n"
                            "<!--SX_BLOCK:offerings-->")
        probs = self._fails(html, css)
        self.assertIn("total editability", probs)


# ─── The JS armor (§6) ───────────────────────────────────────────────

class TestJSArmor(unittest.TestCase):
    def test_clean_iife_passes(self):
        ok, problems = canvas.scan_canvas_js(
            "(function(){document.querySelectorAll('.tab').forEach(function(t){"
            "t.addEventListener('click',function(){t.classList.toggle('on');});});})();")
        self.assertTrue(ok, problems)

    def test_empty_is_fine(self):
        self.assertEqual(canvas.scan_canvas_js(""), (True, []))

    def test_must_be_iife(self):
        ok, problems = canvas.scan_canvas_js("var x = 1;")
        self.assertFalse(ok)
        self.assertIn("IIFE", problems[0])

    def test_ban_list(self):
        for snippet in ("eval('x')", "new Function('x')", "fetch('/api')",
                        "new XMLHttpRequest()", "import('x')",
                        "new WebSocket('wss://x')", "document.write('x')",
                        "localStorage.getItem('k')", "sessionStorage.setItem('k','v')",
                        "var u='https://evil.example/x'"):
            ok, problems = canvas.scan_canvas_js(
                f"(function(){{{snippet}}})();")
            self.assertFalse(ok, snippet)
            self.assertTrue(any("banned construct" in p for p in problems),
                            snippet)

    def test_size_cap(self):
        ok, problems = canvas.scan_canvas_js(
            "(function(){/*" + "x" * (7 * 1024) + "*/})();")
        self.assertFalse(ok)
        self.assertTrue(any("exceeds" in p for p in problems))


# ─── Assembly anatomy (§3.5) ─────────────────────────────────────────

class TestAssembly(unittest.TestCase):
    def test_platform_anatomy(self):
        out, plan, blocks = _run_ok()
        self.assertIsNotNone(out["html"], out["report"]["fallbacks"])
        html = out["html"]
        self.assertTrue(html.startswith("<!DOCTYPE html>"))           # page_shell
        self.assertIn("sxm-header", html)                             # header chrome
        # one marker pair per plan section, in order
        for i, s in enumerate(plan["sections"]):
            self.assertIn(f"<!--sx:{s['module']}:{i}-->", html)
            self.assertIn(f"<!--/sx:{s['module']}:{i}-->", html)
        # stable DOM ids
        for dom in ("top", "about", "cta", "offerings", "contact"):
            self.assertIn(f'id="{dom}"', html)
        # authored sections staged; block byte-identity; tokens spliced
        self.assertIn("sxm-stage", html)
        for b in blocks.values():
            self.assertIn(b["html"], html)
        self.assertNotIn("<!--SX_BLOCK:", html)
        # authored CSS in its own style block before </head>
        self.assertIn('<style id="sx-canvas">', html)
        self.assertLess(html.index('<style id="sx-canvas">'),
                        html.index("</head>"))
        # the one page script before </body>
        self.assertIn('<script id="sx-canvas-js">', html)
        self.assertLess(html.index('<script id="sx-canvas-js">'),
                        html.index("</body>"))

    def test_module_fallback_for_missing_section(self):
        ctx = _ctx()
        spec = _spec()
        plan = canvas.canvas_plan(spec, ctx, _dro())
        blocks = canvas.prerender_data_sections(plan, ctx)
        # no chunk results at all → every authored section module-renders
        html, fallbacks = canvas.assemble_canvas(plan, [], blocks, ctx, "T")
        self.assertEqual(sorted(set(fallbacks)), ["about", "cta", "hero"])
        self.assertIn("<!--sx:hero:0-->", html)      # still assembled
        self.assertIn("Furniture that outlives trends", html)  # module copy


# ─── The fact-checker (§7) ───────────────────────────────────────────

class TestFactCheck(unittest.TestCase):
    def test_clean_page_passes(self):
        out, plan, blocks = _run_ok()
        self.assertTrue(out["report"]["fact_check"]["ok"],
                        out["report"]["fact_check"]["problems"])
        ok, problems = canvas.fact_check_canvas(out["html"], _ctx(), plan, blocks)
        self.assertTrue(ok, problems)

    def test_invented_fact_fails(self):
        out, plan, blocks = _run_ok()
        page = out["html"].replace("Made slowly in our workshop",
                                   "Trusted by 40 workshops")
        ok, problems = canvas.fact_check_canvas(page, _ctx(), plan, blocks)
        self.assertFalse(ok)
        self.assertTrue(any("number '40'" in p for p in problems), problems)

    def test_block_tamper_fails(self):
        out, plan, blocks = _run_ok()
        victim = next(b for b in blocks.values() if b["module"] == "offerings")
        page = out["html"].replace(victim["html"], "<section>rewritten</section>")
        ok, problems = canvas.fact_check_canvas(page, _ctx(), plan, blocks)
        self.assertFalse(ok)
        self.assertTrue(any("immutable block 'offerings'" in p for p in problems))

    def test_substance_floor(self):
        out, plan, blocks = _run_ok()
        with mock.patch.dict(os.environ, {"CANVAS_FLOOR_WORDS": "100000"}):
            ok, problems = canvas.fact_check_canvas(out["html"], _ctx(),
                                                    plan, blocks)
        self.assertFalse(ok)
        self.assertTrue(any("substance floor" in p for p in problems))

    def test_keyframe_cap(self):
        out, plan, blocks = _run_ok()
        junk = "<style>" + "".join(f"@keyframes pad-{i} {{ to {{ opacity: 1; }} }}"
                                   for i in range(9)) + "</style>"
        page = out["html"].replace("</head>", junk + "</head>")
        ok, problems = canvas.fact_check_canvas(page, _ctx(), plan, blocks)
        self.assertFalse(ok)
        self.assertTrue(any("motion ceiling" in p for p in problems))

    def test_imagery_floor(self):
        out, plan, blocks = _run_ok()
        # the shell ships a chamber <img data-slot>; strip all imagery so
        # the floor has something to bite on
        page = re.sub(r"<img\b[^>]*>", "", out["html"])
        ok, problems = canvas.fact_check_canvas(
            page, _ctx(gallery=True), plan, blocks)
        self.assertFalse(ok)
        self.assertTrue(any("imagery floor" in p for p in problems))
        # and the untouched page passes with the same non-empty gallery
        ok2, _ = canvas.fact_check_canvas(
            out["html"], _ctx(gallery=True), plan, blocks)
        self.assertTrue(ok2)

    def test_anatomy_census(self):
        out, plan, blocks = _run_ok()
        page = out["html"].replace("<!--sx:about:2-->", "")
        ok, problems = canvas.fact_check_canvas(page, _ctx(), plan, blocks)
        self.assertFalse(ok)
        self.assertTrue(any("section marker" in p for p in problems))
        page2 = out["html"].replace('<section id="about"', "<section")
        ok2, problems2 = canvas.fact_check_canvas(page2, _ctx(), plan, blocks)
        self.assertFalse(ok2)
        self.assertTrue(any("DOM id 'about'" in p for p in problems2))

    def test_single_script_and_handlers(self):
        out, plan, blocks = _run_ok()
        page = out["html"].replace(
            "</body>", '<script id="sx-canvas-js">(function(){})();</script></body>')
        ok, problems = canvas.fact_check_canvas(page, _ctx(), plan, blocks)
        self.assertFalse(ok)
        self.assertTrue(any("exactly one" in p for p in problems))
        page2 = out["html"].replace('data-override-target="hero/headline"',
                                    'onclick="go()" data-override-target="hero/headline"')
        ok2, problems2 = canvas.fact_check_canvas(page2, _ctx(), plan, blocks)
        self.assertFalse(ok2)
        self.assertTrue(any("inline event handler" in p for p in problems2))

    def test_block_script_exempt_from_census(self):
        # the contact form's submit handler rides inside the immutable
        # block — a byte-identical platform script must not trip the
        # single-script census (the first live build fell back on this)
        out, plan, blocks = _run_ok()
        victim = next(b for b in blocks.values() if b["module"] == "offerings")
        platform_js = ("\n(function(){var f=document.getElementById("
                       "'sxm-contact-form'); if(!f) return;})();\n")
        new_html = victim["html"] + f"<script>{platform_js}</script>"
        page = out["html"].replace(victim["html"], new_html)
        victim["html"] = new_html
        ok, problems = canvas.fact_check_canvas(page, _ctx(), plan, blocks)
        self.assertTrue(ok, problems)

    def test_unknown_script_still_fails(self):
        out, plan, blocks = _run_ok()
        page = out["html"].replace("</body>",
                                   "<script>var x = 1;</script></body>")
        ok, problems = canvas.fact_check_canvas(page, _ctx(), plan, blocks)
        self.assertFalse(ok)
        self.assertTrue(any("unidentified <script> block" in p
                            for p in problems), problems)

    def test_per_section_substance(self):
        out, plan, blocks = _run_ok()
        thin = out["html"].replace(PARA_ABOUT, "A short line.")
        ok, problems = canvas.fact_check_canvas(thin, _ctx(), plan, blocks)
        self.assertFalse(ok)
        self.assertTrue(any("about section carries" in p for p in problems))
        long_h1 = out["html"].replace(
            "Furniture that outlives trends",
            "Furniture that outlives every trend and fills your home with quiet warmth")
        ok2, problems2 = canvas.fact_check_canvas(long_h1, _ctx(), plan, blocks)
        self.assertFalse(ok2)
        self.assertTrue(any("hero headline runs" in p for p in problems2))


# ─── The degradation ladder (§9) ─────────────────────────────────────

class TestFallbacks(unittest.TestCase):
    def test_total_llm_failure_returns_no_html(self):
        with mock.patch.object(canvas, "_call_llm", lambda *a: None):
            out = canvas.run_canvas(_spec(), _ctx(), _dro(), "biz-canvas")
        self.assertIsNone(out["html"])
        stages = [f["stage"] for f in out["report"]["fallbacks"]]
        self.assertIn("author", stages)
        self.assertTrue(any(f["stage"].startswith("chunk_")
                            for f in out["report"]["fallbacks"]))

    def test_chunk_kill_degrades_to_modules(self):
        # hero + about carry enough text that the page still clears the
        # substance floor once the cta chunk is gone
        rich = {"hero": PARA_HERO + " " + PARA_HERO,
                "about": PARA_ABOUT + " " + PARA_ABOUT}
        llm, _ = _mock_llm(paras=rich, invalid_chunks={1})
        with mock.patch.object(canvas, "_call_llm", llm):
            out = canvas.run_canvas(_spec(), _ctx(), _dro(), "biz-canvas")
        self.assertIsNotNone(out["html"])            # a failed chunk is never a blank page
        crumbs = [f for f in out["report"]["fallbacks"]
                  if f["stage"] == "chunk_1"]
        self.assertTrue(crumbs)
        self.assertIn("render from modules", crumbs[0]["detail"])
        # the cta section is present via its module render
        self.assertIn("<!--sx:cta:", out["html"])

    def test_fact_check_retry_then_module_path(self):
        thin = {"hero": "Short line one.", "about": "Short line two.",
                "cta": "Short line three."}
        llm, _ = _mock_llm(paras=thin)
        with mock.patch.object(canvas, "_call_llm", llm):
            out = canvas.run_canvas(_spec(), _ctx(), _dro(), "biz-canvas")
        self.assertIsNone(out["html"])
        self.assertTrue(out["report"]["fact_check"]["retried"])
        self.assertIn("fact_check",
                      [f["stage"] for f in out["report"]["fallbacks"]])

    def test_report_shape_on_success(self):
        out, plan, blocks = _run_ok()
        report = out["report"]
        self.assertEqual(report["planned"]["authored"], ["hero", "about", "cta"])
        self.assertEqual(report["planned"]["blocks"], ["offerings", "contact"])
        self.assertTrue(all(c["ok"] for c in report["chunks"]))
        self.assertGreaterEqual(report["words"], 450)
        self.assertLessEqual(report["keyframes"], 8)
        self.assertTrue(report["script"])

    def test_gate_default_off(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SITE_CANVAS", None)
            self.assertFalse(canvas.canvas_enabled())
        with mock.patch.dict(os.environ, {"SITE_CANVAS": "on"}):
            self.assertTrue(canvas.canvas_enabled())


# ─── Substance invariants (§10.3) ────────────────────────────────────

class TestSubstanceInvariants(unittest.TestCase):
    def test_words1(self):
        import design_invariants as di
        thin = "<html><body><p>" + " ".join(["word"] * 100) + "</p></body></html>"
        f = di.check_words(thin)
        self.assertEqual(f["rule_id"], "WORDS-1")
        fat = "<html><body><p>" + " ".join(["word"] * 500) + "</p></body></html>"
        self.assertIsNone(di.check_words(fat))
        self.assertIsNone(di.check_words(
            "<html><body><script>" + " ".join(["word"] * 999) +
            "</script><p>" + " ".join(["word"] * 500) + "</p></body></html>"))
        with mock.patch.dict(os.environ, {"CANVAS_FLOOR_WORDS": "10"}):
            self.assertIsNone(di.check_words(thin))

    def test_imagery1(self):
        import design_invariants as di
        self.assertIsNone(di.check_imagery("<body></body>", False))
        populated = '<body><img data-slot="gallery_1" src="https://cdn.example/x.jpg" alt="a"></body>'
        self.assertIsNone(di.check_imagery(populated, True))
        empty = '<body><img data-slot="gallery_1" src="" alt="a"></body>'
        f = di.check_imagery(empty, True)
        self.assertEqual(f["rule_id"], "IMAGERY-1")
        none_at_all = "<body><p>no images</p></body>"
        self.assertEqual(di.check_imagery(none_at_all, True)["rule_id"],
                         "IMAGERY-1")

    def test_motion_ceiling(self):
        import design_invariants as di
        under = "".join(f"@keyframes k{i} {{ to {{ opacity: 1; }} }}"
                        for i in range(8))
        self.assertIsNone(di.check_motion_ceiling("", under))
        over = under + "@keyframes k9 { to { opacity: 1; } }"
        f = di.check_motion_ceiling("", over)
        self.assertEqual(f["rule_id"], "MOTION-CEILING-1")
        with mock.patch.dict(os.environ, {"CANVAS_KEYFRAME_CAP": "2"}):
            self.assertEqual(di.check_motion_ceiling("", under)["rule_id"],
                             "MOTION-CEILING-1")

    def test_registered_in_entry(self):
        import design_invariants as di
        thin = "<html><body><p>" + " ".join(["word"] * 50) + "</p></body></html>"
        findings = di.check_design_invariants(
            thin, "@keyframes a { to {opacity:1;} }" * 9,
            {"site_prefs": {}, "gallery": [{"url": "x"}]})
        ids = {f["rule_id"] for f in findings}
        self.assertIn("WORDS-1", ids)
        self.assertIn("IMAGERY-1", ids)
        self.assertIn("MOTION-CEILING-1", ids)
        for f in findings:
            self.assertEqual(f["severity"], "ADVISORY")


# ─── Mono-accent guard (§10.1) ───────────────────────────────────────

class TestMonoGuard(unittest.TestCase):
    def _body_class(self, dna):
        from site_modules import _base
        html = _base.page_shell(dna, "t", "x", "",
                                design={"palette": {
                                    "accent_strategy": "tonal_monochrome"}})
        return html.split('<body class="')[1].split('"')[0]

    def test_chromatic_secondary_survives(self):
        # gold accent + genuinely chromatic green secondary (sat > 0.18,
        # hue gap > 30°) → palette.secondary_active → the mono class must
        # NOT neutralize it.
        dna = brand_dna.build_brand_dna(
            "biz-mono", {"design": {"secondary_color": "#2e6b4f"}})
        self.assertTrue(dna["palette"].get("secondary_active"))
        self.assertNotIn("sx-mono-accent", self._body_class(dna))
        self.assertIn("sx-scarce-accent", self._body_class(dna))

    def test_neutral_secondary_still_collapses(self):
        dna = brand_dna.build_brand_dna("biz-mono2", {})
        self.assertFalse(dna["palette"].get("secondary_active"))
        self.assertIn("sx-mono-accent", self._body_class(dna))


# ─── Model ladder task family ────────────────────────────────────────

class TestModelLadder(unittest.TestCase):
    def test_canvas_timeouts(self):
        import model_ladder
        self.assertEqual(model_ladder.timeout_for("canvas", "claude-opus-4-8"),
                         240.0)
        self.assertEqual(model_ladder.timeout_for(
            "canvas", "claude-sonnet-4-5-20250929"), 120.0)


# ─── Composer wiring ─────────────────────────────────────────────────

_CANVAS_DOC = (
    '<!DOCTYPE html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
    '<title>Oak &amp; Ash</title>\n</head>\n<body class="">'
    '<!--sx:hero:0--><section id="top" class="atl-aaaa0001">'
    '<h1 data-override-target="hero/headline">Furniture that outlives trends</h1>'
    '</section><!--/sx:hero:0-->'
    '<!--sx:offerings:1--><section id="offerings"><h2>The work</h2>'
    '</section><!--/sx:offerings:1-->'
    '</body>\n</html>')


class TestRenderAndPersistCanvas(unittest.TestCase):
    """render_and_persist(_canvas_html=…) skips render_page/run_atelier
    and joins at slot population; the canvas document + report persist
    to site_config. All DB/LLM boundaries mocked."""

    def _call(self, canvas_html, canvas_report=None, full=True,
              stored_cfg=None):
        import site_composer
        patched = {}

        def _patch_as_service(path, payload):
            patched.update(payload.get("site_config") or {})
            patched["__html_content__"] = payload.get("html_content")
            return None

        site_row = {"id": "site-1", "site_config": dict(stored_cfg or {})}
        with mock.patch.object(site_composer, "_ensure_site_row",
                               return_value=site_row), \
                mock.patch.object(site_composer.sb_clients,
                                  "sb_get_as_service", return_value=[]), \
                mock.patch.object(site_composer.sb_clients,
                                  "sb_patch_as_service",
                                  side_effect=_patch_as_service), \
                mock.patch.object(site_composer.site_modules, "render_page",
                                  side_effect=AssertionError(
                                      "render_page must be skipped")), \
                mock.patch("vision_grader.grade", return_value=None), \
                mock.patch("design_register.get_invention_count",
                           return_value=None), \
                mock.patch.object(site_composer, "_verify_inventions",
                                  return_value={}):
            result = site_composer.render_and_persist(
                "biz-canvas", _spec(), _ctx(), dro=None, full_recompose=full,
                _canvas_html=canvas_html, _canvas_report=canvas_report)
        return result, patched

    def test_canvas_joins_and_persists(self):
        result, cfg = self._call(_CANVAS_DOC, {"fact_check": {"ok": True},
                                               "fallbacks": []})
        # the canvas document flows through (the composer mark is stamped)
        self.assertIn("x-solutionist-composer", cfg["__html_content__"])
        self.assertIn("atl-aaaa0001", cfg["__html_content__"])
        self.assertEqual(cfg["canvas"]["html"], _CANVAS_DOC)
        self.assertEqual(cfg["canvas_report"]["fact_check"]["ok"], True)
        self.assertEqual(cfg["html_source"], "canvas")
        self.assertTrue(result["canvas"]["fresh"])
        self.assertTrue(result["canvas"]["fact_check_ok"])

    def test_stored_canvas_reused_on_rerender(self):
        # shuffle/override re-render (full=False): the stored document
        # drives the page — no re-authoring, render_page still skipped.
        result, cfg = self._call(None, full=False,
                                 stored_cfg={"canvas": {"html": _CANVAS_DOC}})
        self.assertIn("atl-aaaa0001", cfg["__html_content__"])
        self.assertFalse(result["canvas"]["fresh"])

    def test_full_module_compose_clears_stale_canvas(self):
        # a full recompose WITHOUT the canvas must clear both keys (a
        # stale canvas never masks a fresh module compose). render_page
        # runs here — restore it and hand it a real render.
        import site_composer
        patched = {}

        def _patch_as_service(path, payload):
            patched.update(payload.get("site_config") or {})
            return None

        with mock.patch.object(site_composer, "_ensure_site_row",
                               return_value={"id": "site-1", "site_config":
                                             {"canvas": {"html": _CANVAS_DOC},
                                              "canvas_report": {}}}), \
                mock.patch.object(site_composer.sb_clients,
                                  "sb_get_as_service", return_value=[]), \
                mock.patch.object(site_composer.sb_clients,
                                  "sb_patch_as_service",
                                  side_effect=_patch_as_service), \
                mock.patch.object(site_composer, "_run_quality_gate",
                                  return_value=({"passed": True, "checks": []},
                                                [])), \
                mock.patch("vision_grader.grade", return_value=None), \
                mock.patch("design_register.get_invention_count",
                           return_value=None), \
                mock.patch.object(site_composer, "_verify_inventions",
                                  return_value={}):
            site_composer.render_and_persist(
                "biz-canvas", _spec(), _ctx(), dro=None, full_recompose=True)
        self.assertNotIn("canvas", patched)
        self.assertNotIn("canvas_report", patched)
        self.assertEqual(patched.get("html_source"), "module-composer")


class TestComposeSiteGate(unittest.TestCase):
    """compose_site's canvas branch: gated on SITE_CANVAS=on + full
    recompose + a DRO. All LLM/DB boundaries mocked."""

    def _compose(self, env_on):
        import site_composer
        canvas_out = {"html": "<html>canvas page</html>",
                      "report": {"fact_check": {"ok": True}, "fallbacks": [],
                                 "planned": {"authored": ["hero"]}}}
        env = {"SITE_CANVAS": "on"} if env_on else {}
        with mock.patch.dict(os.environ, env, clear=False):
            if not env_on:
                os.environ.pop("SITE_CANVAS", None)
            with mock.patch.object(site_composer, "gather_context",
                                   return_value=_ctx()), \
                    mock.patch.object(site_composer, "_maybe_analyze_references",
                                      return_value=None), \
                    mock.patch("agents.composer.drl.passes.produce_dro",
                               return_value=(_dro(), None)), \
                    mock.patch.object(site_composer, "compose_spec_llm",
                                      return_value=_spec()), \
                    mock.patch.object(site_composer, "_ensure_site_row",
                                      return_value={"id": "s1",
                                                    "site_config": {}}), \
                    mock.patch.object(site_composer, "render_and_persist",
                                      return_value={"vision_verdict": None,
                                                    "quality_report": {}}) as rp, \
                    mock.patch("canvas.run_canvas",
                               return_value=canvas_out) as rc:
                site_composer.compose_site("biz-canvas")
        return rp, rc

    def test_env_off_never_touches_canvas(self):
        rp, rc = self._compose(env_on=False)
        self.assertFalse(rc.called)
        self.assertIsNone(rp.call_args.kwargs["_canvas_html"])

    def test_env_on_flows_canvas_through(self):
        rp, rc = self._compose(env_on=True)
        self.assertTrue(rc.called)
        self.assertEqual(rp.call_args.kwargs["_canvas_html"],
                         "<html>canvas page</html>")
        self.assertEqual(rp.call_args.kwargs["_canvas_report"]
                         ["fact_check"]["ok"], True)


if __name__ == "__main__":
    unittest.main()
