"""What a site of this kind must decide (2026-09-04, the barbershop
bench). The Director carried one density skeleton for every business;
the render that won carried the decisions a walk-in shop needs."""
import site_vertical_features as svf
import spec_author


def test_families_come_from_the_types_own_words_first():
    assert svf.family_for("barbershop") == "walk_in"
    assert svf.family_for("Nail Salon") == "walk_in"
    assert svf.family_for("tattoo studio") == "walk_in"
    assert svf.family_for("life coach") == "practice"
    assert svf.family_for("fitness trainer") == "practice"
    assert svf.family_for("photographer") == "creative"
    assert svf.family_for("plumber") == "trade"
    assert svf.family_for("church") == "gathering"
    assert svf.family_for("online store") == "store"
    assert svf.family_for("saas") == "product"


def test_registry_canonicals_fill_in_when_words_miss():
    assert svf.family_for("consultant") == "practice"
    assert svf.family_for("personal_services") == "walk_in"
    assert svf.family_for("ministry") == "gathering"
    assert svf.family_for("") == "generic"
    assert svf.family_for("zorblax") == "generic"


def test_the_walk_in_block_carries_the_bench_lessons():
    block = svf.block_for("barbershop")
    assert "MUST DECIDE" in block and "barbershop" in block
    for phrase in ("TODAY'S HOURS", "DURATION BESIDE EVERY PRICE",
                   "BOOK WITH A NAMED PERSON", "MOBILE ACTION BAR", "DIRECTIONS"):
        assert phrase in block, phrase
    assert "never invent" in block


def test_every_family_has_a_list_and_no_line_invents():
    for fam, items in svf.FEATURES.items():
        assert items, fam
        assert fam in svf.FAMILY_LABEL


def test_the_director_prompt_carries_the_block():
    user = spec_author.build_user_prompt("DOSSIER", [], vertical=svf.block_for("barbershop"))
    assert "MUST DECIDE" in user
    assert user.index("MUST DECIDE") < user.index("THE CURRENT SECTION PLAN")
    # and nothing changes for callers that pass none
    assert "MUST DECIDE" not in spec_author.build_user_prompt("DOSSIER", [])
