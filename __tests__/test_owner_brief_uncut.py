"""The owner's words reach the pipeline uncut (2026-09-04, the barbershop
bench). A practitioner's typed prompt was sliced to 600 characters at
three seams; the last sentence ("Price list on the site, people always
ask.") never reached the Director, and the builder never saw the prompt
at all."""
import canvas_brief
import builder_v2


LONG = (
    "I need a website for my barbershop. Marrow & Steel Barber Co in Lakewood. "
    "It's me and one other barber, two chairs, walk-ins and appointments. We do "
    "classic cuts, skin fades, beard work, and hot towel shaves. I've been cutting "
    "14 years, opened this shop in 2021. I want it to feel like a real shop, not a "
    "salon. Dark, clean, a little old-school but not a costume. Guys should be able "
    "to book from the site. I don't want it to look like every other barbershop "
    "website with the crossed razors and the barber pole. Show the work. We're good "
    "at fades and beard lineups and I want that to be obvious. Price list on the "
    "site, people always ask.")
LAST = "Price list on the site, people always ask."


def _ctx():
    return {"business": {"id": "b", "name": "Marrow & Steel", "type": "barbershop"},
            "owner_brief": LONG, "offerings": [], "testimonials": [], "gallery": [],
            "contact": {}, "site": {"site_config": {}}, "dna": {}, "bundle": {}}


def test_the_prompt_is_longer_than_the_old_cap():
    assert len(LONG) > 600, "the fixture must exceed the old 600-char slice"
    assert canvas_brief.OWNER_BRIEF_MAX_CHARS >= len(LONG)


def test_the_director_reads_the_last_sentence():
    brief = canvas_brief.compile_canvas_brief(_ctx(), None, [])
    assert LAST in brief


def test_the_builder_reads_the_owners_words_too():
    data = builder_v2.assemble_real_data(_ctx(), "b")
    assert "THE OWNER'S WORDS" in data
    assert LAST in data
    assert "cutting 14 years" in data


def test_site_composer_shares_the_cap():
    import site_composer
    assert site_composer._owner_brief_cap() == canvas_brief.OWNER_BRIEF_MAX_CHARS
