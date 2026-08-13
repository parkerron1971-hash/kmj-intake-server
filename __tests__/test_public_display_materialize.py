"""Post-audit gap list (2026-08-13) — Chief's ruling on customer
visibility has to survive the write.

public_display was a captured slot only. The spec model carried it, the
generator's own docstring said so, and materialize_spec's write_payload
dropped it. So an LLM could decide a module was customer_visible, that
decision was written into the spec, and then thrown away — Chief's main
build path could not put a menu on a website whatever it concluded.

Materializing it safely depends on the same two rules as the field
picker shipped the same day:

  1. customer_facing decides which fields go out. It defaults to False
     on every field, so a published module shows only what was
     deliberately marked, never its whole schema.
  2. A module with nothing to show is not published. Until today an
     empty allow-list was read by the public renderers as permission to
     publish EVERY field, which is how a client roster could have
     reached the open web.
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import module_spec_generator as msg  # noqa: E402


def _schema(*fields):
    return {"fields": list(fields)}


def _f(name, customer_facing=False, ftype="text"):
    return {"name": name, "type": ftype, "label": name.title(),
            "customer_facing": customer_facing}


def _pd(spec, schema):
    return msg._public_display_from_spec(spec, schema)


# ─── internal by default ─────────────────────────────────────────────


def test_no_slot_means_private():
    assert _pd({}, _schema(_f("title", True)))["enabled"] is False


def test_internal_only_means_private():
    spec = {"public_display": {"visibility": "internal_only"}}
    assert _pd(spec, _schema(_f("title", True)))["enabled"] is False


def test_malformed_slot_means_private():
    for slot in ("nope", 5, []):
        assert _pd({"public_display": slot}, _schema(_f("t", True)))["enabled"] is False


# ─── customer_visible publishes only what was marked ─────────────────


def test_customer_visible_publishes_the_marked_fields():
    spec = {"public_display": {"visibility": "customer_visible"}}
    schema = _schema(_f("dish", True), _f("price", True), _f("cost_to_me"))
    pd = _pd(spec, schema)
    assert pd["enabled"] is True
    assert pd["visible_fields"] == ["dish", "price"]


def test_unmarked_fields_never_go_out():
    """The whole safety guarantee. cost_to_me and supplier are exactly
    the kind of thing a practitioner would be horrified to publish."""
    spec = {"public_display": {"visibility": "customer_visible"}}
    schema = _schema(_f("dish", True), _f("cost_to_me"), _f("supplier"))
    pd = _pd(spec, schema)
    assert "cost_to_me" not in pd["visible_fields"]
    assert "supplier" not in pd["visible_fields"]


def test_customer_visible_with_no_marked_fields_stays_private():
    """An under-specified spec is not permission to guess — and an empty
    allow-list used to mean 'publish everything'."""
    spec = {"public_display": {"visibility": "customer_visible"}}
    pd = _pd(spec, _schema(_f("dish"), _f("price")))
    assert pd["enabled"] is False
    assert "visible_fields" not in pd


def test_contact_links_are_never_published_even_if_marked():
    spec = {"public_display": {"visibility": "customer_visible"}}
    schema = _schema(_f("dish", True), _f("who", True, ftype="contact_link"))
    assert _pd(spec, schema)["visible_fields"] == ["dish"]


def test_internal_bookkeeping_names_are_never_published_even_if_marked():
    spec = {"public_display": {"visibility": "customer_visible"}}
    schema = _schema(_f("dish", True), _f("assigned_to", True),
                     _f("contact_id", True), _f("internal_notes", True))
    assert _pd(spec, schema)["visible_fields"] == ["dish"]


def test_hidden_fields_are_written_as_a_backstop():
    spec = {"public_display": {"visibility": "customer_visible"}}
    pd = _pd(spec, _schema(_f("dish", True)))
    assert set(pd["hidden_fields"]) == {"contact_id", "assigned_to", "internal_notes"}


def test_component_hint_is_carried_through():
    spec = {"public_display": {"visibility": "customer_visible",
                               "component": "MenuBoard"}}
    assert _pd(spec, _schema(_f("dish", True)))["component"] == "MenuBoard"


# ─── it actually reaches the write ───────────────────────────────────


def test_write_payload_includes_public_display():
    """The regression: the payload dropped the key entirely."""
    import inspect
    src = inspect.getsource(msg.materialize_spec)
    assert '"public_display": _public_display_from_spec(' in src, (
        "materialize_spec is not writing public_display")
