---
title: Who calls our guests (People & Care until a Welcome Team, or the church's own way, plus a backup)
date: 2026-11-20
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-20, on the Welcome Path mock: "by default the calls goes to people and care until we get a welcome team. of course allow this to be selected by any church as to how they want it done so there structure is unique to them", then "build"'
status: in review
prs: [kmj-intake-server#PENDING]
migrations: []
left_undone:
  - "The frontend sheet (GuestCallsSheet, opened from Text > New here and the Follow-up board) ships in its own solutionist-studio PR"
  - "The mock's 'Also tell' (kids desk, greeters on Saturday) and 'How Chief tells the caller' toggles are wave 2. settings.guest_calls.tell is stored and honored (app push, email) but no screen changes it yet"
  - "The call brief (Chief's short brief, one tap to call) is step 3; the caller's push and email say where the guest came in and when the call is due, nothing more"
  - "The Follow-up board's Hand to list still offers only role holders, so the office can't hand a guest to an office login by hand; Who calls our guests can"
  - "church_follow_up.remove_role (taking a person's last role) still sends everything of theirs back to the office, guest calls included, even when they are also an office login"
  - "settings.guest_calls joined the server keys in the two unapplied settings-guard files (APPLY-2026-11-17-settings-server-keys.sql and APPLY-2026-11-19-payroll-deposits.sql): if Kevin applied either before this merged, run it again (safe twice)"
decisions:
  - "Behind guest_path.switched_on and only for guest follow-ups (guest_path.is_guest_follow_up). Off is today's hand-off exactly"
  - "Who can be a caller: an office login (owner, Admin, Manager) as its person, or anyone holding an active church role. Nobody else can reach a follow-up (the Lead tab needs a role), so nobody else is offered or handed one"
  - "Order: a rule (pastor_ask, baptism, door:<door>), then the mode (person; team = fewest open guest calls; people_care), auto = People & Care until the church has a Welcome Team AND the office said yes (welcome_ok), then today's choose()"
  - "People & Care = a Manager login holding first_guests (fewest open guest calls first), else the owner. A login with no person record gets one, once, from its name and sign-in email (source office_login); an existing record with that email is used instead"
  - "A team is one of the church's groups of kind team/ministry (its people who can call) or a role two or more people hold (the deacons)"
  - "Marked assigned_by guest_calls:<route>, leader_role guest_calls (the welcome route keeps the role choose() picked). _sweep_handed leaves them to guest_calls.recheck, which re-hands by the same rules when the caller can't take it (login gone, duty moved, person or role gone), with a note; with the path off, back to the office"
  - "Due in due_days (default 2) at 6 PM church time. Ladder for the call: 9 AM on the due day the caller is reminded; a day late the backup takes it and both hear (no backup: today's chain); three days late, after a backup, the senior pastor (else the owner) hears plus the office's alert (no backup: today's next_up)"
  - "A login caller hears by push + email (care_handoff.tell's pattern) linking to the Follow-up board, held in the church's quiet hours; a member caller keeps today's email to /my/lead"
  - "One guest, one caller: a guest with another open guest follow-up gets a note on it ('Came through another door: …') instead of a second follow-up"
  - "A Welcome Team lead appearing in auto mode raises one office alert (deduped, and stamped settings.guest_calls.welcome_asked so it's asked once); calls stay with People & Care until the office says yes; guests already handed stay put"
related: [2026-11-20-guest-welcome-path.md, 2026-11-17-guest-lane-new-here.md, 2026-11-14-new-here-guest-texts.md, 2026-10-26-checkin-welcome-handoff.md]
---
Step 2 of the Welcome Path (mock board "Who calls our guests", canvas
WmRiSK8seJky8pJUK5nztE). New `guest_calls.py`: the church's setting
(`businesses.settings.guest_calls`, a server key, written only through
`PUT /church/guest-calls/{business_id}`) and `GET` of the same, which Builder
3's Guests room reads. `church_follow_up.start()` asks it for every guest's
follow-up; the sweep tells a login caller in the app and by email and walks the
guest ladder; `_sweep_handed` hands these to `guest_calls.recheck`. No
migration: settings plus existing columns (`assigned_by`, `leader_role`, the
existing note kinds nudged / reassigned / pastors_told).

Before building more here: the call brief (step 3) and replies reaching the
caller (step 4) both read who the caller is from the follow-up's
`leader_contact_id`; `guest_calls.logins(ch)` says which callers are office
logins.
