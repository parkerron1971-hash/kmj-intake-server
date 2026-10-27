---
title: A member's help ask can say how much
date: 2026-10-27
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-10-27: "create a path for members to be able to request these things from the church app" → Ask the church (#1609) and Help requests (#1610); the help worker found the ask had no amount field'
status: shipped, behind CHURCH_MEMBER_ASKS (owner until Thursday)
prs: [kmj-intake-server (this PR)]
migrations: []
left_undone: []
decisions: ["Optional, as typed (\"180\", \"$1,200.50\"), kept as plain dollars in submission.amount; church_help.from_ask already reads it as the amount asked", "Only on a help ask; a visit or life event never carries one, whatever is sent"]
related: [2026-10-27-member-asks.md, 2026-10-27-church-help.md]
---
`member_asks.py`: the Ask for help page has "How much, if you know
(optional)"; a bad amount says how to type it. `__tests__/test_member_asks.py`
covers it, including Help requests reading it as 118050 cents.
