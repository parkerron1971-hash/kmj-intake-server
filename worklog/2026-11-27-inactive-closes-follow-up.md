---
title: Marking someone inactive closes their follow-up and takes them off the Welcome Path
date: 2026-11-27
agent: Claude Code (Claude Opus 5.5)
asked: "Kevin said yes to all of your proposal; it's now mission M-5 ... rank 1: marking a contact inactive or 'not a guest' closes their open church_follow_ups and takes them off the Welcome Path" (relayed by KAI)
status: in progress
prs: []
migrations: []
left_undone: ["Needs a look's 'Not a guest' / 'Scam' buttons (another worker, inbound_hold.py) should call church_follow_up.close_for_contact"]
decisions: ["the status is read where it matters (the follow-up sweep, every scheduled New here text), not hooked on each screen that changes it: some screens write the contact straight to the database", "inactive and churned both count", "a close that doesn't save waits for the next sweep and is never nudged in between"]
related: [kai/reviews/inbound-safety-proposal.md (Solution Space)]
---
Two website connect cards at Love City (11-22 and 11-26) were one sales
campaign, not guests. The office marked the first one inactive on 11-23, but
his follow-up stayed open and kept climbing ("hasn't been reached" two days
later). Now:

- the church follow-up sweep reads each person's status and closes the open
  follow-ups of anyone marked inactive or churned, with Chief's note, before
  anyone is told or nudged;
- `new_here.run_scheduled` refuses any Welcome Path / New here text to
  someone marked inactive, and `new_here.leave_path` cancels their queued ones;
- `church_follow_up.close_for_contact(biz, contact, by_user=, by_name=, why=)`
  closes everything open for one person: the helper Needs a look's "Not a
  guest" and "Scam" call.

Mission M-5 step 1 (Fixes). The other M-5 fixes ship in their own PRs per desk.
