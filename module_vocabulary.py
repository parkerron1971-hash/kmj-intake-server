"""
module_vocabulary.py — THE MODULE VOCABULARY, backend side.

The closed set of words a custom module can be built out of: field
types, view kinds, module-agent trigger kinds, offering categories.
Chief composes modules from exactly this vocabulary; the practitioner
picks from it by hand in ModuleBuilder. Frontend twin:
src/core/types/moduleVocabulary.ts.

WHY THIS FILE EXISTS
────────────────────
The vocabulary was written out by hand in a dozen places across the two
repos, and the copies had already fallen out of step in the way that
matters most — the LLM PROMPT.

  module_spec_generator.py declared FieldType with 'offering_ref' in it,
  and three lines of prose in _SYSTEM_PROMPT told the model the field
  types were "text, textarea, select, date, number, checkbox,
  contact_link, url, email". No offering_ref.

A type the prompt never mentions is a type the model never emits. The
union was widened; Chief's actual vocabulary was not. Widening a Literal
is not what gives Chief a new word — telling it is.

So the rule here is not merely "one list". It is: **the prompt is
generated from the list, and a test asserts every member appears in the
prompt.** That test (test_module_vocabulary.py) is the one that would
have caught the drift above, and it is modelled directly on
test_archetype_enum.py::test_prompt_palette_offers_every_archetype,
which was written after the identical failure with archetypes.

DISCIPLINE
──────────
  - Adding a word = adding it to the Literal HERE, and nowhere else in
    this repo. Everything downstream derives.
  - Every Literal has a matching `*_VALUES` tuple derived via get_args().
    Never hand-write the tuple; that is the duplication coming back.
  - Renderers, routers and validators may branch on individual members.
    That is consuming the vocabulary, not redeclaring it.
  - The frontend keeps its own mirror because a TS union has to exist at
    compile time. `GET /module-specs/vocabulary` serves this list at
    runtime, so the builder asks the server what the server allows rather
    than guessing — and reports the difference instead of silently
    offering a type Chief will never produce, or hiding one it will.
"""

from __future__ import annotations

from typing import Literal, get_args

# ─── Field types ──────────────────────────────────────────────────────
# Mirrors the frontend FieldType exactly — drift means DynamicModule
# rejects a schema this module accepted, or vice versa.

FieldType = Literal[
    "text",
    "textarea",
    "select",
    "date",
    "number",
    "checkbox",
    "contact_link",
    "url",
    "email",
    # Phase C.1.2 — references an offerings row by id. The widget resolves
    # the dropdown from offerings filtered by the field's
    # offering_categories constraint.
    "offering_ref",
    # ── Added once the vocabulary had ONE declaration. Each cost a line
    # here plus a renderer branch, rather than edits to a union, a
    # validator, a dropdown and two prompts across two repos. The prompt
    # picked them up for free — that is the whole point of the
    # consolidation.
    "phone",     # tel input; stored as typed
    "currency",  # stored as a NUMBER so sorting and totals keep working
    "rating",    # integer 1-5
    # Points at a ROW of another custom module, by id. The field carries
    # `module_slug` naming the target, exactly as offering_ref carries
    # offering_categories.
    #
    # WHY: 20 blueprint fields across all 10 verticals named another module
    # and stored it as free TEXT — lawyer/payments.matter, consultant/
    # payments.project, service_provider/invoices.job. The Matters module
    # sat right beside the payment and nothing connected them, so "what is
    # unbilled on the Nakamura matter" had no answer, a rename orphaned
    # every child row, and a typo broke the link silently.
    "module_ref",
]

FIELD_TYPES: tuple[str, ...] = get_args(FieldType)

# ─── Views ────────────────────────────────────────────────────────────

ViewKind = Literal["list", "board"]
VIEW_KINDS: tuple[str, ...] = get_args(ViewKind)

# ─── Module-agent triggers ────────────────────────────────────────────
# The real consumer is module_agent.py's dispatch chain. A kind that
# exists here but has no branch there is a silent no-op, so the test
# suite asserts the dispatch covers every member.

TriggerKind = Literal["new_entry", "overdue", "field_change"]
TRIGGER_KINDS: tuple[str, ...] = get_args(TriggerKind)

# ─── Offering categories ──────────────────────────────────────────────
# Mirrors the offerings.category CHECK constraint
# (supabase/offerings-migration.sql). The DB is the root of truth for
# this one; this Literal is the app-layer statement of the same set, and
# the test asserts the migration's CHECK still agrees.
#
# 'donation' is intentionally NOT a category — donations live behind the
# restricted-modules surface (Fork 25 Giving guard).

OfferingCategory = Literal[
    "service",
    "session",
    "event",
    "course",
    "product",
    "package",
    "custom",
]

OFFERING_CATEGORIES: tuple[str, ...] = get_args(OfferingCategory)

# Sets, for the routers that validate membership. Derived, never typed
# out — a hand-written set beside a Literal is exactly the drift this
# module exists to end.
VALID_OFFERING_CATEGORIES: frozenset[str] = frozenset(OFFERING_CATEGORIES)

# Deliberate SUBSETS. These are not smaller copies of the vocabulary,
# they are meaningful groupings, so they live here where a category
# addition is visible next to them and forces a decision.
BOOKABLE_CATEGORIES: frozenset[str] = frozenset({"service", "session"})
SELLABLE_CATEGORIES: frozenset[str] = frozenset({"product", "course", "package"})


# ─── Prompt fragments ─────────────────────────────────────────────────
# The LLM's copy of the vocabulary, GENERATED. This is the seam where the
# drift actually hurt: prose that enumerates the words is still a copy of
# the list, and prose is the copy no compiler checks.

def field_types_sentence() -> str:
    """Comma-joined field types, for a system prompt."""
    return ", ".join(FIELD_TYPES)


def view_kinds_sentence() -> str:
    return ", ".join(VIEW_KINDS)


def trigger_kinds_sentence() -> str:
    return ", ".join(TRIGGER_KINDS)


def offering_categories_sentence() -> str:
    """Pipe-joined, matching the 'closed enum: a | b | c' phrasing Chief's
    prompt already uses for offerings."""
    return " | ".join(OFFERING_CATEGORIES)


def as_dict() -> dict[str, list[str]]:
    """The whole vocabulary as plain data — served by
    GET /modules/vocabulary and used by the parity tests."""
    return {
        "field_types": list(FIELD_TYPES),
        "view_kinds": list(VIEW_KINDS),
        "trigger_kinds": list(TRIGGER_KINDS),
        "offering_categories": list(OFFERING_CATEGORIES),
    }
