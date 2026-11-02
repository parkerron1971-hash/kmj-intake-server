---
title: In a church, the office's jobs open to whoever holds the duty
date: 2026-11-01
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-01: "yes the duties part would be great" (docs/CHURCH_DUTIES.md step 2a, the office gates; approved)'
status: in review
prs: [kmj-intake-server (this PR)]
migrations: []
left_undone:
  - "FE (step 4): the buttons follow my-role.duties. Until then the app still shows what it showed: Rooms' Rentals tab reads `rentals` (money, owner and admins); the list a rooms Manager may read is the new `rental_list`. The Messaging page shows its switch to the owner only."
  - "Event sign-ups: one PUT carries prices with places, the deadline and the questions, so the whole setup stays the owner's and admins'. Splitting the free settings out would let whoever does the events open a free sign-up."
  - "church_duties.py's docstring still says nothing calls require(); left for whichever of 2a and 2b lands second, so the two PRs don't collide on one line."
  - "Step 2b (the marketing desk, clips, the site and the events page, ChurchSavvy parts) is another session's PR."
decisions:
  - "Churches only (church_follow_up.is_church). Any other business keeps its gate exactly: the weekly text is still assert_access(admin) first, chat rules still the owner only, with the same refusals."
  - "Only a Manager's answer reads a duty; the owner and admins pass by role, Members and Viewers keep their old refusals (they hold no duty, so a duty's 'give it to you' line would mislead them)."
  - "The weekly text's gate (_may_announce) tries admin first; below that, only a church's Manager seat goes on to the duty, so a stranger or a Member still gets the same 404. The keyword (/sms/keyword) stays admin-only: it is the church's inbound identity, not the weekly text."
  - "The scheduled announcement checks at send time that its author is still the owner, an admin, or a church Manager holding weekly_text; a duty that can't be read leaves it unsent."
  - "meetings makes a Manager a boss on the board pages (setup and every board, writes included, as the owner and admins); board members' own rules and the member app's Board tab are unchanged."
  - "rooms replaces the Office-area check for Managers (Office & Leadership and Sunday & Serving by default); Member and Viewer logins still go by the Office area. The Rentals list opens to a rooms Manager with fee_cents, deposit_cents, invoice_id and the bill left out; fees and bills stay the owner's and admins'."
  - "events: the duty's area is Website & outreach while the old gate was the Office area, so a Manager no lane names also keeps the Office area's yes until the church moves the events (nobody loses access). The Office & Leadership lane no longer reads sign-ups by default (the catalog gives events to Sunday & Serving and Media); the Executive Pastor and the admins still do."
  - "A failed duty read is a 503 everywhere; the status routes that already turned a 503 into 'off' still do (board, rooms, leaders note); sign-ups' status raises it, as before."
  - "Tests: conftest clears church_duties' minute cache between tests (only if the module is loaded), since test files share church and login ids."
related: [2026-11-01-church-duties.md]
---
Six gates read `church_duties` (docs/CHURCH_DUTIES.md, "The office's gates"):
`sms_routing._may_announce` and `run_scheduled_announcement` (weekly_text),
`church_board._access` (meetings), `messaging_router._chat_rules_keeper`
(chat_rules), `church_spaces._access` and the Rentals list (rooms),
`church_event_signups._office` (events), `church_leaders_note._access`
(leaders_note). Each module's tests gained the duty cases (the owner, an
admin, the lane's Manager, a Manager the duty moved away from, a Manager no
lane names, a failed read; for the weekly text and chat rules, a business
that isn't a church), and the tests that pinned the old Office-area and
admin-only checks were updated. No migration, no FE change.
