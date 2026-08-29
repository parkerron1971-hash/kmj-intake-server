"""
test_builder_v2.py — Revamp Phase 2: one mind, one call, armor after.

Pins the deterministic armor (the annotator, JS/external armor), the
authorship checks (truth + coverage), parsing, and the surgical-repair
prompt shape. The live call itself rides the model_ladder and is
exercised by real builds behind the flag.
"""
import os
from unittest import mock

import builder_v2 as v2


def test_flag_default_off():
    with mock.patch.dict(os.environ, {}, clear=True):
        assert v2.enabled() is False
    with mock.patch.dict(os.environ, {"SITE_BUILDER_V2": "on"}):
        assert v2.enabled() is True


# ─── parsing ─────────────────────────────────────────────────────────

def test_parse_doc_strips_fences_and_bounds():
    raw = "```html\n<!DOCTYPE html><html><head></head><body>x</body></html>\n```"
    doc = v2._parse_doc(raw)
    assert doc.startswith("<!DOCTYPE html>") and doc.endswith("</html>")
    assert v2._parse_doc("no document here") is None


# ─── the annotator (Amendment 1: platform guarantee) ─────────────────

def test_annotator_adds_targets_and_preserves_existing():
    html = ("<html><body><h1 data-override-target='v2/f1'>Hi</h1>"
            "<p>copy one</p><p>copy two</p></body></html>")
    out, added = v2.annotate_editability(html)
    assert added == 2                       # two unstamped paragraphs
    assert 'data-override-target="v2/auto_1"' in out
    assert "v2/f1" in out                   # existing stamp untouched
    assert out.count("data-override-target") == 3


def test_annotator_never_reserializes_the_document():
    """AUDIT FIX (flight one): the bs4 version re-serialized the whole
    doc and lowercased case-sensitive SVG attributes — silently
    breaking inline-SVG signature moves (viewBox, preserveAspectRatio)
    before the judge ever saw them. The regex version touches ONLY the
    matched opening tags."""
    html = ("<html><body>"
            '<svg viewBox="0 0 10 10" preserveAspectRatio="xMidYMid meet">'
            '<circle r="2"/></svg>'
            "<script>if(a>1){b()}</script><p>text</p></body></html>")
    out, added = v2.annotate_editability(html)
    assert added == 1
    assert "viewBox" in out and "preserveAspectRatio" in out
    assert "if(a>1)" in out


def test_truth_exempts_design_numerals_and_current_year():
    """AUDIT FIX: '01' section numerals and the copyright year are
    layout and dates, not claims — the old 2-digit rule fired repairs
    that pressured the author to strip its own design language."""
    from datetime import datetime, timezone
    year = datetime.now(timezone.utc).year
    data = 'BUSINESS: KMJ\n{"count": "400"}'
    page = (f"<html><body><p>01</p><p>02 — Phase</p><p>© {year}</p>"
            f"<p>400 clients</p><p>trusted by 999</p></body></html>")
    flags = v2.check_truth(page, data)
    assert len(flags) == 1 and "999" in flags[0]


# ─── mechanical armor ────────────────────────────────────────────────

def test_script_armor_drops_banned_keeps_clean():
    html = ("<script>fetch('https://evil')</script>"
            "<script>(function(){document.body.classList.add('x')})()</script>")
    out, dropped = v2.armor_scripts(html)
    assert "fetch" not in out and "classList" in out
    assert dropped == ["fetch("]


def test_script_armor_allows_the_contact_fetch_literal_only():
    """The 2026-07-25 blank-sections bug: the contact endpoint reads
    JSON, so the page's script MUST fetch it — but the armor dropped any
    script containing fetch(, taking the reveals down with it. The one
    permitted form is the inline string-literal call to the platform's
    own endpoint; every other fetch still fells the script."""
    ep = v2.contact_endpoint("b1")
    ok = (f"<script>fetch(\"{ep}\", {{method:'POST'}});"
          "document.body.classList.add('shown')</script>")
    out, dropped = v2.armor_scripts(ok, allowed_fetch=ep)
    assert dropped == [] and "classList" in out
    # single-quoted literal is equally fine
    out, dropped = v2.armor_scripts(
        f"<script>fetch('{ep}')</script>", allowed_fetch=ep)
    assert dropped == []
    # any OTHER fetch target still drops the script
    out, dropped = v2.armor_scripts(
        f"<script>fetch(\"{ep}\");fetch('https://evil')</script>",
        allowed_fetch=ep)
    assert dropped == ["fetch("] and "evil" not in out
    # a variable target is not verifiable → dropped
    out, dropped = v2.armor_scripts(
        "<script>var u=x;fetch(u)</script>", allowed_fetch=ep)
    assert dropped == ["fetch("]
    # without an allowance the old behavior holds
    out, dropped = v2.armor_scripts(f"<script>fetch('{ep}')</script>")
    assert dropped == ["fetch("]


def test_armor_violations_name_the_cause_and_the_permitted_form():
    ep = v2.contact_endpoint("b1")
    vs = v2.armor_violations(["fetch("], ep)
    assert len(vs) == 1
    assert "SCRIPT REMOVED" in vs[0]          # says what happened
    assert '"fetch("' in vs[0]                # names the banned call
    assert ep in vs[0]                        # teaches the permitted form
    assert v2.armor_violations([], ep) == []


def test_external_armor_keeps_fonts_strips_rest():
    html = ('<link href="https://fonts.googleapis.com/css2?family=X" rel="stylesheet">'
            '<link href="https://evil.example/steal.css" rel="stylesheet">'
            '<script src="https://cdn.example/x.js"></script>'
            '<iframe src="https://x.example"></iframe><p>hi</p>')
    out, stripped = v2.armor_external(html)
    assert "fonts.googleapis.com" in out
    assert "evil.example" not in out
    assert "cdn.example" not in out and "iframe" not in out
    assert len(stripped) == 3


# ─── authorship checks ───────────────────────────────────────────────

_DATA = """BUSINESS: KMJ — type: consultant
CONTACT FORM ENDPOINT (the form's action): https://api.example/sites/b1/contact-submit
IMAGES (every one appears on the page, exact urls):
- https://x/one.png (tee)
- https://x/two.png (flyer)
[statband]
{"years": "15"}"""


def test_truth_traces_digit_runs():
    ok_html = "<html><body><p>15 years in business</p></body></html>"
    assert v2.check_truth(ok_html, _DATA) == []
    bad_html = "<html><body><p>Trusted by 400 clients</p></body></html>"
    problems = v2.check_truth(bad_html, _DATA)
    assert problems and "400" in problems[0]


def test_coverage_checks_images_nav_form_footer_endpoint():
    html = ("<html><body><nav>x</nav>"
            "<img src='https://x/one.png'><img src='https://x/two.png'>"
            "<form method='POST' action='https://api.example/sites/b1/contact-submit'>"
            "<input name='email'></form><footer>f</footer></body></html>")
    assert v2.check_coverage(html, _DATA) == []
    missing = v2.check_coverage("<html><body><p>bare</p></body></html>", _DATA)
    joined = " | ".join(missing)
    assert "https://x/one.png" in joined
    assert "<nav>" in joined or "no <nav>" in joined
    assert "no <form>" in joined and "no <footer>" in joined


# ─── the new laws (Kevin's review, 2026-07-25) ───────────────────────

def test_dash_law_flags_spliced_copy_and_exempts_titles():
    html = ("<html><body>"
            "<p>We do the work — together.</p>"
            "<h2>Clean headline</h2>"
            "<figcaption><strong>The Glow Up — Summer Series</strong>"
            "</figcaption></body></html>")
    problems = v2.check_grammar(html)
    assert len(problems) == 1
    assert "DASH LAW" in problems[0] and "together" in problems[0]


def test_dash_law_clean_page_passes():
    html = ("<html><body><p>We do the work, together.</p>"
            "<p>One kind of person: the one who moves.</p></body></html>")
    assert v2.check_grammar(html) == []


def test_head_check_requires_title_description_og():
    bare = "<html><head></head><body></body></html>"
    problems = " | ".join(v2.check_head(bare))
    assert "<title>" in problems and "description" in problems \
        and "og:image" in problems
    good = ("<html><head><title>KMJ</title>"
            '<meta name="description" content="x">'
            '<meta property="og:image" content="https://x/y.png">'
            "</head><body></body></html>")
    assert v2.check_head(good) == []


def test_gallery_requires_lightbox_only_at_gallery_scale():
    imgs5 = "<img src='a'>" * 5
    assert any("lightbox" in p for p in
               v2.check_interactions(f"<html><body>{imgs5}</body></html>"))
    # a lightbox satisfies it
    ok = f"<html><body>{imgs5}<div id=\"lightbox\"></div></body></html>"
    assert v2.check_interactions(ok) == []
    # four images is not a gallery
    assert v2.check_interactions(
        "<html><body>" + "<img src='a'>" * 4 + "</body></html>") == []


def test_reveal_safety_flags_observer_without_scroll_fallback():
    risky = ("<html><style>.rv{opacity:0}</style><body>"
             "<script>new IntersectionObserver(function(){})</script>"
             "</body></html>")
    assert any("REVEAL SAFETY" in p for p in v2.check_interactions(risky))
    safe = ("<html><style>.rv{opacity:0}</style><body>"
            "<script>new IntersectionObserver(function(){});"
            "window.addEventListener('scroll',sweep)</script>"
            "</body></html>")
    assert not any("REVEAL SAFETY" in p for p in v2.check_interactions(safe))


def test_reveal_safety_flags_hidden_state_with_no_script_at_all():
    """The armored page from 2026-07-25: reveal CSS survived, the script
    did not — eleven sections at opacity:0 with nothing left to show
    them. A scriptless page with reveal-hidden CSS fails the law."""
    orphaned = ("<html><style>.reveal{opacity:0}</style><body>"
                "<p class='reveal'>hi</p></body></html>")
    assert any("no script" in p for p in v2.check_interactions(orphaned))
    # a real runtime beside the hidden state passes this check
    alive = ("<html><style>.reveal{opacity:0}</style><body>"
             "<script>window.addEventListener('scroll',s)</script>"
             "</body></html>")
    assert not any("no script" in p for p in v2.check_interactions(alive))
    # no hidden state, no script needed
    plain = "<html><body><p>hi</p></body></html>"
    assert v2.check_interactions(plain) == []


# ─── the eyes (vision loop plumbing — no browser, no API) ────────────

def test_eyes_flag_defaults_on_and_conftest_holds_it_off():
    import os
    assert os.environ.get("SITE_V2_VISION_LOOP") == "off"   # tests never pay
    with mock.patch.dict(os.environ, {}, clear=True):
        assert v2.eyes_enabled() is True                     # prod default on
    with mock.patch.dict(os.environ, {"SITE_V2_VISION_LOOP": "off"}):
        assert v2.eyes_enabled() is False


def test_parse_inspector_verdicts():
    good = ('```json\n{"verdict":"repair","violations":[{"where":"hero",'
            '"what":"portrait floats small","fix":"cover-fit"}]}\n```')
    out = v2._parse_inspector(good)
    assert out["verdict"] == "repair" and len(out["violations"]) == 1
    # empty violations collapses to ship; junk returns None
    assert v2._parse_inspector('{"verdict":"repair","violations":[]}')[
        "verdict"] == "ship"
    assert v2._parse_inspector("not json") is None
    assert v2._parse_inspector('{"verdict":"maybe"}') is None


def test_vision_violations_become_surgical_prompt_lines():
    p = v2.build_user_prompt(
        "SPEC", "DATA",
        violations=["SEEN IN THE RENDER (hero): portrait floats small "
                    "— FIX: cover-fit the frame"],
        prior_doc="<html>doc</html>")
    assert "SURGICAL REPAIR" in p and "SEEN IN THE RENDER" in p


# ─── the surgical repair prompt (never a re-roll) ────────────────────

def test_repair_prompt_is_surgical():
    p = v2.build_user_prompt("SPEC", "DATA",
                             violations=["number '400' untraced"],
                             prior_doc="<html>doc</html>")
    assert "SURGICAL REPAIR" in p
    assert "Fix ONLY what each violation requires" in p
    assert "number '400' untraced" in p
    assert "<html>doc</html>" in p
    # the fresh-build prompt carries the spec as law instead
    p2 = v2.build_user_prompt("SPEC TEXT", "DATA")
    assert "THE APPROVED SPEC" in p2 and "SURGICAL" not in p2


def test_filled_space_rule_rides_builder_prompt_and_inspector():
    """The builder executes the FILLED-SPACE LAW (rule 14) and the eyes
    measure it from the render walk (dead bands are visible in stills;
    arrival variety stays a prompt-level law)."""
    assert "FILLED SPACE" in v2._SYSTEM
    assert "transition-delay" in v2._SYSTEM
    assert "FILLED SPACE" in v2._INSPECTOR


# ─── the stand-in law (2026-08-28, MaCnificent Hair Co) ──────────────

_DROP = ('<div class="sx-drop" data-sx-slot="hero_braids">A full head of '
         'medium box braids seen from behind, warm light</div>')


def test_stand_in_law_flags_visible_frames_and_spares_hidden_drops():
    """The first no-photo build shipped tinted 'slot-frame' boxes with an
    italic 'slot-note' describing the photograph that was not there."""
    bad = ('<section id="gallery"><div class="frame"><div class="slot-frame">'
           '<p class="slot-note">Braids from behind, clean parts.</p></div>'
           '</div>' + _DROP + '</section>')
    found = v2.check_stand_ins(bad)
    assert len(found) == 1 and "VISIBLE STAND-IN" in found[0]
    assert "'slot-frame'" in found[0] and "'slot-note'" in found[0]
    assert "typographic" in found[0]
    # the hidden drop slot alone is the contract, not a violation — and
    # a real <img> whose class happens to say "slot" is a real image
    good = ('<section id="gallery"><img class="slot-img" src="https://x/a.jpg" '
            'alt="braids">' + _DROP + '</section>')
    assert v2.check_stand_ins(good) == []


def test_stand_in_law_flags_a_caption_echo():
    """The shot direction inside the hidden drop, repeated as visible
    copy beside it, is a description of a photo that is not there."""
    echo = ('<section id="top">' + _DROP + '<p class="lead">A full head of '
            'medium box braids seen from behind in warm light.</p></section>')
    found = v2.check_stand_ins(echo)
    assert len(found) == 1 and "CAPTION ECHO" in found[0]
    # different copy beside the drop is fine
    fine = ('<section id="top">' + _DROP + '<p class="lead">Book your chair '
            'and leave with a finish you will keep looking at.</p></section>')
    assert v2.check_stand_ins(fine) == []


def test_stand_in_rule_rides_prompt_and_inspector():
    assert "NO VISIBLE STAND-INS" in v2._SYSTEM
    assert "typographic hero" in v2._SYSTEM
    assert "STAND-INS" in v2._INSPECTOR


def _law_passing_doc(endpoint: str, extra: str = "") -> str:
    return ("<!DOCTYPE html><html><head><title>Studio</title>"
            '<meta name="description" content="A braiding studio by hand">'
            '<meta property="og:title" content="Studio">'
            '<meta property="og:description" content="A braiding studio">'
            '<meta property="og:image" content="https://x/a.jpg">'
            "<style>body{margin:0}</style></head><body>"
            '<nav><a href="#top">Top</a></nav><main id="top"><h1>Braids worn '
            "like their own kind of magnificent.</h1>" + extra + "</main>"
            f'<form method="POST" action="{endpoint}"><input name="name">'
            '<input name="email"><button>Send</button></form>'
            "<footer>Studio</footer></body></html>")


def test_stand_ins_cost_a_repair_but_never_the_fallback(monkeypatch):
    """A stand-in is a quality defect, not an invented fact. It earns the
    surgical round; if the author will not let go of it, the page still
    ships — and the report says what is still on it."""
    endpoint = "https://api.example/contact/biz-1"
    standin = ('<div class="slot-frame"><p class="slot-note">Braids from '
               "behind, clean parts.</p></div>")
    calls = []

    def _fake_call(system, user, business_id, spend=None):
        calls.append(user)
        return _law_passing_doc(endpoint, standin)

    monkeypatch.setattr(v2, "_call", _fake_call)
    monkeypatch.setattr(v2, "assemble_real_data", lambda ctx, b: "BUSINESS: x")
    monkeypatch.setattr(v2, "contact_endpoint", lambda b: endpoint)
    monkeypatch.setattr(v2, "eyes_enabled", lambda: False)
    out = v2.run_builder_v2("SPEC", {}, "biz-1")
    assert out["html"] is not None                 # never the fallback
    assert len(calls) == 2 and "SURGICAL REPAIR" in calls[1]
    assert "VISIBLE STAND-IN" in calls[1]
    assert out["report"]["stand_ins"] and "slot-frame" in out["report"]["stand_ins"][0]
    assert not out["report"]["fallbacks"]
    # …and a clean page reports an empty list, no repair round
    calls.clear()
    monkeypatch.setattr(v2, "_call",
                        lambda s, u, b, spend=None: _law_passing_doc(endpoint))
    out2 = v2.run_builder_v2("SPEC", {}, "biz-1")
    assert out2["html"] and out2["report"]["stand_ins"] == []


# ─── the dead shop door (2026-08-28, MaCnificent Hair Co) ────────────

def test_store_off_is_said_out_loud_and_a_shop_on_the_page_is_a_violation(monkeypatch):
    """With no products the store line was simply ABSENT from the
    connected block, and the author invented "The shop — browse and
    order online" linking to /store on the site's own origin."""
    import offering_profiles
    monkeypatch.setattr(offering_profiles, "business_state", lambda b: {
        "booking_enabled": False, "booking_url": "",
        "store_url": "https://macnificent-hair-co.mysolutionist.app/store"})
    monkeypatch.setattr(v2, "_store_has_products", lambda ctx: False)
    block = v2.connected_systems_block("biz-1", {})
    assert "- STORE: OFF" in block and "/store" in block
    page = ('<html><body><nav><a href="#store">Shop</a></nav>'
            '<section id="store"><h2>The shop</h2><a href="https://'
            'macnificent-hair-co.mysolutionist.app/store">Visit the shop</a>'
            "</section></body></html>")
    found = v2.check_connected(page, block)
    assert len(found) == 1 and "DEAD DOOR" in found[0]
    assert "1 shop link(s)" in found[0] and "1 shop section(s)" in found[0]
    # a page that simply has no shop passes; a store that is ON keeps
    # the existing MISSING-door law and never trips the dead-door one
    assert v2.check_connected("<html><body>braids</body></html>", block) == []
    monkeypatch.setattr(v2, "_store_has_products", lambda ctx: True)
    on = v2.connected_systems_block("biz-1", {})
    assert "- STORE: ON" in on
    assert v2.check_connected(page, on) == []
    assert any("MISSING" in p for p in
               v2.check_connected("<html><body>braids</body></html>", on))


# ─── THE BUILDER LETS A PAGE FINISH (2026-08-29, the builder bench) ────

class _Usage:
    def __init__(self, i, o):
        self.input_tokens, self.output_tokens = i, o


class _Block:
    type = "text"
    def __init__(self, text):
        self.text = text


class _Msg:
    def __init__(self, text, stop="end_turn", i=1000, o=500):
        self.content = [_Block(text)]
        self.stop_reason = stop
        self.usage = _Usage(i, o)


class _FakeStream:
    """A scripted client: each messages.stream() call pops the next
    (text, stop_reason) and records the messages it was given."""
    def __init__(self, script):
        self.script = list(script)
        self.seen = []
        outer = self

        class _Messages:
            def stream(_s, **kw):
                outer.seen.append(kw)
                text, stop = outer.script.pop(0)

                class _Ctx:
                    def __enter__(self_):
                        return self_
                    def __exit__(self_, *a):
                        return False
                    text_stream = iter([text])
                    def get_final_message(self_):
                        return _Msg(text, stop, i=1000, o=len(text) // 4)
                return _Ctx()
        self.messages = _Messages()


def _ladder_passthrough(fn, model, task, business_id, max_tokens):
    return fn(model, max_tokens, 60.0), model


def test_call_streams_and_returns_the_text(monkeypatch):
    fake = _FakeStream([("<!DOCTYPE html><html>whole</html>", "end_turn")])
    monkeypatch.setattr(v2.llm_call, "sdk_client", lambda **k: fake)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    import model_ladder
    monkeypatch.setattr(model_ladder, "call_with_ladder", _ladder_passthrough)
    spend = v2.new_spend()
    out = v2._call("sys", "user", "biz", spend=spend)
    assert out == "<!DOCTYPE html><html>whole</html>"
    assert len(fake.seen) == 1 and fake.seen[0]["messages"][0]["role"] == "user"
    assert spend["calls"] == 1 and spend["output_tokens"] > 0 and spend["cost_cents"] > 0


def test_a_cut_page_is_continued_not_rerolled(monkeypatch):
    """Opus 5 and Fable 5 both came back at exactly max_tokens on the
    bench: cut before </html>. The cut text rides back as an assistant
    turn with a continue instruction — one more call, same model."""
    fake = _FakeStream([("<!DOCTYPE html><html><body>half", "max_tokens"),
                        (" the rest</body></html>", "end_turn")])
    monkeypatch.setattr(v2.llm_call, "sdk_client", lambda **k: fake)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    import model_ladder
    monkeypatch.setattr(model_ladder, "call_with_ladder", _ladder_passthrough)
    spend = v2.new_spend()
    out = v2._call("sys", "user", "biz", spend=spend)
    assert out == "<!DOCTYPE html><html><body>half the rest</body></html>"
    assert len(fake.seen) == 2
    turns = fake.seen[1]["messages"]
    assert [t["role"] for t in turns] == ["user", "assistant", "user"]
    assert turns[1]["content"] == "<!DOCTYPE html><html><body>half"
    assert "Continue EXACTLY" in turns[2]["content"]
    assert spend["calls"] == 2


def test_the_ceiling_and_the_budget_are_taller_than_the_cut(monkeypatch):
    monkeypatch.delenv("BUILDER_V2_MAX_TOKENS", raising=False)
    monkeypatch.delenv("BUILDER_V2_OUTPUT_BUDGET", raising=False)
    assert v2._max_tokens() >= 64000
    assert v2._output_budget() >= v2._max_tokens()
    import model_ladder
    assert not model_ladder.supports_sampling("claude-opus-5")


def test_budget_skips_the_repair_round_and_keeps_the_document(monkeypatch):
    """A stand-in on the first draft would normally cost a repair round.
    With the purse empty, the round is skipped, the document ships, and
    the report says so — no second charge for nothing."""
    endpoint = "https://api.example/contact/biz-1"
    standin = ('<div class="slot-frame"><p class="slot-note">Braids from '
               "behind, clean parts.</p></div>")
    calls = []

    def _fake_call(system, user, business_id, spend=None):
        calls.append(user)
        if spend is not None:
            spend["calls"] += 1
            spend["output_tokens"] += 10 ** 6      # one call empties the purse
        return _law_passing_doc(endpoint, standin)

    monkeypatch.setattr(v2, "_call", _fake_call)
    monkeypatch.setattr(v2, "assemble_real_data", lambda ctx, b: "BUSINESS: x")
    monkeypatch.setattr(v2, "contact_endpoint", lambda b: endpoint)
    monkeypatch.setattr(v2, "eyes_enabled", lambda: False)
    out = v2.run_builder_v2("SPEC", {}, "biz-1")
    assert out["html"] is not None
    assert len(calls) == 1                                # no repair call
    assert out["report"]["spend"]["skipped"] == ["repair"]
    assert any("budget reached" in f["detail"] for f in out["report"]["fallbacks"])
    assert out["report"]["stand_ins"]                     # still reported


# ─── THE EYES SAY WHY THEY CLOSED (2026-08-29, the proof build) ───────

def test_eyes_record_why_when_the_verdict_is_cut(monkeypatch):
    """On Opus 5 the inspector's reply hit its 1200-token cap mid-JSON and
    the eyes silently reported 'did not run'. The cap is taller now, and a
    None always carries its reason onto the report."""
    assert v2.INSPECTOR_MAX_TOKENS >= 4000
    assert v2.VISION_SETTLE_MS >= 1500
    monkeypatch.setattr(v2, "_screenshot_walk", lambda html: [("1440px top", b"jpeg")])
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")

    class _U:
        input_tokens, output_tokens = 10, 4000

    class _B:
        type = "text"
        text = '{"verdict":"repair","violations":[{"where":"hero","what":"cut mid'

    class _M:
        content = [_B()]
        stop_reason = "max_tokens"
        usage = _U()

    class _Client:
        class messages:
            @staticmethod
            def create(**kw):
                assert kw["max_tokens"] == v2.INSPECTOR_MAX_TOKENS
                return _M()

    monkeypatch.setattr(v2.llm_call, "sdk_client", lambda **k: _Client())
    import model_ladder
    monkeypatch.setattr(model_ladder, "call_with_ladder",
                        lambda fn, model, task, business_id, max_tokens: (fn(model, max_tokens, 60.0), model))
    why = {}
    assert v2.inspect_with_eyes("<html></html>", "SPEC", "biz", why=why) is None
    assert "max_tokens" in why["reason"] and "cap" in why["reason"]


def test_run_carries_the_eyes_reason_onto_the_report(monkeypatch):
    endpoint = "https://api.example/contact/biz-1"
    monkeypatch.setattr(v2, "_call", lambda s, u, b, spend=None: _law_passing_doc(endpoint))
    monkeypatch.setattr(v2, "assemble_real_data", lambda ctx, b: "BUSINESS: x")
    monkeypatch.setattr(v2, "contact_endpoint", lambda b: endpoint)
    monkeypatch.setattr(v2, "eyes_enabled", lambda: True)

    def _closed(doc, spec, biz, why=None):
        if why is not None:
            why["reason"] = "no screenshots (playwright unavailable or the render failed)"
        return None

    monkeypatch.setattr(v2, "inspect_with_eyes", _closed)
    out = v2.run_builder_v2("SPEC", {}, "biz-1")
    assert out["html"] and out["report"]["vision"]["ran"] is False
    assert "no screenshots" in out["report"]["vision"]["reason"]
