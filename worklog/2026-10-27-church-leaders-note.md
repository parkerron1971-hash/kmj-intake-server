---
title: The Monday leaders note — this week, what's needed and one win, emailed to the church's leaders (server)
date: 2026-10-27
agent: Claude Code (Claude Opus 5.5)
asked: 'The leadership plan (artifact D68g78Hu7ULPXpwgkg1v5Y) and its meeting playbook (Evd8431XHqafeFpSXSgCFr) → Kevin, 2026-10-27: "let''s build"'
status: shipped, switched off (platform owner only until a Thursday)
prs: [kmj-intake-server#1619, solutionist-studio#1390]
migrations: []
left_undone:
  - "Switch-on: CHURCH_LEADERS_NOTE=on on Railway on a Thursday (it defaults to owner), with the app's What's New entry"
  - "No reminder on Monday morning that the note is waiting (no push, no Needs-you row)"
  - "Email only: the leaders' chat can't carry it (a chat message needs a member sender)"
  - "Chief can't draft, read or send the note (no action handler)"
  - "The last send only is kept (businesses.settings.church_leaders_note); there is no history of earlier weeks"
decisions:
  - "Lane: Build, Kevin's direct ask on the leadership plan"
  - "A leader's reply goes to whoever sent the note (their sign-in email as reply_to), not a no-reply box: What's needed asks for answers"
  - "No model call: the draft is assembled from rows. This week = the church's next seven days (today and six more) on its clock (business_marketing.business_tz via group_gatherings.zone, the clock Sunday Planning and the groups read; chief_assignments._tz_for falls back to UTC). A clock that can't be read is a 503"
  - "This week reads where the church calendar reads: worship_services (archived and templates out), Services & Events occasions (an invite-only one stays out of a note to every leader), rooms booked (booked only; a rental is said as 'booked for a rental', never its renter), and the groups that meet (meet_day, every other week, monthly, skips) on one line. A plan and its own occasion are said once (same day, within two hours); a room booked under a gathering's name is folded in as its place"
  - "What's needed: places still open on the Sunday teams for each plan in the days (no one, offered to the team, or a no: the schedule page's rule) by team, and how many were asked and haven't answered; an event's roles short (events_rsvp_router.role_fill); people in follow-up with no one, as a count. Nothing else, never invented. The win is blank"
  - "Recipients: member_portal_messaging.leaders_room_people (called, not changed), as the church's people: one email per address however many share it; the names of those with no email are listed. Email through email_layout + email_sender.send_via_resend with the church's identity, a key per send per person, reply_to none (as every church office email)"
  - "Who: owner, admins and managers (assert_access 'manager'), churches only, and with Who sees what on a manager must work the Office (church_spaces' rule). Below a manager, another church, or not a church: 404; a manager without the Office: 403; the status route says enabled false for all of them"
  - "Once a week: one send per church per Monday-start week on its clock. The send claims the week first in businesses.settings.church_leaders_note (fresh read, merged into the live settings, the PATCH filtered on the note's id or its absence, so two presses or two people send once), then emails; if nothing went the claim is let go (the earlier week's record put back). A second send that week is a 409 that says when it went, by whom, and when the next can go. rate_limit 'church_leaders_note_send' (4 an hour per church) stops a loop of failing tries"
  - "Kept per send: id, week, state, sent_at, by and by_name, sent, no_email, failed, subject and text (8,000 letters at most). No table, no migration"
related: [2026-10-27-church-board.md, 2026-10-27-church-spaces.md, 2026-10-26-who-sees-what.md]
---
- `church_leaders_note.py` (new): the switch (`CHURCH_LEADERS_NOTE` off | owner | on,
  owner by default, like `church_board.py`), who may send, the draft (this week,
  what's needed, an empty win, a subject), the recipients, the email (each heading
  set apart with a rule in the church's colour, a day's line in bold, what was typed
  escaped), and the once-a-week send. Three routes under `/church/leaders-note`:
  `GET /status` `{enabled}`, `GET` the draft with the recipients, counts and the last
  send, `POST /send` `{business_id, subject, text}`.
- `kmj_intake_automation.py`: mounts the router after Board & minutes (before the
  public site's catch-all). `rate_limit.py`: the `church_leaders_note_send` bucket.
  `.env.example`: `CHURCH_LEADERS_NOTE`.

Checks:
- `__tests__/test_church_leaders_note.py`: 18 tests (the owner, an admin and a manager
  in; a member, a viewer, a stranger and another church's manager out; a manager
  without the Office out while Who sees what is on, and an areas read that fails is a
  503; not a church; the switch; the draft from a week of fake rows across the clocks
  going back, with what stays out; a quiet week empty, never invented; a full Sunday
  says nothing; every failed read a 503; one email an address and who has none; the
  email's headings and escaping; no one with an email refused before the week is
  taken; a failed email named while the rest go; once a week with the other settings
  untouched, Sunday night still that week, Monday a new one; the week freed when
  nothing went; a send made in between never overwritten; tries held to a few an
  hour; a subject and words needed; the joined text matches the app's).
- The access ratchet, ownership sweep segments, route type hints, seat access,
  step-up scopes, Board & minutes and Help requests pass.
