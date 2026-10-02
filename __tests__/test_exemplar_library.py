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

from agents.composer import drl
from agents.composer.drl import passes, signals as sig
import design_languages as dl

try:                      # CI has no jsonschema — the walker below is the contract
    import jsonschema     # pragma: no cover
except ImportError:       # pragma: no cover
    jsonschema = None


_TYPES = {"object": dict, "array": list, "string": str, "integer": int,
          "number": (int, float), "boolean": bool}


def _walk(node, value, path="$"):
    """The subset of JSON Schema that schema.json actually uses — required,
    properties, enum, const, type, maxLength, minimum/maximum, items —
    raised as one AssertionError naming the path. No dependency."""
    if "const" in node:
        assert value == node["const"], f"{path}: {value!r} != const {node['const']!r}"
    if "enum" in node:
        assert value in node["enum"], f"{path}: {value!r} not in {node['enum']}"
    t = node.get("type")
    if t:
        py = _TYPES[t]
        ok = isinstance(value, py) and not (t in ("integer", "number") and isinstance(value, bool))
        assert ok, f"{path}: expected {t}, got {type(value).__name__}"
    if isinstance(value, str) and "maxLength" in node:
        assert len(value) <= node["maxLength"], f"{path}: {len(value)} > maxLength {node['maxLength']}"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in node:
            assert value >= node["minimum"], f"{path}: {value} < {node['minimum']}"
        if "maximum" in node:
            assert value <= node["maximum"], f"{path}: {value} > {node['maximum']}"
    if isinstance(value, dict):
        for req in node.get("required", []):
            assert req in value, f"{path}: missing required {req!r}"
        for k, sub in node.get("properties", {}).items():
            if k in value:
                _walk(sub, value[k], f"{path}.{k}")
    if isinstance(value, list) and "items" in node:
        for i, item in enumerate(value):
            _walk(node["items"], item, f"{path}[{i}]")


def validate_against_schema(record, schema):
    _walk(schema, record)
    if jsonschema is not None:
        jsonschema.validate(record, schema)


def test_the_walker_is_a_real_alarm():
    """Rehearsal inside the test: a record that breaks the schema must
    trip the walker (a passing validator is what a broken one looks like)."""
    schema = drl.load_schema()
    good = json.loads(json.dumps(drl.load_exemplars()[0]))
    validate_against_schema(good, schema)
    bad = json.loads(json.dumps(good))
    bad["decisions"]["palette"]["base"] = "hot_pink"
    try:
        _walk(schema, bad)
    except AssertionError as e:
        assert "palette.base" in str(e)
    else:
        raise AssertionError("walker accepted an out-of-enum palette.base")
    bad = json.loads(json.dumps(good))
    del bad["summary_for_practitioner"]
    try:
        _walk(schema, bad)
    except AssertionError as e:
        assert "summary_for_practitioner" in str(e)
    else:
        raise AssertionError("walker accepted a record missing a required key")


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
        validate_against_schema(e, schema)                   # the contract
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
