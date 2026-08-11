"""
test_module_vocabulary.py — the module vocabulary has ONE declaration,
and the LLM is actually told all of it.

THE BUG THIS FILE EXISTS FOR
────────────────────────────
module_spec_generator.FieldType has included 'offering_ref' since C.1.2.
The system prompt's prose list of field types did not. The validator
accepted a word the model was never taught, so Chief could not emit it —
a capability that shipped, passed review, and was unreachable.

That is the same shape as the archetype bug that produced
test_archetype_enum.py::test_prompt_palette_offers_every_archetype
("work_pipeline existing in the enum but not the prompt = the model
never emits it"). This file applies that lesson to the four remaining
vocabularies.

The load-bearing assertion is not "one list exists". It is
test_prompt_teaches_every_* below: a word the prompt never says is a
word Chief does not have.
"""

import re
from typing import get_args

import pytest

import module_vocabulary as mv


# ─── The declaration itself ───────────────────────────────────────────

def test_literals_and_tuples_agree():
    """The *_VALUES tuples are derived via get_args, never hand-typed.
    If someone replaces a derivation with a literal tuple and gets it
    wrong, this catches it."""
    assert mv.FIELD_TYPES == get_args(mv.FieldType)
    assert mv.VIEW_KINDS == get_args(mv.ViewKind)
    assert mv.TRIGGER_KINDS == get_args(mv.TriggerKind)
    assert mv.OFFERING_CATEGORIES == get_args(mv.OfferingCategory)


def test_no_duplicates_and_no_empties():
    for name in ("FIELD_TYPES", "VIEW_KINDS", "TRIGGER_KINDS", "OFFERING_CATEGORIES"):
        values = getattr(mv, name)
        assert values, f"{name} is empty"
        assert len(set(values)) == len(values), f"{name} has a duplicate"
        assert all(v and v.strip() == v for v in values), f"{name} has a blank/padded entry"


def test_donation_is_not_an_offering_category():
    """Fork 25 Giving guard. Donations live behind the restricted-modules
    surface; a donation category here would route giving through the
    ordinary catalog."""
    assert "donation" not in mv.OFFERING_CATEGORIES


def test_subsets_are_subsets():
    """BOOKABLE/SELLABLE are groupings of the vocabulary, not private
    copies that can name a category which no longer exists."""
    assert mv.BOOKABLE_CATEGORIES <= set(mv.OFFERING_CATEGORIES)
    assert mv.SELLABLE_CATEGORIES <= set(mv.OFFERING_CATEGORIES)
    assert mv.VALID_OFFERING_CATEGORIES == set(mv.OFFERING_CATEGORIES)


# ─── One declaration: everything downstream derives ───────────────────

def test_spec_generator_reexports_the_same_objects():
    """module_spec_generator re-exports the vocabulary for its long-time
    importers. If it ever re-declares instead of re-exporting, these stop
    being the same object and drift becomes possible again."""
    import module_spec_generator as msg

    assert msg.FieldType is mv.FieldType
    assert msg.ViewKind is mv.ViewKind
    assert msg.TriggerKind is mv.TriggerKind
    assert msg.OfferingCategory is mv.OfferingCategory


def test_offerings_router_validates_against_the_vocabulary():
    import offerings_router

    assert offerings_router._VALID_CATEGORIES == set(mv.OFFERING_CATEGORIES)


def test_chief_validates_against_the_vocabulary():
    import chief_of_staff

    assert chief_of_staff._VALID_OFFERING_CATEGORIES == set(mv.OFFERING_CATEGORIES)


# ─── The one that matters: is the MODEL told? ─────────────────────────

def _declared_field_types_in_prompt() -> set[str]:
    """Pull the field-type LIST out of the prompt — the 'field types: …'
    clause specifically, not the whole prompt.

    Asserting `field_type in _SYSTEM_PROMPT` looks equivalent and is
    worthless: the prompt is ~300 lines and mentions offering_ref in
    twenty other places (its constraint rules, examples, archetype
    params). A whole-prompt substring check stayed GREEN when the stale
    list was reinstated — i.e. it would NOT have caught the original bug.
    Verified by reintroducing the bug, not by reasoning about it."""
    import module_spec_generator as msg

    match = re.search(r"field types:\s*([^)]*)\)", msg._SYSTEM_PROMPT)
    assert match, "the prompt no longer carries a 'field types: …' clause"
    return {t.strip() for t in match.group(1).split(",") if t.strip()}


def test_prompt_field_type_list_is_exactly_the_vocabulary():
    """The list the model is handed must BE the vocabulary — no more, no
    less. Missing = a capability Chief cannot reach. Extra = Chief emits
    a type the validator rejects, and the practitioner sees a failure."""
    assert _declared_field_types_in_prompt() == set(mv.FIELD_TYPES)


@pytest.mark.parametrize("field_type", sorted(mv.FIELD_TYPES))
def test_prompt_teaches_every_field_type(field_type):
    """Per-type, so a failure names the missing word."""
    assert field_type in _declared_field_types_in_prompt(), (
        f"'{field_type}' is in the vocabulary but the prompt's field-type "
        f"list never names it — the model cannot emit what it was not told"
    )


def test_prompt_view_kind_list_is_exactly_the_vocabulary():
    import module_spec_generator as msg

    match = re.search(r"views:\s*([^;)]*)[;)]", msg._SYSTEM_PROMPT)
    assert match, "the prompt no longer carries a 'views: …' clause"
    declared = {v.strip() for v in match.group(1).split(",") if v.strip()}
    assert declared == set(mv.VIEW_KINDS)


def test_no_placeholder_survives_into_the_prompt():
    """The prompt is a plain string with __TOKEN__ placeholders rather
    than an f-string (it is full of literal JSON braces). A renamed or
    mistyped token would otherwise ship to the model verbatim."""
    import module_spec_generator as msg

    leftovers = re.findall(r"__[A-Z_]+__", msg._SYSTEM_PROMPT)
    assert not leftovers, f"unsubstituted placeholder(s) in the prompt: {leftovers}"


class _EmptyCtx(dict):
    """_build_system_prompt reads a few dozen context keys unguarded;
    anything unset reads as empty. Borrowed from test_growth_doctrine."""
    def __missing__(self, key):
        return []


def _min_ctx():
    return _EmptyCtx(business={"id": "b1", "name": "Test Co", "type": "coach",
                               "settings": {}, "voice_profile": {}})


@pytest.mark.parametrize("category", sorted(mv.OFFERING_CATEGORIES))
def test_chief_prompt_teaches_every_offering_category(category):
    """Chief's own prompt enumerates the offering categories inline. Same
    rule: the closed enum it states has to be the closed enum we enforce,
    or Chief proposes a category create_offering will reject.

    Asserts against the BUILT prompt, not the source — an interpolation
    can be present in the source and still be dropped on the floor."""
    import chief_of_staff as cos

    prompt = cos._build_system_prompt(_min_ctx(), False)
    assert category in prompt, (
        f"offering category '{category}' never reaches Chief's system prompt"
    )


# ─── The executor has to handle what the vocabulary allows ────────────

@pytest.mark.parametrize("trigger_kind", sorted(mv.TRIGGER_KINDS))
def test_module_agent_dispatches_every_trigger_kind(trigger_kind):
    """module_agent.py's dispatch chain is the real consumer of
    TriggerKind. A kind with no branch there is not an error — it is a
    silent no-op, which is worse: the trigger saves, shows in the UI, and
    never fires."""
    import inspect

    import module_agent

    source = inspect.getsource(module_agent)
    assert f'"{trigger_kind}"' in source, (
        f"trigger kind '{trigger_kind}' is in the vocabulary but "
        f"module_agent.py never mentions it — it would save and never fire"
    )


# ─── The DB is the root of truth for offering categories ──────────────

def test_offering_categories_match_the_db_check_constraint():
    """supabase/offerings-migration.sql carries the CHECK that actually
    rejects a bad category. If the app-layer list grows past it, the
    write fails at the database with a 400 the practitioner cannot act
    on."""
    import pathlib

    sql_path = pathlib.Path(__file__).resolve().parent.parent / "supabase" / "offerings-migration.sql"
    if not sql_path.exists():
        pytest.skip(f"{sql_path.name} not present in this checkout")

    sql = sql_path.read_text(encoding="utf-8", errors="replace")
    # Strip `-- …` comments FIRST. The per-category comments contain their
    # own parentheses ("(one-time)"), which truncate a naive [^)]* match at
    # the third category and make this test report a drift that isn't there.
    sql = re.sub(r"--[^\n]*", "", sql)
    match = re.search(r"category\s+IN\s*\(([^)]*)\)", sql, re.IGNORECASE)
    assert match, "could not find the category CHECK constraint in offerings-migration.sql"

    in_db = {m.group(1) for m in re.finditer(r"'([a-z_]+)'", match.group(1))}
    assert in_db == set(mv.OFFERING_CATEGORIES), (
        f"app vocabulary {sorted(mv.OFFERING_CATEGORIES)} != "
        f"DB CHECK {sorted(in_db)} — a write would fail at the database"
    )


# ─── Served to the frontend ───────────────────────────────────────────
# GET /module-specs/vocabulary is how the studio's builder stops guessing
# what the backend allows. A TS union must exist at compile time, so the
# frontend copy cannot be deleted — but it can be CHECKED against this.

def test_as_dict_carries_all_four_vocabularies():
    d = mv.as_dict()
    assert set(d) == {"field_types", "view_kinds", "trigger_kinds",
                      "offering_categories"}
    assert d["field_types"] == list(mv.FIELD_TYPES)
    assert d["view_kinds"] == list(mv.VIEW_KINDS)
    assert d["trigger_kinds"] == list(mv.TRIGGER_KINDS)
    assert d["offering_categories"] == list(mv.OFFERING_CATEGORIES)


def test_as_dict_is_json_serializable():
    """It is served over HTTP; a tuple that survives in Python and fails
    at the wire would only show up in production."""
    import json

    assert json.loads(json.dumps(mv.as_dict())) == mv.as_dict()


def test_the_vocabulary_endpoint_requires_auth_and_returns_the_list():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    import module_spec_router as msr
    from auth_supabase import require_user

    app = FastAPI()
    app.include_router(msr.router)

    # Unauthenticated first — this is a platform constant, not tenant
    # data, but every read in this service sits behind auth and this one
    # should not be the exception that teaches otherwise.
    assert TestClient(app).get("/module-specs/vocabulary").status_code in (401, 403)

    class _User:
        id = "u1"

    app.dependency_overrides[require_user] = lambda: _User()
    body = TestClient(app).get("/module-specs/vocabulary").json()

    assert body["ok"] is True
    assert body["vocabulary"] == mv.as_dict()
    # The thing the frontend actually needs from it.
    assert "offering_ref" in body["vocabulary"]["field_types"]


def test_vocabulary_route_is_not_shadowed_by_a_path_param():
    """/vocabulary sits on a router that also serves /{spec_id} shaped
    routes. If one of those ever becomes a GET declared earlier, this
    endpoint quietly starts resolving a spec named "vocabulary"."""
    import module_spec_router as msr

    paths = [r.path for r in msr.router.routes]
    vocab_i = paths.index("/module-specs/vocabulary")
    for i, p in enumerate(paths):
        if i < vocab_i and "{" in p and "GET" in getattr(
                msr.router.routes[i], "methods", set()):
            raise AssertionError(
                f"GET {p} is declared before /vocabulary and will shadow it")


# ─── module_ref, the spec-level contract ──────────────────────────────

def _spec(fields, slug="payments", archetype="fallback_generic"):
    import module_spec_generator as msg

    return msg.ModuleSpec(
        name="Payments", slug=slug, description="d", icon="💳",
        intake_excerpt="track payments against matters",
        schema={"fields": fields, "views": ["list"]},
        agent_config={"enabled": True, "triggers": []},
        archetype=archetype, archetype_params={},
        archetype_fallback_reason="test", reasoning="r", confidence="high",
    )


def _f(name, ftype="text", **kw):
    d = {"name": name, "type": ftype, "label": name.title()}
    d.update(kw)
    return d


def test_module_ref_needs_a_target():
    import pydantic

    with pytest.raises(pydantic.ValidationError, match="module_slug"):
        _spec([_f("matter", "module_ref")])


def test_module_ref_with_a_target_validates():
    s = _spec([_f("matter", "module_ref", module_slug="matters")])
    assert s.schema_.fields[0].module_slug == "matters"


def test_module_ref_cannot_point_at_its_own_module():
    """A payments row referencing the payments module is a loop with no
    meaning, and the likeliest generator slip when it decomposes."""
    import pydantic

    with pytest.raises(pydantic.ValidationError, match="its own module"):
        _spec([_f("self", "module_ref", module_slug="payments")], slug="payments")


def test_module_ref_must_not_carry_options():
    """The choices ARE the target module's rows, resolved at render time.
    A populated options[] means the model built a select and mislabelled
    it, which would render an empty dropdown of stale strings."""
    import pydantic

    with pytest.raises(pydantic.ValidationError, match="options"):
        _spec([_f("m", "module_ref", module_slug="matters", options=["a"])])


def test_module_ref_is_checked_for_every_archetype():
    """The offering_ref rule lives inside the booking_calendar block and
    so only ever guarded one archetype. This one is deliberately outside
    them — a field pointing at another module is a schema concern."""
    import pydantic

    for arch in ("fallback_generic", "work_pipeline", "event_roster"):
        with pytest.raises(pydantic.ValidationError, match="module_slug"):
            _spec([_f("matter", "module_ref")], archetype=arch)


@pytest.mark.parametrize("field_type", ["module_ref"])
def test_prompt_teaches_module_ref(field_type):
    """A type the prompt never names is a type Chief never emits."""
    assert field_type in _declared_field_types_in_prompt()
