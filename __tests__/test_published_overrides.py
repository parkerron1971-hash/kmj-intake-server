"""
test_published_overrides.py — the owner gets to edit what goes out.

KEVIN, 2026-08-10, twice: he wanted to EDIT the copy in "In your name".
The first answer was to fix the derivation (#508 — his signature printed
the platform subdomain while his verified domain sat unread). That was
right for a WRONG derivation. It is not an answer for a derivation that
is merely not what he wants, and substituting it for what he asked for
was not mine to do.

Derived by default, overridable per field, always reversible.
"""
import brand_engine


def _bundle(monkeypatch, brand_kit, site=None):
    def fake_one(table, col, val):
        if table == "businesses":
            return {"id": "biz-1", "name": "KMJ Creative Solutions",
                    "owner_id": "o1", "settings": {"brand_kit": brand_kit}}
        if table == "business_sites":
            return site or {"slug": "kmj-creative-solutions", "site_config": {}}
        return {}
    monkeypatch.setattr(brand_engine, "_safe_get_one", fake_one)
    return brand_engine.get_bundle("biz-1", use_cache=False)


def test_no_override_means_pure_derivation(monkeypatch):
    b = _bundle(monkeypatch, {})
    assert b["published_overrides"]["fields"] == []
    assert "mysolutionist.app" in (b["footer"]["site_url"] or "")


def test_an_override_wins(monkeypatch):
    b = _bundle(monkeypatch, {"published_overrides": {
        "site_url": "https://kmjcreate.com"}})
    assert b["footer"]["site_url"] == "https://kmjcreate.com"
    assert "site_url" in b["published_overrides"]["fields"]


def test_one_business_has_one_address(monkeypatch):
    """The signature and the footer must never disagree about where the
    practitioner lives, so a site_url override moves both."""
    b = _bundle(monkeypatch, {"published_overrides": {
        "site_url": "https://kmjcreate.com"}})
    assert b["signature_block"]["site_url"] == "https://kmjcreate.com"
    assert b["footer"]["site_url"] == "https://kmjcreate.com"


def test_the_derived_value_is_kept_so_reset_is_possible(monkeypatch):
    """Without this an override is a one-way door — the UI could not
    show what it WOULD say, so the owner could never get back."""
    b = _bundle(monkeypatch, {"published_overrides": {
        "site_url": "https://kmjcreate.com"}})
    derived = b["published_overrides"]["derived"]["site_url"]
    assert "mysolutionist.app" in derived


def test_signature_fields_override_independently(monkeypatch):
    b = _bundle(monkeypatch, {"published_overrides": {
        "signature_title": "Founder & Chief Solutionist"}})
    assert b["signature_block"]["title"] == "Founder & Chief Solutionist"
    # untouched fields stay derived
    assert b["signature_block"]["business_name"] == "KMJ Creative Solutions"
    assert b["published_overrides"]["fields"] == ["signature_title"]


# ─── the save path ───────────────────────────────────────────────────

def test_only_whitelisted_fields_survive_a_save():
    out = brand_engine._normalize_brand_kit({"published_overrides": {
        "site_url": "https://kmjcreate.com",
        "required_disclaimers": "no thanks",   # not overridable
        "evil": "x"}})
    assert set(out["published_overrides"]) == {"site_url"}


def test_an_empty_string_resets_rather_than_storing_a_blank():
    """This is how 'reset to derived' works from the UI without a second
    endpoint — and it is the guard that matters: a blank legal_footer
    stored as an override would strip a practitioner's disclaimers from
    every contract they send."""
    out = brand_engine._normalize_brand_kit({"published_overrides": {
        "legal_footer": "   ", "site_url": "https://kmjcreate.com"}})
    assert set(out["published_overrides"]) == {"site_url"}

    empty = brand_engine._normalize_brand_kit({"published_overrides": {
        "legal_footer": ""}})
    assert "published_overrides" not in empty


def test_values_are_trimmed_and_capped():
    out = brand_engine._normalize_brand_kit({"published_overrides": {
        "copyright_line": "  spaced  ", "legal_footer": "x" * 900}})
    assert out["published_overrides"]["copyright_line"] == "spaced"
    assert len(out["published_overrides"]["legal_footer"]) == 400


def test_junk_shapes_do_not_crash_or_persist():
    for junk in ("nope", [], 7, None):
        out = brand_engine._normalize_brand_kit({"published_overrides": junk})
        assert "published_overrides" not in out


def test_normalising_twice_is_stable():
    once = brand_engine._normalize_brand_kit({"published_overrides": {
        "site_url": " https://kmjcreate.com "}})
    twice = brand_engine._normalize_brand_kit(dict(once))
    assert once["published_overrides"] == twice["published_overrides"]
