---
title: The growth report in a church's and a nonprofit's words, and kept to their finance roles
date: 2026-10-16
agent: Claude Code (Claude Opus 5.5)
asked: 'fix the entire health area … I want this to make sense — the backend half Kevin agreed to with the frontend Giving health (solutionist-studio#1239)'
status: shipped
prs: [kmj-intake-server#1466, solutionist-studio#1239]
migrations: []
left_undone:
  - "Chief's client_health for a church still returns the contact-based at-risk/lapsed lists (now with a church_note saying they are not the church's drifting list); an attendance-based drifting read on the server would let Chief name the same people Who's drifting does"
decisions:
  - "growth_words.re_say relabels a finished report per voice (church: givers, nonprofit: donors): driver labels, the repeat-rate definition, the coverage warnings, plus a vocabulary note for the shared field names. Numbers untouched; the business voice is returned as built. Every driver gains a stable key in every voice"
  - "GET/POST /growth-intelligence for a nonprofit-family business (church or nonprofit) require a finance role (owner, admin, accountant) via giving_records.require_finance — the rule require_ministry_finance keeps for that family's books, bank and reports. Other businesses keep the any-seat (viewer/member) rule"
  - "Chief's growth_report and save_growth_record apply the same rule to the person in the turn; a run with no person in it reads no giving (as church_people refuses care numbers)"
  - "2026-10-27, refreshed onto main before Love City's office logins go out: the report is a Giving door. Where a church names a Giving & money keeper (church_keys, #1621), the route and Chief need the keeper's key, the owner and admins too; it is read for every type, so a church that changes its type keeps its keeper; keys that can't be read keep it shut"
related: [solutionist-studio/worklog/2026-10-16-church-giving-health.md]
---
A gift is stored as a paid invoice, so Chief read the growth report back
to a pastor as first-time buyers, purchase value and paid invoices. The
report now says new givers, how often they give, average gift and
anonymous gifts for a church (donors for a nonprofit), and carries a
vocabulary note so Chief speaks of gifts, never sales.

Per-person giving in this report was readable by any viewer seat; for a
church or nonprofit it now takes a finance role, on the route and in
Chief. Tests: __tests__/test_growth_words.py (8), rehearsed red by
removing each gate.

2026-10-27: refreshed onto main, and the report joins the Giving doors
(church_keys.wall on the route, church_keys.is_open in Chief). Tests:
five more in __tests__/test_growth_words.py.
