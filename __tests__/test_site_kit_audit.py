"""THE KIT AUDIT (2026-11-22, Kevin: "fix any issue with kits that's causing
bugs ... people would need to edit the design. can that happen with no
issues?").

28 kit pages were assembled (every layout; a full church, one with no photos,
one with almost no data, one with a long name) and looked at on a phone and a
computer. What that found, pinned here:

  - an Edit Mode edit to the headline wiped the photos set in it, an edit to a
    menu item removed its link, a times tile collapsed into one line;
  - the sample church's site said "Saturday 9am, Sunday worship" and showed one
    of its four gatherings;
  - on a phone the ministries ran off the right edge of the screen;
  - a long church name ran under the header button;
  - "Plan a visit" sat twice side by side, and a button inside the visit
    section pointed at the visit section.
"""
import copy
import json
import re
from pathlib import Path
from unittest import mock

import site_kit as kit
import site_kit_church as church
from agents.override_system import override_resolver as resolver

ROOT = Path(__file__).resolve().parent.parent
CFG = json.loads((ROOT / "sample_church" / "site_config.json").read_text(encoding="utf-8"))
ENDPOINT = "https://kmj-intake-server-production.up.railway.app/sites/b-audit/contact-submit"


def _fx():
    facts = CFG["facts"]
    gallery = [{"url": f"https://example.org/{p['name']}.jpg", "alt": p.get("alt") or ""} for p in CFG["photos"]]
    return {"business": {"name": "Grace Street Fellowship", "type": "church"}, "contact": facts["contact"],
            "gallery": gallery, "events": facts["events"], "ministries": facts["ministries"], "testimonials": [],
            "discovery_dossier": {"identity": {"team": facts["team"]}}, "form_endpoint": ENDPOINT}


def _words(**over):
    w = copy.deepcopy(CFG["words"])
    w.update(over)
    return w


def _poster_words():
    fx = _fx()
    return _words(hero={"lines": ["Come as", "you are.", "Stay for the family."], "accent_word": "family",
                        "inset_photos": [fx["gallery"][0]["url"], fx["gallery"][1]["url"]],
                        "secondary": "Plan a visit", "secondary_target": "visit"})


def _keyed(html):
    """{key: (tag, inner)} for every element Edit Mode can change."""
    return {m.group(3): (m.group(2).lower(), m.group(4)) for m in resolver._OVERRIDE_TARGET_RE.finditer(html)}


def _built(layout, words):
    ctx_spec = f"0. THE CONCEPT\nLAYOUT: {layout} - a church page\n"
    ctx = {"business": {"id": "b-audit", "name": "Grace Street Fellowship", "type": "church"},
           "design_spec_text": ctx_spec, "contact": {**CFG["facts"]["contact"], "submit_url": ENDPOINT},
           "gallery": _fx()["gallery"], "site": {"site_config": {"discovery_dossier": _fx()["discovery_dossier"]}},
           "offerings": [], "testimonials": [], "booking": {"enabled": False}}
    with mock.patch.dict("os.environ", {"SITE_KIT": "on"}):
        with mock.patch.object(kit, "write_words", return_value=words):
            with mock.patch.object(kit, "fx_from_ctx", return_value=_fx()):
                return kit.build(ctx, "b-audit")


# ─── editing ─────────────────────────────────────────────────────────

def test_no_edit_key_sits_on_an_element_that_wraps_other_markup():
    for layout in ("poster", "bulletin", "magazine", "leader"):
        html, report = _built(layout, _poster_words())
        assert html, report
        keyed = _keyed(html)
        assert len(keyed) > 10
        for key, (tag, inner) in keyed.items():
            rest = re.sub(r'</?em>|<span class="k-(?:acc|under)">|</span>', "", inner)
            assert "<" not in rest, f"{layout}: an edit to {key} ({tag}) would flatten {inner[:80]!r}"


def test_an_edit_to_the_poster_headline_keeps_its_photos():
    html, _ = _built("poster", _poster_words())
    keyed = _keyed(html)
    key = next(k for k, (tag, inner) in keyed.items() if tag == "bdi" and "Come as" in inner)
    edited, applied = resolver._apply_text_overrides(html, {key: "Walk in as"})
    assert applied == [key]
    h1 = re.search(r"<h1[^>]*>.*?</h1>", edited, re.S).group(0)
    assert "Walk in as" in h1 and h1.count("<img") == 2 and "<em>family</em>" in h1


def test_every_line_of_a_headline_can_be_edited_on_its_own():
    html, _ = _built("bulletin", _words())
    h1 = re.search(r'<h1 class="k-h1">.*?</h1>', html, re.S).group(0)
    assert "data-override-target" not in h1.split(">", 1)[0]          # the h1 itself is not the target
    assert len(re.findall(r"<bdi data-override-target=", h1)) == 2
    assert "<br>" in h1


def test_a_menu_link_and_a_times_tile_cannot_be_edited_away():
    html, _ = _built("bulletin", _words())
    assert not re.search(r"<li data-override-target=[^>]*>\s*<a ", html)
    assert not re.search(r'<li class="sxo-times-item"[^>]*data-override-target', html)
    assert re.search(r'<h2 class="k-h2" data-override-target="v2/auto_\d+">When we gather</h2>', html)


def test_a_page_the_kit_assembles_outside_a_build_carries_no_marks():
    page = kit.assemble(_fx(), _poster_words(), None, "poster")
    assert "data-kit-edit" not in page and "data-override-target" not in page


# ─── the sample church's own site ────────────────────────────────────

def test_the_sample_church_shows_all_four_gatherings_on_their_own_days():
    page = kit.assemble(_fx(), _words(), None, "bulletin")
    tiles = re.findall(r'<li class="sxo-times-item" data-day="(\d)" data-time="([\d:]+)">'
                       r'<span class="sxo-label">(\w+)</span>', page)
    assert tiles == [("0", "09:00", "Sunday"), ("0", "11:00", "Sunday"),
                     ("3", "19:00", "Wednesday"), ("5", "19:00", "Friday")]


def test_a_label_that_names_its_day_is_believed_over_the_number():
    records = kit.fact_records(_fx())
    rows = kit.clean_gatherings([{"day": 6, "time": "09:00", "label": "Sunday worship"}], records)
    assert [(g["day_label"], g["time_label"]) for g in rows] == [("Sunday", "9am")]


# ─── what a visitor sees ─────────────────────────────────────────────

def test_the_same_words_are_never_a_button_and_a_link_side_by_side():
    for layout in ("poster", "bulletin", "magazine"):
        page = kit.assemble(_fx(), _poster_words(), None, layout)
        for group in re.findall(r'<div class="k-ctas">(.*?)</div>', page, re.S):
            labels = [re.sub(r"<[^>]+>|&\w+;|\s+$", "", a).strip().lower()
                      for a in re.findall(r"<a\b[^>]*>(.*?)</a>", group, re.S)]
            assert len(labels) == len(set(labels)), (layout, labels)


def test_a_different_second_link_is_kept():
    words = _poster_words()
    words["hero"]["secondary"] = "See the times"
    words["hero"]["secondary_target"] = "times"
    assert "See the times &darr;" in kit.assemble(_fx(), words, None, "poster")


def test_no_button_in_the_visit_section_points_at_the_visit_section():
    page = kit.assemble(_fx(), _words(), None, "bulletin")
    visit = re.search(r'<section class="k-section k-visit" id="visit">.*?</section>', page, re.S).group(0)
    assert 'class="k-btn" href="#visit"' not in visit
    assert "Directions" in visit                                       # the way there stays


def test_a_long_church_name_takes_two_short_lines_in_the_header():
    words = _words(wordmark={"main": "Greater Mount Zion Missionary Baptist Church", "sub": "of Riverton"})
    page = kit.assemble(_fx(), words, None, "bulletin")
    assert '<a class="k-mark k-mark-long" href="#top">' in page
    assert ".k-nav .k-mark-long b{white-space:normal" in page
    assert '<a class="k-mark" href="#top">' in kit.assemble(_fx(), _words(), None, "bulletin")


def test_a_ministry_cannot_grow_wider_than_a_phone():
    assert "grid-template-columns:minmax(0,1fr)" in re.search(r"\.k-min\{[^}]*\}", church.CSS).group(0)
    assert ".k-min .k-meta{white-space:normal" in church.CSS


def test_a_long_poster_line_may_wrap_and_a_short_one_stays_whole():
    words = _poster_words()
    words["hero"]["lines"] = ["Everybody is somebody here", "Come as"]
    page = kit.assemble(_fx(), words, None, "poster")
    assert '<span class="sxo-pw-line is-wrap"><bdi>Everybody is somebody here</bdi>' in page
    assert '<span class="sxo-pw-line"><bdi>Come as</bdi>' in page
    assert ".k-hero-poster .sxo-pw-line.is-wrap{white-space:normal" in page
