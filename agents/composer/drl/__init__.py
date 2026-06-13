# agents/composer/drl/ — Design Rationale Layer.
# PR1: foundation only — schema, signal taxonomy, principles, exemplars.
# The signal-detection + DRO-authoring passes (PR2) and prompt surgery
# (PR3) consume these. See docs/design_rationale_layer.md.

import json
import os
from functools import lru_cache
from typing import Any, Dict, List

from . import signals  # noqa: F401  (re-export the taxonomy module)

_HERE = os.path.dirname(os.path.abspath(__file__))
_EXEMPLAR_DIR = os.path.join(_HERE, "exemplars")


@lru_cache(maxsize=1)
def load_schema() -> Dict[str, Any]:
    """The DRO JSON Schema (validation target for the authoring pass)."""
    with open(os.path.join(_HERE, "schema.json"), encoding="utf-8") as f:
        return json.load(f)


@lru_cache(maxsize=1)
def load_principles() -> str:
    """The translation principles, verbatim — included in the authoring prompt."""
    with open(os.path.join(_HERE, "principles.md"), encoding="utf-8") as f:
        return f.read()


@lru_cache(maxsize=1)
def load_exemplars() -> List[Dict[str, Any]]:
    """The annotated exemplar library (E1–E4), as DRO records + narrative.
    Consulted by signal similarity, never by vertical (spec §4)."""
    out: List[Dict[str, Any]] = []
    for name in sorted(os.listdir(_EXEMPLAR_DIR)):
        if name.endswith(".json"):
            with open(os.path.join(_EXEMPLAR_DIR, name), encoding="utf-8") as f:
                out.append(json.load(f))
    return out


def exemplar_ids() -> List[str]:
    return [e.get("exemplar_id", "") for e in load_exemplars()]
