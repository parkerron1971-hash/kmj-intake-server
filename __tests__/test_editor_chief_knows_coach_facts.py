"""CHIEF KNOWS WHAT THE OWNER TOLD THE COACH (2026-11-10, the live test).

The owner gave the Design Coach the shop's address, and its hours were on file.
Minutes later, in the site editor, Chief asked: "If you give me the shop address
and hours, I can work them in." Those answers lived only in the design dossier,
which Chief never read. Now Chief's site lines carry them, and say which of them
the live page doesn't show yet.
"""
import chief_site_design as csd


def _cfg(truth=None, html=None):
    cfg = {"design_spec": {"text": "THE SPEC", "status": "draft"}}
    if truth is not None:
        cfg["discovery_dossier"] = {"truth": truth}
    if html is not None:
        cfg["canvas"] = {"html": html}
    return cfg


TRUTH = {"address": {"value": "1220 Main St, Suite B, right by the bus stop", "source": "asked"},
         "hours": {"value": "Tues thru Sat, 10 to 7", "source": "asked"},
         "phone": {"value": "(555) 201-3344", "source": "asked"}}


def test_chief_reads_what_the_owner_told_the_coach():
    lines = csd.site_design_lines({"slug": "x", "site_config": _cfg(TRUTH)}, {})
    told = next(ln for ln in lines if "told the Design Coach" in ln)
    assert '"1220 Main St, Suite B, right by the bus stop"' in told
    assert '"Tues thru Sat, 10 to 7"' in told
    assert '"(555) 201-3344"' in told
    assert "never ask for them again" in told
    # it sits right under where the design stands
    assert "Design blueprint" in lines[0] and "told the Design Coach" in lines[1]


def test_nothing_told_means_no_line():
    for cfg in (_cfg(), _cfg({}), _cfg({"address": {"value": "  "}})):
        lines = csd.site_design_lines({"slug": "x", "site_config": cfg}, {})
        assert not any("told the Design Coach" in ln for ln in lines)


def test_a_plain_string_fact_still_counts():
    lines = csd.told_coach_lines(_cfg({"address": "55 Maple Ave"}))
    assert lines == ['  What they told the Design Coach (their words; use them and never '
                     'ask for them again): address "55 Maple Ave".']


def test_the_live_page_is_checked_for_each_fact():
    html = "<footer><p>1220 Main Street, Suite B</p><p>Call 555-201-3344</p></footer>"
    lines = csd.told_coach_lines(_cfg(TRUTH, html))
    missing = next(ln for ln in lines if "Not on the live page yet" in ln)
    assert "hours" in missing and "address" not in missing and "phone" not in missing
    assert "never ask for them" in missing


def test_a_page_that_shows_everything_says_nothing_more():
    html = "<p>1220 Main St</p><p>555 201 3344</p><p>Open Tue to Sat</p>"
    assert len(csd.told_coach_lines(_cfg(TRUTH, html))) == 1


def test_no_page_yet_skips_the_page_check():
    assert len(csd.told_coach_lines(_cfg(TRUTH))) == 1


def test_a_long_answer_is_cut():
    long = {"address": {"value": "x " * 300}}
    told = csd.told_coach_lines(_cfg(long))[0]
    assert len(told) < 320


def test_a_hand_built_site_still_gets_nothing():
    cfg = {**_cfg(TRUTH), "html_source": "manual"}
    assert csd.site_design_lines({"slug": "x", "site_config": cfg}, {}) == []


def test_it_reaches_chiefs_site_block():
    import chief_of_staff
    ctx = {"site": {"slug": "c13-test-shop", "status": "published", "site_config": _cfg(TRUTH)},
           "business": {"settings": {}}}
    block = chief_of_staff._format_site_info(ctx)
    assert "1220 Main St, Suite B" in block and "Tues thru Sat, 10 to 7" in block
