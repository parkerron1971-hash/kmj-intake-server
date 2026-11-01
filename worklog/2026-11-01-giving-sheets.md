---
title: The paper count sheet, and a photo of it read into a draft (giving by service, step 4 server)
date: 2026-11-01
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-01: "I want to create a way for churches that have sheets they want to feel out as hard copy for their records to be able to print out a sheet they want to use that the system produced and then have a way to take a picture of those sheets and it upload into the system and automatically updated based on that person giving... we could store those pictures and the data for future checks and balances" then "build everything"'
status: in review
prs: ["kmj-intake-server (this PR)"]
migrations: [supabase/APPLY-2026-11-01-giving-sheet-photos.sql (applied 2026-11-01)]
left_undone:
  - "Switched with GIVING_SERVICES (owner until a Thursday flip)"
  - "The screens (Print sheet, Photo of the sheet, the draft beside the photo) are the front end PR"
  - "Each photo read is one Claude call (Sonnet 5.5, metered as giving_sheet_read): not yet measured for a price"
decisions:
  - "The sheet: the church and the service with its date, numbered lines (name, fund, cash, check, check #), the church's funds as a key, cash by bill and coin, totals, two counters' signatures; printable, never cached"
  - "A photo is kept FIRST (private bucket giving-sheets, never public; signed links for 15 minutes), then read; a photo that can't be read is still kept, with what went wrong"
  - "The reading is a DRAFT, never gifts: each name matched only when it is one person (whole name, else first and last), a line with cash and a check split in two, unknown funds and hard-to-read lines flagged, the sheet's written totals checked against the rows. Handwriting misreads are why nothing is saved straight from a photo"
  - "A misread amount is kept as read, not quietly capped: saving it is refused with a reason"
  - "Used: the photo is tied to the gifts its draft became (only this count's), the trail from sheet to photo to gifts"
  - "Limits: llm_call metering, the spend guard, a per-church rate limit and the unit gate, as reading a PDF statement"
related: [2026-11-01-giving-services.md]
---
`giving_sheets.py` (new), `kmj_intake_automation` (router), `account_lifecycle`,
`docs/MIGRATIONS.md`. Tests: `__tests__/test_giving_sheets.py` (10).
