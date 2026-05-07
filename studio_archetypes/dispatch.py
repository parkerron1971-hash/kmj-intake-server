"""Archetype dispatcher — routes archetype id to renderer."""
from __future__ import annotations
from typing import Optional


def render_archetype(archetype_id: str, context: dict) -> Optional[str]:
    """Render the archetype matching archetype_id. Returns None on unknown id
    or any render failure. Logs traceback on failure for debugging."""
    try:
        if archetype_id == "split":
            from studio_archetypes.split import render
        elif archetype_id == "editorial-scroll":
            from studio_archetypes.editorial_scroll import render
        elif archetype_id == "showcase":
            from studio_archetypes.showcase import render
        elif archetype_id == "statement":
            from studio_archetypes.statement import render
        elif archetype_id == "immersive":
            from studio_archetypes.immersive import render
        elif archetype_id == "minimal-single":
            from studio_archetypes.minimal_single import render
        else:
            return None
        return render(context)
    except Exception as e:
        import sys
        import traceback
        print(f"[archetype dispatch] {archetype_id} render failed: {e}", file=sys.stderr)
        traceback.print_exc()
        return None
