"""Pass 3.7c motion-richness modules.

Each module exposes some subset of:
    render_styles(design_system?) -> CSS string (include once per page)
    render_script() -> JS string (include once per page, near </body>)
    render_inline(...) -> per-instance HTML

Layouts call these conditionally based on the generated decoration scheme's
motion_richness flags. When a scheme is absent, layouts render exactly as
they did before Pass 3.7c.
"""
