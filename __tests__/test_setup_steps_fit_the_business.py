# __tests__/test_setup_steps_fit_the_business.py
#
# Setup steps fit the business (2026-09-26).
#
# Four gaps, each pinned here so it cannot quietly come back:
#
#   * "Bring your client list over" ticked on ONE typed name. Done now
#     means an import ran, or the business holds a real list
#     (bta.REAL_CLIENT_LIST_MIN), counted the way maturity_engine counts.
#   * The import step asked for one name. Its how-line now leads with the
#     whole list and walks the export for the tool the practitioner said
#     their clients live in (settings.client_sources, or a list-holding
#     tool the Business Session heard).
#   * Setup ignored the type of business: a ministry was asked what it
#     charges, the therapist's and lawyer's first sendable thing (an
#     intake form) had no step, and the financial educator's booking-link
#     goal needed hours it was never offered.
#   * The archetype lens looked up the raw type, so an alias ("church")
#     got the generic lens.
#
# And the contract other open work depends on: resolve_plugins keeps
# every key and type it returned before; it only gains fields.

import pathlib
import sys

import pytest

_here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))

import business_track_actions as bta  # noqa: E402
import business_track_router as btr  # noqa: E402
import vertical_registry  # noqa: E402


# ─── a tiny PostgREST stand-in ───────────────────────────────────────

class FakeDB:
    """Answers the handful of reads the probes and resolve_plugins make.
    Anything it does not know about reads as empty, the same way a
    missing row does."""

    def __init__(self, *, contacts=0, imported=False, track=None,
                 forms=None, biz_row=None):
        self.contacts = contacts
        self.imported = imported
        self.track = track
        self.forms = forms or []
        self.biz_row = biz_row
        self.paths = []
        self.patches = []

    def get(self, path):
        self.paths.append(path)
        if path.startswith("/contacts?"):
            if "source=like." in path:
                return [{"id": "imp"}] if self.imported else []
            limit = int(path.rsplit("limit=", 1)[1].split("&")[0]) if "limit=" in path else 1000
            return [{"id": f"c{i}"} for i in range(min(self.contacts, limit))]
        if path.startswith("/business_tracks?"):
            return [self.track] if self.track else []
        if path.startswith("/intake_forms?"):
            return self.forms
        if path.startswith("/businesses?") and self.biz_row is not None:
            return [self.biz_row]
        return []

    def patch(self, path, body):
        self.patches.append((path, body))
        return [body]


@pytest.fixture
def db(monkeypatch):
    fake = FakeDB()
    monkeypatch.setattr(btr.sb_clients, "sb_get_as_service", fake.get)
    monkeypatch.setattr(btr.sb_clients, "sb_patch_as_service", fake.patch)
    return fake


def _biz(btype="personal_services", settings=None):
    return {"id": "b1", "type": btype, "settings": settings or {},
            "stripe_account_id": None}


# ═══ 1. the done threshold ═══════════════════════════════════════════

def test_one_typed_name_is_not_the_client_list(db):
    db.contacts = 1
    assert btr._done_import_contacts(_biz()) is False


def test_the_list_is_in_at_the_threshold_and_not_one_before(db):
    db.contacts = bta.REAL_CLIENT_LIST_MIN - 1
    assert btr._done_import_contacts(_biz()) is False
    db.contacts = bta.REAL_CLIENT_LIST_MIN
    assert btr._done_import_contacts(_biz()) is True


def test_any_import_counts_however_small(db):
    # An import ran: the list came over, even if the list is short.
    db.contacts, db.imported = 2, True
    assert btr._done_import_contacts(_biz()) is True


def test_the_threshold_is_ten_and_reasoned():
    # Changing it is a decision about what "the list came over" means;
    # the reasoning lives next to the constant.
    assert bta.REAL_CLIENT_LIST_MIN == 10


def test_the_count_reads_the_rows_maturity_engine_counts(db):
    # maturity_engine's contact_count is every contacts row for the
    # business — no source or status filter. The count here must read
    # the same rows, or the two disagree about how many people exist.
    import maturity_engine
    db.contacts = 3
    btr._done_import_contacts(_biz())
    count_paths = [p for p in db.paths if p.startswith("/contacts?") and "source=" not in p]
    assert count_paths, "the probe never counted"
    for p in count_paths:
        assert "status=" not in p and "source=" not in p
    seen = []
    orig = maturity_engine.sb_clients.sb_get_as_service
    try:
        maturity_engine.sb_clients.sb_get_as_service = lambda path: seen.append(path) or []
        maturity_engine.collect_signals("b1")
    finally:
        maturity_engine.sb_clients.sb_get_as_service = orig
    mat = [p for p in seen if p.startswith("/contacts?")]
    assert mat and all("status=" not in p and "source=" not in p for p in mat)


def test_the_import_mark_is_the_one_the_importers_write():
    # contacts_import_router stamps csv_import; the structure import hands
    # people sheets to that same importer. The pattern must match both and
    # any *_import added later.
    import fnmatch
    for source in ("csv_import", "structure_import", "vcard_import"):
        assert fnmatch.fnmatch(source, btr.IMPORT_SOURCE_PATTERN)
    for source in ("manual", "chief_of_staff", "website_contact_form", "online_giving"):
        assert not fnmatch.fnmatch(source, btr.IMPORT_SOURCE_PATTERN)
    import inspect
    import contacts_import_router as cir
    assert '"source": "csv_import"' in inspect.getsource(cir.import_contacts)


# ═══ 2. setup steps per vertical ════════════════════════════════════

@pytest.mark.parametrize("vertical", ["ministry", "nonprofit", "church", "congregation"])
def test_gift_funded_organisations_are_not_asked_what_they_charge(vertical):
    keys = bta.plugins_for_vertical(vertical)
    assert "offerings" not in keys
    assert "giving" in keys
    # And nothing on their list waits on a step they do not have.
    for k in keys:
        assert all(n in keys for n in bta.needs_for(k, vertical)), k
    assert bta.needs_for("site", vertical) == []


@pytest.mark.parametrize("vertical", ["therapist", "counselor", "lawyer", "law"])
def test_intake_verticals_get_the_intake_form_step(vertical):
    keys = bta.plugins_for_vertical(vertical)
    assert "intake_form" in keys and "offerings" in keys


@pytest.mark.parametrize("vertical", ["coach", "personal_services", "contractor",
                                      "ecommerce", "custom", "ministry"])
def test_the_intake_step_stays_with_the_verticals_it_belongs_to(vertical):
    assert "intake_form" not in bta.plugins_for_vertical(vertical)


def test_giving_reaches_only_the_organisations_that_can_take_gifts():
    import vertical_family
    for v in vertical_registry.canonical_keys():
        has = "giving" in bta.plugins_for_vertical(v)
        assert has == vertical_family.is_nonprofit_like(v), v


def test_a_barber_sees_hours_and_clients_first():
    # Barbers onboard as personal_services (the registry has no "barber"
    # alias; the onboarding card writes the canonical key).
    keys = bta.plugins_for_vertical("personal_services")
    assert keys[0] == "import_contacts"
    assert "availability" in keys and "intake_form" not in keys and "giving" not in keys


def test_every_first_hour_goal_is_on_its_own_verticals_list():
    # The goal/plug-in mismatch, as a rule: the sendable artifact is "real
    # once these keys are done", so every key must be a step the vertical
    # is actually offered. Before 2026-09-26 the financial educator's
    # booking link needed hours it was never offered, and the therapist's
    # and lawyer's form had no step at all.
    for v in vertical_registry.canonical_keys():
        art = bta.sendable_artifact_for(v)
        keys = bta.plugins_for_vertical(v)
        missing = [k for k in art["keys"] if k not in keys]
        assert not missing, f"{v}: goal needs {missing}, not on its list"


def test_the_intake_how_line_keeps_the_therapist_boundary():
    how = bta.PLUGIN_CATALOG["intake_form"]["chief"]
    assert how.startswith("DO IT HERE") and "create_client_form" in how
    for word in ("symptoms", "diagnosis", "medication", "EHR"):
        assert word in how
    assert "conflicts" in how  # the lawyer's form checks conflicts


def test_the_giving_door_lands_on_the_giving_panel():
    nav = bta.PLUGIN_CATALOG["giving"]["nav"]
    assert nav == {"tab": "build", "page": "settings", "section": "giving"}
    import system_destinations
    system_destinations.destination(nav["tab"], nav["page"])  # a real page


def test_the_giving_probe_uses_the_give_page_rubric(db):
    db.biz_row = {"id": "b1", "type": "ministry",
                  "settings": {"giving": {"enabled": True}}, "stripe_account_id": "acct_1"}
    assert btr._done_giving(_biz("ministry")) is True
    db.biz_row = {**db.biz_row, "stripe_account_id": None}
    assert btr._done_giving(_biz("ministry")) is False
    db.biz_row = {**db.biz_row, "stripe_account_id": "acct_1", "settings": {}}
    assert btr._done_giving(_biz("ministry")) is False


def test_the_seeded_contact_form_is_not_an_intake_form(db):
    seed = {"id": "f1", "fields": [{"name": "name"}, {"name": "email"},
                                   {"name": "phone"}, {"name": "message"}]}
    db.forms = [seed]
    assert btr._done_intake_form(_biz("therapist")) is False
    shaped = {"id": "f2", "fields": seed["fields"] + [{"name": "insurance"}]}
    db.forms = [seed, shaped]
    assert btr._done_intake_form(_biz("therapist")) is True


def test_a_ministry_site_is_never_blocked_by_prices(db):
    items = btr.resolve_plugins(_biz("ministry"))
    keys = [p["key"] for p in items]
    assert "offerings" not in keys
    site = next(p for p in items if p["key"] == "site")
    assert "offerings" not in site["blocked_by"]
    giving = next(p for p in items if p["key"] == "giving")
    assert giving["blocked_by"] == ["payments"]


# ═══ 3. the import how-line tailors to where their clients live ══════

def test_with_no_answer_the_import_step_asks_where_the_list_lives():
    how = bta.plugin_how("import_contacts")
    assert how.startswith("DO IT HERE")
    assert "whole list" in how and "not one name" in how
    assert "structure-import" in how and "create_contact" in how
    assert "never guess" in how


def test_a_stored_answer_brings_that_tools_export_steps():
    how = bta.import_contacts_how(["square"])
    assert "Square" in how and "Customer directory" in how and "Export customers" in how
    assert "structure-import" in how and "create_contact" in how
    how = bta.import_contacts_how(["vagaro", "acuity"])
    assert "More, Reports, Customers" in how and "Export client list" in how


def test_an_unchecked_tool_gets_the_generic_line_not_a_guess():
    how = bta.import_contacts_how(["other"], other="Fresha")
    assert "Fresha" in how
    assert "look for Export in your client list" in how


def test_paper_is_taken_by_name_in_batches():
    how = bta.import_contacts_how(["paper"])
    assert how.startswith("DO IT HERE") and "create_contact" in how
    assert "handful" in how and "structure-import" in how


def test_every_source_has_a_label_and_an_export_or_an_honest_gap():
    for key, spec in bta.CLIENT_SOURCES.items():
        assert spec["label"].strip(), key
        assert spec["export"].strip() or key == "other", key


def test_resolve_plugins_hands_chief_the_tailored_line(db):
    items = btr.resolve_plugins(_biz(settings={"client_sources": {"sources": ["square"]}}))
    imp = next(p for p in items if p["key"] == "import_contacts")
    assert "Customer directory" in imp["how"]
    # ...and the setup block prints the item's own how, not the catalog's.
    import chief_prompt
    block = chief_prompt._format_setup_block(
        {"items": items, "done": 0, "total": len(items), "artifact": {}})
    assert "Customer directory" in block


def test_a_tool_named_in_the_business_session_tailors_it_too(db):
    db.track = {"first_30_days": {}, "operations_map": {"tools_in_use": ["Vagaro", "Instagram"]}}
    items = btr.resolve_plugins(_biz())
    imp = next(p for p in items if p["key"] == "import_contacts")
    assert "Vagaro" in imp["how"]


def test_squarespace_is_not_square():
    assert bta.match_client_sources(["Squarespace"]) == []
    assert bta.match_client_sources(["Square Appointments", "an Excel sheet"]) == ["square", "spreadsheet"]


def test_unknown_sources_are_dropped_not_stored():
    assert bta.normalize_client_sources(["square", "SQUARE", "myspace", "Google Contacts"]) == \
        ["square", "google_contacts"]
    assert bta.normalize_client_sources(None) == []


# ═══ 4. storage: one place, owner-gated, nothing else touched ════════

def test_saving_merges_into_settings_without_touching_other_keys(db):
    db.biz_row = {"id": "b1", "settings": {"practitioner_name": "Marcus", "track": "purpose"}}
    val = bta.save_client_sources("b1", ["square", "phone", "nope"], "Fresha", via="onboarding")
    assert val["sources"] == ["square", "phone", "other"]
    assert val["other"] == "Fresha" and val["via"] == "onboarding"
    path, body = db.patches[-1]
    assert path == "/businesses?id=eq.b1"
    assert body["settings"]["practitioner_name"] == "Marcus"
    assert body["settings"]["client_sources"]["sources"] == ["square", "phone", "other"]


def test_the_business_session_adds_to_the_onboarding_answer(db):
    db.biz_row = {"id": "b1", "settings": {"client_sources": {"sources": ["phone"]}}}
    val = bta.save_client_sources("b1", ["vagaro"], via="business_session", merge=True)
    assert val["sources"] == ["phone", "vagaro"]


def test_the_endpoint_is_owner_gated(db, monkeypatch):
    seen = {}

    def gate(biz_id, user, min_role="member"):
        seen["role"] = min_role
        return {"id": biz_id}
    monkeypatch.setattr(btr, "_gate", gate)
    db.biz_row = {"id": "b1", "settings": {}}
    out = btr.put_client_sources("b1", btr.ClientSourcesBody(sources=["acuity"]), user=object())
    assert seen["role"] == "owner"
    assert out["ok"] and out["client_sources"]["sources"] == ["acuity"]
    assert out["labels"] == ["Acuity"]


def test_the_coach_is_told_the_answer_and_can_record_it():
    ctx = {"business": {"id": "b1", "name": "Fade Society", "type": "personal_services",
                        "settings": {"practitioner_name": "Marcus",
                                     "client_sources": {"sources": ["booksy"]}}},
           "business_track": {}}
    p = bta.build_business_coach_prompt(ctx, False)
    assert "where their client list lives today: Booksy" in p
    assert '"client_sources"' in p


# ═══ 5. the resolve_plugins contract ════════════════════════════════

def test_resolve_plugins_keeps_every_key_and_type_it_had(db):
    items = btr.resolve_plugins(_biz("coach"))
    assert items
    for p in items:
        assert isinstance(p["key"], str) and p["key"] in bta.PLUGIN_CATALOG
        assert isinstance(p["title"], str) and isinstance(p["why"], str)
        assert isinstance(p["nav"], dict) and p["nav"].get("tab")
        assert isinstance(p["done"], bool)
        assert isinstance(p["blocked_by"], list)
        # the one addition
        assert isinstance(p["how"], str) and p["how"].startswith(("DO IT HERE", "DOOR"))
    assert [(p["done"], bool(p["blocked_by"])) for p in items] == \
        sorted((p["done"], bool(p["blocked_by"])) for p in items)


# ═══ 6. the archetype lens resolves aliases ═════════════════════════

def test_an_alias_reads_its_verticals_lens():
    import chief_prompt
    church = chief_prompt._build_archetype_block({"type": "church"}, {})
    ministry = chief_prompt._build_archetype_block({"type": "ministry"}, {})
    assert church == ministry and "ARCHETYPE LENS —" in church
    assert chief_prompt._build_archetype_block({"type": "Counselor"}, {}) == \
        chief_prompt._build_archetype_block({"type": "therapist"}, {})
    generic = chief_prompt._build_archetype_block({"type": "mobile pet grooming"}, {})
    assert generic.startswith("ARCHETYPE LENS.")
