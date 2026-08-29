"""
test_wider_shelf.py — the wider shelf (2026-08-29): five languages, five
frameworks, three hero shapes, two motions — and the rubrics that reach
them on evidence.
"""
import design_coach as dc
import design_languages as dl
import page_frameworks as pf


NEW_LANGS = ("broadsheet", "signal", "atelier", "neon", "hearth")


def test_every_new_language_is_a_complete_entry_the_brain_can_argue_for():
    assert len(dl.LANGUAGES) == 8
    sheets = dl.character_sheets()
    for k in NEW_LANGS:
        e = dl.LANGUAGES[k]
        for field in ("label", "source", "believes", "sings", "fails", "brief",
                      "pairing_hint", "standard", "css"):
            assert e.get(field), f"{k}.{field}"
        assert e["brief"].startswith(e["label"].upper() + " LANGUAGE")
        assert f".sx-lang-{k} " in e["css"]              # scoped floor
        assert "!important" not in e["css"].split(".sxm-cta")[0]  # only the forced-ink cta rules
        assert e["label"] in sheets                      # the brain is told
        assert dl.validate_choice({"choice": k, "because": "x"})[0] == k
    import brand_dna
    for k in NEW_LANGS:
        assert dl.LANGUAGES[k]["standard"] in brand_dna.FONT_PAIRINGS


def _ctx(btype, photos=0, offerings=0, testimonials=0, products=0, **prefs):
    return {"business": {"type": btype}, "site_prefs": prefs,
            "gallery": [{"url": "u"}] * photos, "offerings": [{}] * offerings,
            "testimonials": [{}] * testimonials, "products": [{}] * products}


def test_language_rubric_reaches_every_new_language_on_evidence():
    assert dl.rubric_select(_ctx("barber", photos=2, boldness="bold"))[0] == "neon"
    assert dl.rubric_select(_ctx("lash_artist", photos=6, boldness="calm"))[0] == "atelier"
    assert dl.rubric_select(_ctx("nonprofit", photos=3))[0] == "hearth"
    assert dl.rubric_select(_ctx("agency", photos=1, type_personality="modern"))[0] == "signal"
    assert dl.rubric_select(_ctx("consultant", photos=1, offerings=5, type_personality="editorial"))[0] == "broadsheet"
    # the old evidence still lands where it did
    assert dl.rubric_select(_ctx("consultant", photos=0, boldness="loud"))[0] == "mural"
    assert dl.rubric_select(_ctx("design_studio", photos=5))[0] == "monograph"
    assert dl.rubric_select(_ctx("law_firm", photos=1, type_personality="classic"))[0] == "ledger"
    # a type string alone never outvotes conviction (2026-07-22)
    assert dl.rubric_select(_ctx("nonprofit", photos=0, boldness="loud"))[0] == "mural"


def test_every_new_framework_orders_real_modules_once_and_ends_on_contact():
    import site_modules
    assert len(pf.FRAMEWORKS) == 10
    for k in ("menu_first", "gathering", "proof_first", "manifesto", "lookbook"):
        fw = pf.FRAMEWORKS[k]
        order = fw["order"]
        assert order[0] == "hero" and order[-1] == "contact"
        assert len(order) == len(set(order))
        assert all(m in site_modules.MODULES for m in order), k
        assert fw["about_variant"] in ("portrait", "narrative", "pull_quote")


def test_framework_rubric_reaches_every_new_skeleton_on_evidence():
    pick = lambda **kw: pf.select_framework(_ctx(**kw), None)[0]
    assert pick(btype="creative", products=3, photos=5) == "lookbook"
    assert pick(btype="creative", products=3, photos=1) == "storefront"
    assert pick(btype="ministry") == "gathering"
    assert pick(btype="barbershop", offerings=5, photos=3) == "menu_first"
    assert pick(btype="coach", testimonials=4, photos=1) == "proof_first"
    assert pick(btype="tutor", photos=0, offerings=1) == "manifesto"
    assert pick(btype="consultant", photos=0, offerings=1) == "portrait_consultant"   # the portrait family keeps its skeleton
    assert pick(btype="photographer", photos=6) == "gallery_studio"
    assert pick(btype="florist", photos=2, offerings=3) == "story_arc"


def test_the_coach_offers_the_new_cards_and_only_real_keys():
    out = dc.parse_turn('{"reply": "Which feels like you?", "stage": "taste", "done": false,'
                        ' "gallery": {"kind": "looks", "options": ["hearth", "neon", "nope"]}}')
    assert out["gallery"] == {"kind": "looks", "options": ["hearth", "neon"]}
    out = dc.parse_turn('{"reply": "Which shape?", "stage": "taste", "done": false,'
                        ' "gallery": {"kind": "layouts", "options": ["monument", "letter", "corridor"]}}')
    assert out["gallery"]["options"] == ["monument", "letter", "corridor"]
    out = dc.parse_turn('{"reply": "How should it move?", "stage": "taste", "done": false,'
                        ' "gallery": {"kind": "motion", "options": ["marquee", "unfold"]}}')
    assert out["gallery"]["options"] == ["marquee", "unfold"]
    for word in ("broadsheet", "atelier", "monument", "corridor", "letter", "marquee", "unfold"):
        assert word in dc.SYSTEM if hasattr(dc, "SYSTEM") else word in dc._SYSTEM
