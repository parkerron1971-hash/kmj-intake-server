"""Pass 4.0b.5 — Slot system.

A slot is a replaceable image position in a generated site. Builder
Agent emits `<img data-slot="<name>" src="" alt="...">` tags; the
slot system populates them at render time from one of three sources:

  - placeholder  — styled empty rectangle (profile slots; user uploads)
  - unsplash     — atmospheric/contextual photography from Unsplash
  - dalle        — DALL-E generated decorative textures / abstracts

Persistence lives at business_sites.site_config.slots[slot_name].
Resolution is server-side only — the frontend never sees Unsplash or
DALL-E URLs directly. A custom-uploaded image always wins over the
default; clearing the custom upload reverts to the default suggestion.

Submodules:
  slot_definitions  — canonical SLOT_DEFINITIONS taxonomy (11 slots)
  slot_resolver     — pure resolve_slot_url() for the render layer
  slot_storage      — Supabase read/modify/write helpers
"""
from __future__ import annotations
