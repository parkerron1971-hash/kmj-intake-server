"""Durations reach the authors (2026-09-04, the barbershop bench). The
offerings table carries duration_min; the module renderer printed it;
the data block the Director and builder_v2 read did not."""
import atelier
import builder_v2


def _ctx():
    return {"business": {"id": "b", "name": "Marrow & Steel", "type": "barbershop"},
            "offerings": [
                {"name": "Skin Fade", "price": 45, "duration_min": 45,
                 "description": "Down to skin."},
                {"name": "Beard Trim", "price": 25, "duration_min": None,
                 "description": "Shaped."},
                {"name": "Legacy Row", "price": 30, "duration_minutes": "20",
                 "description": "Old key."},
            ],
            "testimonials": [], "gallery": [], "contact": {},
            "site": {"site_config": {}}, "dna": {}, "bundle": {}}


def test_duration_rides_the_section_data():
    rows = atelier._section_data("offerings", {}, _ctx())["offerings"]
    assert rows[0]["duration_min"] == 45
    assert "duration_min" not in rows[1], "a missing duration is not on file, never null"
    assert rows[2]["duration_min"] == 20, "the older key still counts"


def test_the_builder_reads_the_duration():
    data = builder_v2.assemble_real_data(_ctx(), "b")
    assert '"duration_min": 45' in data


def test_the_director_inventory_reads_the_duration():
    import spec_author
    plan = [{"module": "offerings", "variant": "menu", "content": {}}]
    inv = spec_author._inventory_digest(_ctx(), plan)
    assert '"duration_min": 45' in inv


def test_both_authors_are_told_to_render_it():
    import spec_author
    assert "duration_min" in spec_author._SYSTEM
    assert "duration_min" in builder_v2._SYSTEM
