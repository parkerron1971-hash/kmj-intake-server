"""
test_build_skills.py — build knowledge as data.

Two things have to hold or the library is decoration:

  1. Selection is DETERMINISTIC and correct — same inputs, same skills,
     and a skill scoped to other business types never attaches.
  2. The selected skill REACHES THE MODEL. This is the lesson from the
     offering_ref incident (feedback: the prompt is the capability
     surface). A skill file that parses, scores, renders, and is then
     dropped before the API call is worth exactly nothing, and every
     unit test above it would still pass.
"""

import pathlib

import pytest

import build_skills as bs

SKILL_A = """---
name: alpha
description: the alpha skill
triggers: [booking, appointment]
---
Alpha guidance body.
"""

SKILL_TYPED = """---
name: typed
description: only for lawyers
business_types: [lawyer]
triggers: [matter, case]
---
Typed guidance body.
"""


@pytest.fixture
def lib(tmp_path):
    (tmp_path / "alpha.md").write_text(SKILL_A, encoding="utf-8")
    (tmp_path / "typed.md").write_text(SKILL_TYPED, encoding="utf-8")
    return tmp_path


# ─── Parsing ──────────────────────────────────────────────────────────

def test_parses_frontmatter_and_body():
    s = bs.parse_skill(SKILL_A)
    assert s["name"] == "alpha"
    assert s["triggers"] == ["booking", "appointment"]
    assert "Alpha guidance body." in s["body"]


def test_parses_comma_form_without_brackets():
    s = bs.parse_skill("---\nname: x\ndescription: d\ntriggers: a, b\n---\nbody\n")
    assert s["triggers"] == ["a", "b"]


@pytest.mark.parametrize("text", [
    "no frontmatter at all",
    "---\nname: x\n---\n",                      # no body
    "---\ndescription: d\n---\nbody",           # no name
    "---\nname: x\n---\nbody",                  # no description
])
def test_malformed_skills_are_skipped_not_raised(text):
    """A bad file must never take the build path down with it."""
    assert bs.parse_skill(text) is None


def test_a_malformed_file_does_not_hide_the_good_ones(tmp_path):
    (tmp_path / "good.md").write_text(SKILL_A, encoding="utf-8")
    (tmp_path / "bad.md").write_text("garbage", encoding="utf-8")
    names = [s["name"] for s in bs.load_skills(tmp_path)]
    assert names == ["alpha"]


def test_missing_directory_is_empty_not_an_error():
    assert bs.load_skills(pathlib.Path("/nonexistent-skills-dir")) == []


# ─── Selection ────────────────────────────────────────────────────────

def test_a_trigger_word_selects_the_skill(lib):
    got = bs.select_skills("I need to track my appointments", "coach", lib)
    assert [s["name"] for s in got] == ["alpha"]


def test_no_trigger_means_no_skill(lib):
    assert bs.select_skills("I want to track my recipes", "coach", lib) == []


def test_a_typed_skill_does_not_leak_into_another_business(lib):
    """Booking guidance written for barbers inside a law firm's build is
    worse than no guidance. business_types is a hard filter, not a bonus."""
    got = bs.select_skills("open a new matter", "coach", lib)
    assert got == []


def test_a_typed_skill_applies_to_its_own_business(lib):
    got = bs.select_skills("open a new matter", "lawyer", lib)
    assert [s["name"] for s in got] == ["typed"]


def test_selection_is_deterministic(lib):
    a = bs.select_skills("appointment booking", "coach", lib)
    b = bs.select_skills("appointment booking", "coach", lib)
    assert [s["name"] for s in a] == [s["name"] for s in b]


def test_selection_is_capped(tmp_path):
    """The prompt is already ~17.8KB. An unbounded library would quietly
    turn every build into a much more expensive call."""
    for i in range(6):
        (tmp_path / f"s{i}.md").write_text(
            f"---\nname: s{i}\ndescription: d\ntriggers: [booking]\n---\nbody {i}\n",
            encoding="utf-8")
    assert len(bs.select_skills("booking", "coach", tmp_path)) == bs.MAX_SKILLS


def test_matching_is_case_insensitive(lib):
    assert bs.select_skills("BOOKING please", "coach", lib)


# ─── Rendering ────────────────────────────────────────────────────────

def test_no_skills_renders_nothing(lib):
    assert bs.skills_block([]) == ""
    assert bs.block_for("recipes", "coach", lib) == ""


def test_block_carries_the_body(lib):
    block = bs.block_for("appointment", "coach", lib)
    assert "Alpha guidance body." in block
    assert "APPLICABLE BUILD SKILLS" in block


# ─── The shipped library ──────────────────────────────────────────────

def test_every_shipped_skill_parses():
    """The loader skips malformed files silently on purpose. This is the
    test that makes a broken skill loud instead — at the moment someone
    writes one, rather than by never firing in production."""
    files = sorted(bs.SKILLS_DIR.glob("*.md"))
    assert files, "no skills shipped"
    for p in files:
        assert bs.parse_skill(p.read_text(encoding="utf-8")) is not None, \
            f"{p.name} is malformed"


def test_shipped_skill_names_are_unique():
    names = [s["name"] for s in bs.load_skills()]
    assert len(names) == len(set(names))


@pytest.mark.parametrize("intake,expected", [
    ("I want to track appointments for my clients", "booking-module"),
    ("a board of leads moving through stages", "pipeline-module"),
    ("collect reviews and ratings from customers", "feedback-module"),
])
def test_the_shipped_skills_fire_on_their_own_subject(intake, expected):
    got = [s["name"] for s in bs.select_skills(intake, "coach")]
    assert expected in got, f"{expected} did not fire on {intake!r} (got {got})"


def test_shipped_skills_only_reference_real_field_types():
    """A skill that recommends a field type the vocabulary does not have
    teaches Chief to emit something the validator rejects — the
    offering_ref bug pointed the other way."""
    import re

    import module_vocabulary as mv

    known = set(mv.FIELD_TYPES) | set(mv.VIEW_KINDS) | set(mv.TRIGGER_KINDS)
    for s in bs.load_skills():
        # Backticked words are how these skills name a type.
        for token in re.findall(r"`([a-z_]+)`", s["body"]):
            # Schema KEYS and conventional field names, as opposed to
            # field TYPES. The skills name both, and only the second kind
            # has to exist in the vocabulary.
            if token.endswith("_field") or token in {"status", "stage",
                                                     "closed_statuses",
                                                     "board_column",
                                                     "default_view",
                                                     "offering_categories",
                                                     "created_at", "date",
                                                     # keys of a trigger object
                                                     "type", "action",
                                                     "template", "field",
                                                     # the key the model
                                                     # wrongly invented, which
                                                     # the skills now warn off
                                                     "event"}:
                continue
            assert token in known or "_" in token, (
                f"skill {s['name']} names `{token}`, which is not a field "
                f"type, view or trigger in the vocabulary")


# ─── Does it reach the model? ─────────────────────────────────────────

def test_the_skill_block_actually_reaches_the_system_prompt(monkeypatch):
    """THE test. Everything above can pass while the block is computed and
    dropped on the floor before the API call."""
    import module_spec_generator as msg

    captured = {}

    class _FakeMessages:
        def create(self, **kw):
            captured.update(kw)
            raise RuntimeError("stop here — we only need the system prompt")

    class _FakeClient:
        messages = _FakeMessages()

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(msg.llm_call, "sdk_client", lambda **kw: _FakeClient())

    msg.generate_module_proposal({"name": "Test Co", "type": "coach"},
                           "I need to track appointments and bookings")

    system = captured.get("system", "")
    assert "APPLICABLE BUILD SKILLS" in system, \
        "skills were selected but never reached the model"
    assert "booking-module" in system
    # and the base prompt is still there, not replaced
    assert "You design custom data modules" in system


def test_no_skill_block_when_nothing_applies(monkeypatch):
    import module_spec_generator as msg

    captured = {}

    class _FakeMessages:
        def create(self, **kw):
            captured.update(kw)
            raise RuntimeError("stop")

    class _FakeClient:
        messages = _FakeMessages()

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(msg.llm_call, "sdk_client", lambda **kw: _FakeClient())

    msg.generate_module_proposal({"name": "Test Co", "type": "coach"},
                           "I want to store my grandmother's recipes")

    system = captured.get("system", "")
    assert "APPLICABLE BUILD SKILLS" not in system
    assert system == msg._SYSTEM_PROMPT


# ─── A skill that asks for triggers must show their shape ─────────────

def test_a_skill_that_names_a_trigger_kind_shows_the_required_keys():
    """THE REGRESSION THIS EXISTS FOR, caught by the eval harness on its
    first live run.

    Both reference examples in _SYSTEM_PROMPT show `"triggers": []` —
    EMPTY. The model is never shown a populated trigger. The skills then
    told it to ADD one ("`overdue` on the date field") without stating
    the shape, so it invented {"event": "overdue", "field": ...}.
    ModuleTrigger requires `type` and `action`, Pydantic rejected the
    whole ProposalEnvelope, and Chief built NOTHING — strictly worse than
    the empty-triggers module it produced before the skills existed.

    Naming a trigger kind is an instruction to emit one. Any skill that
    does so has to carry the keys, because the base prompt does not.
    """
    import module_vocabulary as mv

    for s in bs.load_skills():
        body = s["body"]
        if not any(k in body for k in mv.TRIGGER_KINDS):
            continue
        assert '"type"' in body, (
            f"skill {s['name']} names a trigger kind but never shows the "
            f'required "type" key — the base prompt only ever shows '
            f'"triggers": [], so the model has nothing to copy')
        assert '"action"' in body, (
            f"skill {s['name']} names a trigger kind but never shows the "
            f'required "action" key')
        assert '"event"' not in body, (
            f"skill {s['name']} mentions \"event\" — that is the key the "
            f"model wrongly invented; the field is \"type\"")


def test_skills_only_name_real_trigger_actions():
    """module_agent maps action -> agent_queue.action_type. An unknown
    action still runs but falls through to 'other', so the practitioner's
    queue loses the distinction between a reminder and an acknowledgment."""
    import re

    known = {"draft_acknowledgment", "draft_reminder", "draft_notification"}
    for s in bs.load_skills():
        for m in re.finditer(r'"action":\s*"([a-z_]+)"', s["body"]):
            assert m.group(1) in known, (
                f"skill {s['name']} uses action {m.group(1)!r}, which "
                f"module_agent does not map — expected one of {sorted(known)}")
