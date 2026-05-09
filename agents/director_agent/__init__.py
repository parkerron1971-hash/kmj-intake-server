"""Pass 4.0b — Director Agent: Critique loop.

Scores generated HTML against a Design Intelligence Module's rubric
(Pass 4.0a / 4.0b PART 1) and returns a punch list of violations the
Builder Agent can regenerate against.

Two layers:
  deterministic_checker — Layer 1 rules (CSS thresholds, HTML structure,
                          text patterns, global page patterns)
  llm_judge             — Layer 2 rules (qualitative judgments via Sonnet)

Composed by `critique_site` in `critique.py` and exposed via
`POST /director/critique` in `router.py`.
"""
