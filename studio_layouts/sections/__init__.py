"""Shared vocabulary-aware section renderers used by Smart Sites layouts.

Each section module exposes a `render(...)` function that takes the
design_system + section content and returns vocabulary-adapted HTML.
Layouts call into these by default; bespoke layout-specific overrides
live in the layout modules themselves and are passed through the
`render_*_section` dispatch helpers in studio_layouts/shared.py.
"""
