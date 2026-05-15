"""Pass 4.0f spike — Cathedral Hero Component Library.

Top-level namespace for module-specific component libraries. Currently
hosts `cinematic_authority/`, the first module to receive a variant-based
component approach.

Architectural model: each design module under design_modules/ owns:
  - hero/                  variant taxonomy + primitives + treatments
  - about/, services/, …   (future) one folder per major section
  - <render entry points>  pure-function HTML composition

The Composer Agent (agents/composer/) selects from these variants per
business; the render layer produces HTML strings. Replaces Builder
Agent's bespoke-HTML generation with deterministic composition.

This is spike code on branch pass-4-0f-spike-cathedral-hero — NOT
merged to main until the go/no-go decision after Phase 6.
"""
