"""
test_restore_swaps_the_verdict.py — a page and its verdict travel together.

THE LIVE FAILURE THIS ENCODES (2026-08-09):

  01:15  build A ships. vision_verdict composite 30 stored.
  01:56  Kevin restores the previous canvas page. The PAGE swaps;
         vision_verdict does NOT — it is absent from _RESTORE_KEYS, so
         build A's 30 stays behind on a page that no longer exists.
  02:13  build B scores 25 and PASSES the bar (passes_gate: true,
         impact 7, smell 2, broken n). The never-downgrade ratchet
         compares it against the orphaned 30, calls it a regression, and
         destroys it. $4.73, 26.5 minutes, nothing shipped.

The ship-gate error even says "vision verdict failed", which is wrong on
its own terms — the raise fires on `_is_regression`, never on
`passes_gate`. So the one honest signal (the verdict) was stale and the
error explaining it was misleading.
"""
import site_composer


def _cfg_with(**over):
    cfg = {
        "page_spec": {"sections": ["hero"]},
        "generated_html": "<main>NEW</main>",
        "html_source": "module-composer",
        "vision_verdict": {"first_viewport_impact": 8, "balance": 9,
                           "motif_visibility": 6, "rhythm": 8,
                           "template_smell": 1, "passes_gate": True},
        "canvas_report": {"fallbacks": []},
    }
    cfg.update(over)
    return cfg


class _FakeSB:
    def __init__(self, cfg, html):
        self.row = {"id": "site-1", "site_config": cfg, "html_content": html}
        self.patched = None

    def get(self, path):
        return [self.row]

    def patch(self, path, body):
        self.patched = body
        return [{"id": "site-1"}]


def _wire(monkeypatch, fake):
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_get_as_service", fake.get)
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", fake.patch)


def test_the_verdict_travels_with_its_page(monkeypatch):
    """The whole fix in one assertion: after a restore, the live verdict
    is the RESTORED page's verdict, not the discarded one's."""
    old_verdict = {"first_viewport_impact": 7, "balance": 7,
                   "motif_visibility": 5, "rhythm": 7,
                   "template_smell": 2, "passes_gate": True}
    cfg = _cfg_with(previous_compose={
        "saved_at": "2026-08-09T01:56:00Z",
        "html_content": "<main>OLD CANVAS</main>",
        "keys": {"generated_html": "<main>OLD CANVAS</main>",
                 "canvas": {"html": "<section>canvas</section>"},
                 "html_source": "canvas",
                 "vision_verdict": old_verdict},
    })
    fake = _FakeSB(cfg, "<main>NEW</main>")
    _wire(monkeypatch, fake)

    out = site_composer.restore_previous_compose("biz-1")
    assert out["ok"]
    new_cfg = fake.patched["site_config"]

    # The restored page brought its own verdict with it.
    assert new_cfg["vision_verdict"] == old_verdict
    assert new_cfg["html_source"] == "canvas"
    assert fake.patched["html_content"] == "<main>OLD CANVAS</main>"

    # And the page we swapped away kept ITS verdict in the slot, so the
    # swap stays symmetric — restoring again returns both together.
    banked = new_cfg["previous_compose"]["keys"]
    assert banked["vision_verdict"]["balance"] == 9
    assert banked["html_source"] == "module-composer"


def test_the_ratchet_can_no_longer_defend_a_ghost(monkeypatch):
    """Stated as the thing that actually went wrong: the score left
    behind must not outlive the page that earned it."""
    cfg = _cfg_with(previous_compose={
        "saved_at": "2026-08-09T01:56:00Z",
        "html_content": "<main>OLD</main>",
        "keys": {"generated_html": "<main>OLD</main>",
                 "vision_verdict": {"balance": 7, "passes_gate": True}},
    })
    fake = _FakeSB(cfg, "<main>NEW</main>")
    _wire(monkeypatch, fake)
    site_composer.restore_previous_compose("biz-1")
    live = fake.patched["site_config"]["vision_verdict"]
    assert live["balance"] == 7, "the discarded build's 9 is still defending"


def test_a_legacy_snapshot_drops_the_stale_verdict_rather_than_keeping_it(monkeypatch):
    """A slot banked BEFORE vision_verdict joined the list carries no
    verdict. Dropping it is correct — the ratchet then has nothing to
    compare and the next build ships, which beats defending a ghost."""
    cfg = _cfg_with(previous_compose={
        "saved_at": "2026-08-09T01:56:00Z",
        "html_content": "<main>OLD CANVAS</main>",
        "keys": {"generated_html": "<main>OLD CANVAS</main>",
                 "canvas": {"html": "<section>c</section>"}},   # no verdict
    })
    fake = _FakeSB(cfg, "<main>NEW</main>")
    _wire(monkeypatch, fake)
    site_composer.restore_previous_compose("biz-1")
    new_cfg = fake.patched["site_config"]
    assert "vision_verdict" not in new_cfg


def test_html_source_is_derived_not_dropped_on_a_legacy_snapshot(monkeypatch):
    """html_source ROUTES rendering — public_site._use_smart_sites returns
    early on "module-composer". Losing it can let the retired Smart Sites
    engine shadow the page, so it is healed rather than dropped."""
    cfg = _cfg_with(use_smart_sites=True, previous_compose={
        "saved_at": "2026-08-09T01:56:00Z",
        "html_content": "<main>OLD CANVAS</main>",
        "keys": {"generated_html": "<main>OLD CANVAS</main>",
                 "canvas": {"html": "<section>c</section>"}},   # no html_source
    })
    fake = _FakeSB(cfg, "<main>NEW</main>")
    _wire(monkeypatch, fake)
    site_composer.restore_previous_compose("biz-1")
    new_cfg = fake.patched["site_config"]
    assert new_cfg["html_source"] == "canvas", \
        "a restored canvas page must not fall through to Smart Sites"

    # No canvas in the snapshot → the module path, still not a fall-through.
    cfg2 = _cfg_with(use_smart_sites=True, previous_compose={
        "saved_at": "2026-08-09T01:56:00Z",
        "html_content": "<main>OLD</main>",
        "keys": {"generated_html": "<main>OLD</main>"},
    })
    fake2 = _FakeSB(cfg2, "<main>NEW</main>")
    _wire(monkeypatch, fake2)
    site_composer.restore_previous_compose("biz-1")
    assert fake2.patched["site_config"]["html_source"] == "module-composer"


def test_restore_stays_symmetric():
    """The documented contract: restoring twice returns you to where you
    started. Pinned because the key list just grew."""
    for k in ("vision_verdict", "vision_verdict_prior",
              "invention_verification", "html_source"):
        assert k in site_composer._RESTORE_KEYS, k
