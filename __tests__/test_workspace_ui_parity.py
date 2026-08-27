"""
test_workspace_ui_parity.py — the client registry and the server registry
must name the same six things.

This is the seam where a layout that validates on the server renders a
blank box in the app. The server's validator is authoritative about what a
legal layout IS; the client's registry decides what actually gets drawn. If
those two sets drift, the failure is silent and lands in front of a
practitioner.

Parsed with a regex rather than a JS runtime on purpose — this repo has no
node in its test path, and adding one to guard a six-line map would cost
more than it protects.
"""
from __future__ import annotations

import os
import re

import pytest

import workspace_layouts
import workspace_primitives as registry

_UI_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "workspace_ui"
)
_REGISTRY_JS = os.path.join(_UI_DIR, "primitiveRegistry.js")


def _read(path: str) -> str:
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def _client_primitive_ids():
    src = _read(_REGISTRY_JS)
    block = re.search(r"export const PRIMITIVES = \{(.*?)\n\};", src, re.S)
    assert block, "PRIMITIVES map not found in primitiveRegistry.js"
    return set(re.findall(r"^\s*(\w+):", block.group(1), re.M))


def test_the_registries_name_the_same_primitives():
    assert _client_primitive_ids() == set(registry.ids())


def test_the_registries_agree_on_roles():
    src = _read(_REGISTRY_JS)
    roles = re.search(r"export const ROLES = \[(.*?)\];", src, re.S)
    assert roles
    client = [r.strip().strip("'\"") for r in roles.group(1).split(",") if r.strip()]
    assert client == list(registry.ROLES)


@pytest.mark.parametrize("primitive", sorted(registry.ids()))
def test_every_primitive_has_a_component_file(primitive):
    component = "".join(part.capitalize() for part in primitive.split("_"))
    path = os.path.join(_UI_DIR, "primitives", f"{component}.jsx")
    assert os.path.exists(path), f"{primitive} has no {component}.jsx"


@pytest.mark.parametrize("primitive", sorted(registry.ids()))
def test_no_primitive_fetches_its_own_data(primitive):
    """The rule from the brief: each takes a declared data contract and
    renders it. A primitive that can fetch has to know whose data it is
    looking at, and that knowledge does not belong in the render tree."""
    component = "".join(part.capitalize() for part in primitive.split("_"))
    src = _read(os.path.join(_UI_DIR, "primitives", f"{component}.jsx"))

    for forbidden in ("fetch(", "axios", "useQuery", "useSWR", "supabase",
                      "XMLHttpRequest", "useEffect"):
        assert forbidden not in src, f"{component}.jsx reaches for {forbidden}"


@pytest.mark.parametrize("primitive", sorted(registry.ids()))
def test_every_primitive_binding_is_a_declared_prop(primitive):
    """Every binding the server can send must be destructured by the
    component. A binding the component ignores is a contract the validator
    is enforcing for nothing."""
    component = "".join(part.capitalize() for part in primitive.split("_"))
    src = _read(os.path.join(_UI_DIR, "primitives", f"{component}.jsx"))

    for binding in (registry.PRIMITIVES[primitive].get("bindings") or {}):
        assert re.search(rf"\b{binding}\b", src), (
            f"{component}.jsx never reads binding {binding!r}"
        )


def test_only_one_renderer_exists():
    """The structural claim. One engine reads the schema and produces every
    workspace — if a second renderer appears, the vertical has escaped the
    data."""
    renderers = [
        f for f in os.listdir(_UI_DIR)
        if f.endswith(".jsx") and "render" in f.lower()
    ]
    assert renderers == ["WorkspaceRenderer.jsx"], renderers


def test_the_renderer_has_no_per_vertical_branching():
    """If you find yourself writing per-vertical layout code, the design has
    failed. This is that assertion, mechanised."""
    src = _read(os.path.join(_UI_DIR, "WorkspaceRenderer.jsx"))
    for archetype in workspace_layouts.ARCHETYPES:
        assert f"'{archetype}'" not in src and f'"{archetype}"' not in src, (
            f"WorkspaceRenderer branches on {archetype!r}"
        )
    # And it must not switch on primitive slugs either — that is what the
    # registry lookup is for.
    for primitive in registry.ids():
        assert f"'{primitive}'" not in src and f'"{primitive}"' not in src, (
            f"WorkspaceRenderer branches on {primitive!r}"
        )


def test_the_renderer_resolves_bindings_in_one_place():
    src = _read(os.path.join(_UI_DIR, "WorkspaceRenderer.jsx"))
    assert src.count("surface.bindings") == 1, (
        "bindings are read in more than one place; the renderer is the only "
        "thing that should know what a binding is"
    )
