---
title: The count sheet has a Given by app section, and the photo reader reads it
date: 2026-11-01
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-01: "can we also update the sheet. possibly add a way for cash app or other ways could be read only because those giving won''t be seen in the system directly so we need to come up with a way on the sheet" then "yes build the sheet section and the zelle suggestions."'
status: in review
prs: ["kmj-intake-server (this PR)"]
migrations: []
left_undone:
  - "The screen treats an app row from the photo (its method is the app) in the front end PR"
  - "Switched with GIVING_SERVICES (owner until a Thursday flip)"
decisions:
  - "A second section, Given by app (not in the plate): name, the app as printed checkboxes, fund, amount, a note (last 4); its own Apps total. App gifts never pass through the plate, so they stay out of the counters' cash and checks"
  - "The checkboxes are the church's own apps from Settings, Giving (Cash App, Zelle, Venmo, PayPal, apps named under Other); Subsplash isn't one (its gifts arrive on their own); none set: the usual four"
  - "The reader returns app_lines; each becomes a row whose method is the church's app (menu id, e.g. cashapp, other:Givelify), an app that isn't the church's flagged (app_known false); the sheet's Apps total is checked against the rows"
  - "One page on letter: 15 plate lines (was 24) and 6 app lines (measured 903px of about 979 printable). More gifts than lines: print another sheet for the same service; every photo goes into the same count (the sheet says so)"
  - "At most 5 app boxes a line (labels cut at 24 characters), then Other ______; the cell wraps, so a church with many apps still prints one page"
  - "An app the church doesn't list keeps its name (method other:<name>, so the gift is saved through that app by name), flagged for the treasurer"
related: [2026-11-01-giving-sheets.md]
---
`giving_sheets.py` (sheet_apps, the sheet, SHEET_TOOL app_lines, draft_from). Tests:
`__tests__/test_giving_sheets.py` (14).
