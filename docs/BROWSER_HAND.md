# The browser hand moved to Chief's computer

See [CHIEF_COMPUTER.md](CHIEF_COMPUTER.md) for the active architecture, controls,
privacy limits, configuration, migrations and rehearsals.

`use_browser_hand` is a compatibility name for a portal errand plan. It keeps the
Approval Queue on channel `hand`; a person approves before a job can run. Portal
jobs use the same controller and Secure Entry as reorders, with purchases disabled.
Old queue proposals can be converted only when a person explicitly approves them.

The old screenshot/JSON model loop is retired. New `browser_hand` jobs are rejected;
a stale queued job returns a retirement message without opening a browser. Historic
job records and their private frame viewer remain available.
