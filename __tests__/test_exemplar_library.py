"""
test_exemplar_library.py — the DRL's exemplar shelf (7 → 15, 2026-08-29).

Every exemplar is a DRO the brain can learn a MOVE from. This pins:
  • the library is 15 records, each schema-valid (jsonschema) AND valid by
    the runtime validator, with consumable signals from the taxonomy;
  • every enumerated signal value and every value on the 8 distinctiveness
    axes appears in at least one exemplar — the reason the shelf widened
    (the interview bridge's own outputs — craft_first, curious,
    discrete_artifacts, high_conviction — had NO worked example);
  • no two exemplars collide on the 8-axis signature (< threshold), and
    each record's stated axes_shared_with_nearest matches the measured
    value (the record's own number is not trusted);
  • every language choice is a registered language, one exemplar per
    wider-shelf language; and the selector reaches each new exemplar as
    the nearest for its own signal set.
"""
import json
import os

import jsonschema

from agents.composer import drl
from agents.composer.drl import passes, signals as sig
import design_languages as dl


NEW = ("e8_broadsheet", "e9_signal", "e10_atelier", "e11_neon", "e12_hearth",
       "e13_glass", "e14_runway", "e15_arena")


def _lib():
    return {e["exemplar_id"]: e for e in drl.load_exemplars()}


def test_fifteen_records_each_valid_two_ways():
    lib = _lib()
    assert len(lib) == 15
    for k in NEW:
        assert k in lib
    schema = drl.load_schema()
    for k, e in lib.items():
        jsonschema.validate(e, schema)                       # the contract
        assert passes._validate_dro(json.loads(json.dumps(e))) == [], k   # the runtime
        assert e["business_id"].startswith("exemplar:"), k
        assert e["narrative"] and e["summary_for_practitioner"], k
        ids = [s["signal_id"] for s in e["signals"]]
        assert sorted(ids) == sorted(sig.signal_ids()), k    # one entry per signal
        for s in e["signals"]:
            assert sig.is_consumable(s["confidence"]), (k, s["signal_id"])
            assert s["source"] in sig.SIGNAL_SOURCES, (k, s["signal_id"])
            meta = sig.SIGNALS[s["signal_id"]]
            allowed = meta["values"]
            if isinstance(allowed, str):                     # the spectrum
                assert 0.0 <= float(s["value"]) <= 1.0, (k, s["signal_id"])
            elif meta.get("free_text"):
                assert isinstance(s["value"], str) and s["value"], (k, s["signal_id"])
            elif meta.get("multi_select_max"):
                vals = s["value"] if isinstance(s["value"], list) else [s["value"]]
                assert 1 <= len(vals) <= meta["multi_select_max"], (k, s["signal_id"])
                assert all(v in allowed for v in vals), (k, s["signal_id"], vals)
            else:
                assert s["value"] in allowed, (k, s["signal_id"], s["value"])


def _values_seen(lib, signal_id):
    seen = set()
    for e in lib.values():
        for s in e["signals"]:
            if s["signal_id"] == signal_id:
                v = s["value"]
                seen.update(v if isinstance(v, list) else [v])
    return seen


def test_every_enumerated_signal_value_has_a_worked_example():
    lib = _lib()
    for sid, meta in sig.SIGNALS.items():
        allowed = meta["values"]
        if isinstance(allowed, str):
            continue
        missing = set(allowed) - _values_seen(lib, sid)
        assert not missing, f"{sid}: no exemplar shows {sorted(missing)}"


def test_every_axis_value_has_a_worked_example():
    lib = _lib()
    enums = passes._decision_enums()
    for axis in sig.DISTINCTIVENESS_AXES:
        dec, field = axis.split(".")
        seen = {e["decisions"][dec][field] for e in lib.values()}
        missing = set(enums[dec][field]) - seen
        assert not missing, f"{axis}: no exemplar uses {sorted(missing)}"


def test_no_two_exemplars_collide_and_stated_nearest_is_measured():
    lib = _lib()
    sigs = {k: passes.distinctiveness_signature(e) for k, e in lib.items()}
    for k, e in lib.items():
        shared = {o: passes._shared_axes(sigs[k], sigs[o]) for o in lib if o != k}
        worst = max(shared.values())
        assert worst < sig.DISTINCTIVENESS_COLLISION_THRESHOLD, (k, shared)
        stated = e["anti_convergence"]["distinctiveness_check"]["axes_shared_with_nearest"]
        if k in NEW:
            assert stated == worst, (k, stated, shared)
            compared = e["anti_convergence"]["distinctiveness_check"]["compared_against"]
            assert all(o in lib for o in compared), k


def test_one_exemplar_per_wider_shelf_language_and_choices_are_real():
    lib = _lib()
    choices = {}
    for k in NEW:
        lang = lib[k]["decisions"].get("language") or {}
        assert lang.get("choice") in dl.LANGUAGES, (k, lang)
        assert lang.get("because"), k
        choices[lang["choice"]] = k
    assert set(choices) == {"broadsheet", "signal", "atelier", "neon", "hearth",
                            "glass", "runway", "arena"}


def test_selector_reaches_each_new_exemplar_as_nearest_for_its_own_signals():
    lib = _lib()
    for k in NEW:
        picks = passes._select_exemplars(lib[k]["signals"])
        assert picks and picks[0]["exemplar_id"] == k, (k, [p["exemplar_id"] for p in picks])
        assert len(picks) == 2 and picks[1]["exemplar_id"] != k
