"""Design-audit P2/B1 tests (2026-07-18).

B1 — every DRO axis must reach the pixels. The schema enums
(whitespace.philosophy, motion.temperature, palette.accent_strategy,
palette.temperature) used to fall through tolerant keyword matching and
change NOTHING on the page: warm_close / editorial_rhythm / dense_energy,
subtle_entrance / ambient_breathing and tonal_monochrome were silent
no-ops. These tests pin the renderers each value now maps to, the new
"entrance" motion tier's loop-stilling semantics, the temperature
ground-nudge, and the no-silent-no-op warnings.
"""
import unittest


def _dna():
    import brand_dna
    # bundle={} → deterministic defaults (formal/restrained), no I/O.
    return brand_dna.build_brand_dna("biz-b1-tests", {})


class TestMotionTierMapping(unittest.TestCase):
    def _motion(self, temperature):
        import brand_dna
        out = brand_dna.apply_dro_style(_dna(), {"motion": {"temperature": temperature}})
        return out.get("motion")

    def test_subtle_entrance_maps_entrance(self):
        self.assertEqual(self._motion("subtle_entrance"), "entrance")

    def test_ambient_breathing_maps_standard(self):
        self.assertEqual(self._motion("ambient_breathing"), "standard")

    def test_none_still_subtle(self):
        self.assertEqual(self._motion("none"), "subtle")

    def test_expressive_still_rich(self):
        self.assertEqual(self._motion("expressive"), "rich")

    def test_unknown_temperature_warns_and_keeps_tier(self):
        with self.assertLogs("brand_dna", level="WARNING") as logs:
            tier = self._motion("vibrating")
        self.assertIn("motion.temperature", "\n".join(logs.output))
        self.assertEqual(tier, _dna().get("motion"))   # untouched, not silent


class TestEntranceTierRendering(unittest.TestCase):
    def _entrance_dna(self):
        dna = _dna()
        dna["motion"] = "entrance"
        return dna

    def test_reveal_css_ships_but_loops_stilled(self):
        from site_modules import _base
        css = _base.base_css(self._entrance_dna())
        self.assertIn(".sxm-reveal {", css)                 # arrivals ship
        self.assertIn(".sxm-depth-orb { animation: none; }", css)  # loops stilled

    def test_reveal_script_ships(self):
        from site_modules import _base
        self.assertTrue(_base.reveal_script(self._entrance_dna()))

    def test_signature_move_allowed(self):
        from site_modules import _base
        design = {"motion": {"temperature": "subtle_entrance",
                             "signature_move": "a gentle cascade"}}
        self.assertEqual(_base.signature_move_class(self._entrance_dna(), design),
                         "sx-sig-cascade")

    def test_marquee_stilled(self):
        from site_modules import interstitial
        words = "crafted • warm • honest • premium • quiet"
        _, css = interstitial.render("marquee", {"words": words},
                                     {"dna": self._entrance_dna()})
        # still override + the reduced-motion block = two static-row rules
        self.assertEqual(css.count("justify-content: center"), 2)

    def test_thread_and_silence_stilled(self):
        from site_modules import interstitial
        _, css_t = interstitial.render("thread", {}, {"dna": self._entrance_dna()})
        _, css_s = interstitial.render("silence", {"ghost": "calm"},
                                       {"dna": self._entrance_dna()})
        self.assertNotIn("sxm-int-sweep", css_t)
        self.assertNotIn("sxm-int-breathe", css_s)

    def test_hero_word_land_kept(self):
        # word-land is ARRIVAL motion — the entrance tier keeps it.
        from site_modules import hero
        _, css = hero.render("anchored",
                             {"headline": "Test headline here", "subheadline": "s",
                              "cta_label": "Go", "cta_href": "#"},
                             {"dna": self._entrance_dna(), "business": {"name": "T"}})
        self.assertIn("sxm-word-land", css)


class TestWhitespaceTierMapping(unittest.TestCase):
    def _pad(self, philosophy):
        import brand_dna
        out = brand_dna.apply_dro_style(
            _dna(), {"whitespace": {"philosophy": philosophy}})
        return out["rhythm"]["section_pad"]

    def test_confidence_air_airiest(self):
        import brand_dna
        self.assertEqual(self._pad("confidence_air"),
                         brand_dna.derive_rhythm("bold")["section_pad"])

    def test_warm_close_restrained(self):
        import brand_dna
        self.assertEqual(self._pad("warm_close"),
                         brand_dna.derive_rhythm("restrained")["section_pad"])

    def test_dense_energy_restrained(self):
        import brand_dna
        self.assertEqual(self._pad("dense_energy"),
                         brand_dna.derive_rhythm("restrained")["section_pad"])

    def test_editorial_rhythm_middle_tier(self):
        import brand_dna
        self.assertEqual(self._pad("editorial_rhythm"),
                         brand_dna.derive_rhythm("confident")["section_pad"])

    def test_unknown_philosophy_warns(self):
        import brand_dna
        with self.assertLogs("brand_dna", level="WARNING") as logs:
            brand_dna.apply_dro_style(
                _dna(), {"whitespace": {"philosophy": "chaotic_neutral"}})
        self.assertIn("whitespace.philosophy", "\n".join(logs.output))


class TestEditorialRhythmBodyClass(unittest.TestCase):
    def test_page_shell_class_and_css(self):
        from site_modules import _base
        html = _base.page_shell(
            _dna(), "t", "<section class='sxm-section'>x</section>", "",
            design={"whitespace": {"philosophy": "editorial_rhythm"}})
        self.assertIn("sx-editorial-rhythm", html.split('<body class="')[1])
        self.assertIn("sx-editorial-rhythm .sxm-section:nth-of-type(even)",
                      _base.base_css(_dna()))


class TestTonalMonochrome(unittest.TestCase):
    def test_body_classes(self):
        from site_modules import _base
        html = _base.page_shell(
            _dna(), "t", "x", "",
            design={"palette": {"accent_strategy": "tonal_monochrome"}})
        body_class = html.split('<body class="')[1].split('"')[0]
        self.assertIn("sx-scarce-accent", body_class)
        self.assertIn("sx-mono-accent", body_class)

    def test_mono_override_in_base_css(self):
        from site_modules import _base
        css = _base.base_css(_dna())
        self.assertIn("body.sx-mono-accent", css)
        self.assertIn("--sx-secondary-soft: var(--sx-surface2)", css)

    def test_single_semantic_regression(self):
        from site_modules import _base
        html = _base.page_shell(
            _dna(), "t", "x", "",
            design={"palette": {"accent_strategy": "single_semantic"}})
        body_class = html.split('<body class="')[1].split('"')[0]
        self.assertIn("sx-scarce-accent", body_class)
        self.assertNotIn("sx-mono-accent", body_class)

    def test_unknown_strategy_warns(self):
        import brand_dna
        with self.assertLogs("brand_dna", level="WARNING") as logs:
            brand_dna.apply_dro_style(
                _dna(), {"palette": {"accent_strategy": "rainbow_chaos"}})
        self.assertIn("accent_strategy", "\n".join(logs.output))


class TestTemperatureNudge(unittest.TestCase):
    def _cool_dna(self):
        import brand_dna
        return brand_dna.apply_dro_palette(_dna(), {"base": "cool_light"})

    def test_warm_flips_cool_ground(self):
        import brand_dna
        nudged = brand_dna.apply_dro_temperature(self._cool_dna(), "warm")
        h, _l, _s = brand_dna._hls(nudged["palette"]["bg"])
        hue = h * 360
        self.assertTrue(hue < 60 or hue > 300,
                        f"warm-nudged bg should sit in the warm hue family, got {hue}")
        self.assertNotEqual(nudged["palette"]["bg"], "#f7f9fb")

    def test_cool_tints_true_gray(self):
        import brand_dna
        dna = self._cool_dna()
        dna["palette"] = dict(dna["palette"], bg="#808080")
        nudged = brand_dna.apply_dro_temperature(dna, "cool")
        h, _l, s = brand_dna._hls(nudged["palette"]["bg"])
        self.assertTrue(190 < h * 360 < 230)
        self.assertGreaterEqual(s, 0.016)     # gray got the visible floor

    def test_accent_family_rederived(self):
        import brand_dna
        nudged = brand_dna.apply_dro_temperature(self._cool_dna(), "warm")
        for key in ("accent_soft", "accent_strong", "on_accent", "authority"):
            self.assertIn(key, nudged["palette"])

    def test_input_untouched(self):
        cool = self._cool_dna()
        import brand_dna
        brand_dna.apply_dro_temperature(cool, "warm")
        self.assertEqual(cool["palette"]["bg"], "#f7f9fb")

    def test_unknown_temperature_warns_and_noops(self):
        import brand_dna
        cool = self._cool_dna()
        with self.assertLogs("brand_dna", level="WARNING") as logs:
            out = brand_dna.apply_dro_temperature(cool, "fiery")
        self.assertIn("palette.temperature", "\n".join(logs.output))
        self.assertEqual(out["palette"]["bg"], "#f7f9fb")

    def test_empty_temperature_noop_no_warning(self):
        import brand_dna
        cool = self._cool_dna()
        out = brand_dna.apply_dro_temperature(cool, "")
        self.assertEqual(out["palette"]["bg"], "#f7f9fb")


# ─── B4 (2026-07-18) — second compositions + bespoke contact ──────────

def _b4_ctx(**over):
    """A ctx rich enough for every new variant to render."""
    import brand_dna
    ctx = {
        "dna": brand_dna.build_brand_dna("biz-b4-tests", {}),
        "business": {"name": "Atelier T", "created_at": "2020-01-01T00:00:00Z"},
        "booking": {"enabled": True, "url": "https://book.example.com"},
        "offerings": [{"name": "Session"}, {"name": "Package"}],
        "testimonials": [{"quote": "Wonderful work."}, {"quote": "Changed things."}],
        "contact": {"submit_url": "https://api.example.com/contact-submit",
                    "email": "hi@example.com", "phone": "555-0100"},
        "store": {"enabled": True, "url": "https://store.example.com",
                  "items": [{"name": "Print A", "image_url": "https://img.example.com/a.jpg",
                             "current_price": 42},
                            {"name": "Print B", "image_url": "https://img.example.com/b.jpg",
                             "current_price": 18}]},
    }
    ctx.update(over)
    return ctx


class TestSecondVariants(unittest.TestCase):
    def test_registry_variants(self):
        import site_modules
        self.assertEqual(site_modules.MODULES["cta"]["variants"], ("band", "editorial"))
        self.assertEqual(site_modules.MODULES["statband"]["variants"], ("band", "ledger"))
        self.assertEqual(site_modules.MODULES["store"]["variants"], ("featured", "shelf"))
        self.assertEqual(site_modules.MODULES["contact"]["variants"], ("standard", "centered"))

    def test_cta_editorial_renders_working_link(self):
        from site_modules import cta_band
        html, css = cta_band.render("editorial", {"headline": "Ready?", "cta_label": "Book now"},
                                    _b4_ctx())
        self.assertIn("sxm-cta-link", html)
        self.assertIn("https://book.example.com", html)
        self.assertIn(".sxm-ctaed", css)
        # the band is untouched
        html_b, _ = cta_band.render("band", {"headline": "Ready?"}, _b4_ctx())
        self.assertIn("sxm-ctaband", html_b)

    def test_cta_link_label_intent_still_governs(self):
        from site_modules import cta_band
        html, _ = cta_band.render("editorial", {"cta_label": "Get in touch"}, _b4_ctx())
        self.assertIn('href="#contact"', html)   # contact-talk never routes to booking

    def test_statband_ledger_rows_and_floor(self):
        from site_modules import statband
        html, css = statband.render("ledger", {"headline": "Proof"}, _b4_ctx())
        self.assertGreaterEqual(html.count('class="sxm-statrow"'), 3)
        self.assertIn("sxm-statledger-rows", css)
        # data floor intact: fewer than two real stats → nothing
        self.assertEqual(statband.render("ledger", {}, {"dna": _b4_ctx()["dna"],
                                                        "business": {}}), ("", ""))
        html_b, _ = statband.render("band", {}, _b4_ctx())
        self.assertIn("sxm-stat-grid", html_b)

    def test_store_shelf_items_and_floor(self):
        from site_modules import store
        html, css = store.render("shelf", {}, _b4_ctx())
        self.assertEqual(html.count("sxm-shelf-item"), 2)
        self.assertIn("$42.00", html)
        self.assertIn("sxm-shelf-row", css)
        # trust floor intact: no real products → nothing
        bare = _b4_ctx(store={"enabled": True, "url": "https://s.example.com", "items": []})
        self.assertEqual(store.render("shelf", {}, bare), ("", ""))
        html_f, _ = store.render("featured", {}, _b4_ctx())
        self.assertIn("sxm-store-card", html_f)

    def test_contact_centered_form_and_solo(self):
        from site_modules import contact_footer
        html, css = contact_footer.render("centered", {"headline": "Say hello"}, _b4_ctx())
        self.assertIn("sxm-contact-centered", html)
        self.assertIn('id="sxm-contact-form"', html)
        self.assertIn("<script>", html)                 # wiring script ships
        self.assertIn(".sxm-contact-form {", css)       # shared CONTACT_FORM_CSS
        # no endpoint → solo, no form, still a composed finale
        html_s, _ = contact_footer.render("centered", {"headline": "Hi"},
                                          _b4_ctx(contact={"email": "hi@example.com"}))
        self.assertNotIn('id="sxm-contact-form"', html_s)
        self.assertIn("sxm-contact-invite", html_s)
        # standard untouched
        html_std, _ = contact_footer.render("standard", {"headline": "Hi"}, _b4_ctx())
        self.assertIn("sxm-contact-inner", html_std)

    def test_module_menu_lists_new_variants(self):
        import site_composer
        menu = site_composer._module_menu()
        for v in ("ledger", "shelf", "editorial", "centered"):
            self.assertIn(v, menu)


class TestBespokeContact(unittest.TestCase):
    def test_eligibility(self):
        import atelier
        self.assertNotIn("contact", atelier._NEVER_BESPOKE)
        for still in ("store", "statband", "showcase", "interstitial"):
            self.assertIn(still, atelier._NEVER_BESPOKE)
        self.assertEqual(atelier.ALLOWED_SLOTS.get("contact"), ())

    def test_plan_seats_contact_on_rule_break(self):
        import atelier
        spec = [{"module": m, "variant": "x", "content": {}} for m in
                ("hero", "about", "offerings", "contact")]
        dro = {"decisions": {"rule_break": {"what": "oversize the close",
                                            "where": "the contact form finale"}}}
        picks = [spec[i]["module"]
                 for i in atelier.plan_bespoke(dro, spec, _b4_ctx())]
        self.assertIn("contact", picks)
        self.assertEqual(picks[0], "hero")

    def test_plan_never_seats_data_dense(self):
        import atelier
        spec = [{"module": m, "variant": "x", "content": {}} for m in
                ("hero", "statband", "store", "showcase", "contact")]
        dro = {"decisions": {"rule_break": {"what": "loud", "where": "proof numbers"}}}
        picks = [spec[i]["module"]
                 for i in atelier.plan_bespoke(dro, spec, _b4_ctx())]
        self.assertNotIn("statband", picks)
        self.assertNotIn("store", picks)
        self.assertNotIn("showcase", picks)

    def test_contact_form_passthrough(self):
        import atelier
        fh, fs = atelier._contact_form(_b4_ctx())
        self.assertTrue(fh.strip().startswith("<form"))
        self.assertIn("contact-submit", fh)
        self.assertTrue(fs)
        self.assertEqual(atelier._contact_form({"dna": _b4_ctx()["dna"]}), ("", ""))

    def test_prompt_form_token_block(self):
        import atelier
        p = atelier.build_bespoke_prompt("contact", "standard", "abc12345", {},
                                         {"copy": {}}, (), [], form_token=True)
        self.assertIn("WORKING FORM", p)
        self.assertIn(atelier._FORM_TOKEN, p)
        p2 = atelier.build_bespoke_prompt("about", None, "abc12345", {},
                                          {"copy": {}}, (), [])
        self.assertNotIn("WORKING FORM", p2)

    def test_refine_prompt_form_line(self):
        import atelier
        rp = atelier.build_refine_prompt("contact", "abc12345", {}, {"copy": {}},
                                         "<section>x</section>", "", "moodier",
                                         (), [], form_token=True)
        self.assertIn("THE WORKING FORM", rp)
        rp2 = atelier.build_refine_prompt("about", "abc12345", {}, {"copy": {}},
                                          "<section>x</section>", "", "moodier",
                                          (), [])
        self.assertNotIn("THE WORKING FORM", rp2)

    def test_run_atelier_ships_form_runtime(self):
        import atelier
        html = ('<html><head></head><body>'
                '<!--sx:contact:3--><section id="contact">module</section>'
                '<!--/sx:contact:3--></body></html>')
        frag = {"html": ('<section id="contact" class="atl-aaaaaaaa">'
                         '<form id="sxm-contact-form"></form></section>'),
                "css": ".atl-aaaaaaaa { display: block; }", "index": 3,
                "variant": "standard"}
        out, meta = atelier.run_atelier(
            html, [], _b4_ctx(), None, "biz-b4-tests",
            regenerate=False, stored={"fragments": {"contact": frag}})
        self.assertIn("atl-aaaaaaaa", out)                     # fragment landed
        self.assertIn(".sxm-contact-form {", out)              # CONTACT_FORM_CSS
        tail = out.split("</head>")[-1]
        self.assertIn("sxm-consent-armed", tail)               # script in body

    def test_contact_section_data(self):
        import atelier
        data = atelier._section_data("contact", {}, _b4_ctx())
        ch = data.get("contact_channels") or {}
        self.assertEqual(ch.get("email"), "hi@example.com")
        self.assertEqual(ch.get("phone"), "555-0100")
        self.assertEqual(data.get("booking_url"), "https://book.example.com")


class TestShellIdiomRotation(unittest.TestCase):
    """P3d (2026-07-18) — the accent-word pick rotates per headline, and a
    fourth signature move (wipe) widens the motion repertoire."""

    def test_accent_word_two_word_plain(self):
        from site_modules._base import accent_headline
        self.assertEqual(accent_headline("Quiet Luxury"), "Quiet Luxury")
        self.assertEqual(accent_headline("Hello"), "Hello")

    def test_accent_word_deterministic(self):
        from site_modules._base import accent_headline
        h = "Handcrafted Furniture For Modern Rooms"
        self.assertEqual(accent_headline(h), accent_headline(h))
        self.assertIn('<em class="sxm-accent-word">', accent_headline(h))

    def test_accent_word_rotates_not_always_longest(self):
        from site_modules._base import accent_headline, _ALPHA_RE
        sample = ["Handcrafted Furniture For Modern Rooms",
                  "A Quiet Place To Heal Fully",
                  "Bold Cakes For Loud Parties",
                  "Where Stories Become Heirlooms Daily",
                  "Small Batch Roasts Done Right",
                  "Your Home Deserves Better Light",
                  "We Build Gardens That Last",
                  "Portraits That Feel Like You",
                  "Slow Food For Fast Lives",
                  "The Old Ways Made New Again"]
        longest_hits = 0
        treated = 0
        for s in sample:
            out = accent_headline(s)
            if "<em" not in out:
                continue
            treated += 1
            em = out.split('<em class="sxm-accent-word">')[1].split("</em>")[0]
            words = s.split()
            longest = max(words, key=lambda w: len(_ALPHA_RE.sub("", w)))
            if em == longest:
                longest_hits += 1
        self.assertGreaterEqual(treated, 8)
        self.assertLess(longest_hits, treated)  # not the old always-longest tell

    def test_accent_word_short_words_never_treated(self):
        from site_modules._base import accent_headline
        self.assertNotIn("<em", accent_headline("Go To The Sea"))

    def test_accent_word_escapes(self):
        from site_modules._base import accent_headline
        out = accent_headline("Bold <script> Moves Daily")
        self.assertNotIn("<script>", out)
        self.assertIn("&lt;script&gt;", out)

    def test_wipe_keyword_family(self):
        from site_modules._base import signature_move_class
        dna = {"motion": "standard"}
        for mv in ("a soft wipe reveal", "curtain lift", "veil of light",
                   "shutter opening", "unveil the band"):
            self.assertEqual(signature_move_class(dna, {"motion": {"signature_move": mv}}),
                             "sx-sig-wipe", mv)

    def test_sweep_stays_underline(self):
        from site_modules._base import signature_move_class
        self.assertEqual(signature_move_class(
            {"motion": "standard"}, {"motion": {"signature_move": "slow sweep"}}),
            "sx-sig-underline")

    def test_hash_fallback_covers_four_families(self):
        from site_modules._base import signature_move_class
        dna = {"motion": "standard"}
        vals = {signature_move_class(dna, {"motion": {"signature_move": f"xyzzy {i}"}})
                for i in range(60)}
        self.assertEqual(vals, {"sx-sig-cascade", "sx-sig-drift",
                                "sx-sig-underline", "sx-sig-wipe"})

    def test_entrance_tier_never_drifts(self):
        from site_modules._base import signature_move_class
        dna = {"motion": "entrance"}
        arrivals = {"sx-sig-cascade", "sx-sig-underline", "sx-sig-wipe"}
        # drift keywords fall through to an arrival family under entrance
        self.assertIn(signature_move_class(
            dna, {"motion": {"signature_move": "ambient drift"}}), arrivals)
        # explicit wipe stays legal (arrival motion)
        self.assertEqual(signature_move_class(
            dna, {"motion": {"signature_move": "curtain lift"}}), "sx-sig-wipe")
        # hash fallback under entrance only yields arrival families
        vals = {signature_move_class(dna, {"motion": {"signature_move": f"xyzzy {i}"}})
                for i in range(60)}
        self.assertTrue(vals <= arrivals)

    def test_subtle_still_no_signature(self):
        from site_modules._base import signature_move_class
        self.assertEqual(signature_move_class(
            {"motion": "subtle"}, {"motion": {"signature_move": "wipe"}}), "")

    def test_wipe_css_ships_with_motion(self):
        from site_modules._base import base_css
        css = base_css({"motion": "standard"})
        self.assertIn("body.sx-sig-wipe .sxm-reveal { clip-path: inset(0 0 14% 0);", css)
        self.assertIn("body.sx-sig-wipe .sxm-reveal.sxm-in { clip-path: inset(0 0 0 0); }", css)
        self.assertIn("body.sx-sig-wipe .sxm-reveal { clip-path: none; }", css)
        self.assertIn("body.sx-sig-soft.sx-sig-wipe .sxm-reveal { clip-path: inset(0 0 5% 0); }", css)

    def test_wipe_css_active_rule_absent_when_subtle(self):
        from site_modules._base import base_css
        css = base_css({"motion": "subtle"})
        # the ACTIVE wipe rides the reveal observer, which subtle never ships;
        # only the inert soft-tier rule (always-on _RULE_BREAK_CSS) may appear
        self.assertNotIn("inset(0 0 14% 0)", css)


if __name__ == "__main__":
    unittest.main()
