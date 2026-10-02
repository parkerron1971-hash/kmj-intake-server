---
title: Marketing desk streamlined, Chief proactive about the week
date: 2026-10-02
agent: Claude Code (Claude Opus 5.5)
asked: "check out the marketing engine under mission control ... streamline the function so there is a smooth flow. chief should be involved and proactive ... I approve this"
status: in progress
prs: [kmj-intake-server#1204, solutionist-studio (paired desk rebuild, branch marketing-flow-fe)]
migrations: []
left_undone: ["frontend desk rebuild (This week view, review by idea, Chief drawer, theme vars) ships in the paired solutionist-studio PR", "tenant version: per-business config/credentials/domain/signals (docs/MARKETING_DESK.md lists the blockers)"]
decisions: ["next week is planned Thursday 7:00 AM ET on purpose", "approving stays the owner's: Chief has no approve action", "the seven-caption generator (POST /week) is retired; the weekly plan is the one way a week is drafted", "the second Meta posting path comes off the desk", "a post means one idea on every channel"]
related: []
---
Kevin approved the redesign canvas https://claude.ai/artifact/R4YcBsj9xwtAgyDFsj19pW.

Backend changes:
- `marketing_desk.py` computes Chief's read, the masthead, the "needs a look"
  list, Today's marketing items, the Mission Control Chief digest and the
  owner pushes, all from rows.
- Today used to count the platform business's content calendar, a different
  pipeline, so the weekly plan's drafts never reached it.
- The plan used to land Thursday at 10:00 by accident. It now runs Thursday
  at 7:00 AM on purpose.
- A storage blip before sending used to strand a post as "uncertain". It now
  goes back to approved and is retried. `/not-sent` is the exit for a post
  that really is unconfirmed.
- New endpoints `/slot/edit` and `/slot/cancel` change one idea on every
  channel, checking every channel before writing.

A read-only production probe showed the new wording on Kevin's real data:
"Next week is drafted", "Five posts wait for your OK", and "Three posts from
this week missed their time".

Before building more here, read docs/MARKETING_DESK.md.

Later the same day Kevin found his approved post on Instagram, not Facebook:
the editor had preselected one account. New posts (the desk's and Chief's)
now go to every connected channel unless he chooses, at the next open slot
unless he picks a time (`/ideas`, `marketing_new_post`).
