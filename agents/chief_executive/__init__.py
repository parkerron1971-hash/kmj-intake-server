"""Pass 4.0d PART 2 — Chief Executive layer.

Single conversational surface (POST /chief/message) that classifies
the practitioner's message via Sonnet, then dispatches to the right
backend specialist:

  design_refine     → /director/refine (Director regenerate)
  content_edit      → /chief/override (text override, PART 1)
  color_swap        → /chief/override (color_role override, PART 1)
  slot_change       → /slots/{biz}/{slot}/* (slot system, returned as
                       a frontend-action stub in PART 2; the slot
                       endpoints already accept practitioner requests
                       directly so Chief just surfaces what the user
                       intended)
  operational_task  → STUB in PART 2 (future Chief task creation)
  scheduling        → STUB in PART 2 (future Chief scheduling)
  briefing_request  → STUB in PART 2 (future Chief briefing fetch)
  multi_intent      → split + process sequentially
  ambiguous         → request clarification (confidence below threshold)

Modules:
  intent_classifier — Sonnet pre-processor producing JSON
  dispatcher        — per-intent handler functions
  router            — FastAPI router (mounts /chief/message)

Decisions (from planning doc + unattended choices flagged in commit):
  - Sonnet model claude-sonnet-4-5-20250929 (matches existing agents)
  - temperature=0.2, JSON-only output
  - Confidence threshold 0.6: below → ambiguous + clarification
  - dry_run mode (default False) lets test cases verify dispatch
    without firing expensive Builder runs
  - Specialist failure surfaces honestly in the response (status per
    intent), no false-positive "success"
"""
