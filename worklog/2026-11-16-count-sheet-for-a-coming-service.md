---
title: The count sheet prints for a service that hasn't come yet
date: 2026-11-16
agent: Claude Code (Claude Fable 5.2)
asked: "Kevin, 2026-11-16, about Elevation of Grace, which had just subscribed: \"the giving sheets like was in my giving area. i didn't see it for their church only for my church.\" Told why and offered the change: \"yes make that change and push it now instead of thursday.\""
status: shipped
prs: [kmj-intake-server (this PR), solutionist-studio (the Print sheet button under Coming up)]
migrations: []
left_undone:
  - "Not seen on Elevation of Grace's own login: reading their church with the service key was not permitted. The cause given to Kevin (no services entered, so no counts, so no sheet) is from the code, not from their screen."
  - "A church with no services entered has no sheet to print: the sheet needs a service to name."
  - "Nothing reads the code printed on a sheet, so a sheet printed ahead says 'Printed ahead of the day' in its place."
decisions:
  - "Print only, no early count. A count is made when its day comes, and a collecting count's online-gift window is worked out from the counts already made (giving_services.online_window); a count made days early would have moved those windows. GET /giving/{business}/services/{service}/sheet?date= renders the same sheet_html under the service's name and day, makes no count and records nothing."
  - "Only a day the service really meets, from today through COMING_DAYS (the days the screen lists as coming up); anything else is 404. Same gate as the counts (_gate: the switch, finance people, the giving keeper)."
  - "GIVING_SERVICES has been on for every church since 2026-11-13, so this is live for every church when it deploys. Shipped on a Monday on Kevin's word: the church's first Sunday is 2026-11-22."
related: []
---
`giving_sheets.py`: `coming_sheet` (the new route) and one change in
`sheet_html` (a sheet with no count id says "Printed ahead of the day").
Tests: `__tests__/test_giving_sheets.py`, the last section.
