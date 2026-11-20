---
title: Welcome Path step 4 — a guest's reply reaches their caller, and the automatic texts wait for a person
date: 2026-11-20
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-20, on the Welcome Path mock (the rule "A reply holds the automatic texts until a person answers", the caller phone''s "answered the church''s text" alert): "build". Build step 4, "Replies reach the caller" (the mock''s gap 5).'
status: in review
prs: [kmj-intake-server (this PR), solutionist-studio (Text opens on the guest from the alert; Waiting on you in the list)]
migrations: []
left_undone:
  - "Live only where GUEST_PATH lets it (unset = owner: the platform's own church). Off: nothing here runs, and replies land in Text as before"
  - "Holding the texts is new_here.run_scheduled's job (Builder 4's HOLD check reads metadata.new_here.hold). Until that merges, a hold is set, told and cleared, but the next automatic text still goes"
  - "Only the church's own number: a guest's reply to the shared number (a church with no number of its own) isn't held. New here's texts never go from the shared number, so a path guest texting there is rare"
  - "A member caller who texts the guest from their own phone doesn't clear the hold: they clear it by noting Talked or Left a message on the Lead tab (the email says so). The office can also answer in Text"
  - "The path's end: on_path() treats `ended` or `ended_at` in metadata.new_here as ended (Builder 4's weeks two to six may name it otherwise: line it up there)"
  - "Other writers of contacts.metadata (new_here._keep, enroll, save_card) read-modify-write the whole column without the hold_v check; a write of theirs landing in the same moment as a reply could drop the hold keys. The window is milliseconds; the sweep can't restore a lost hold"
  - "A guest with two contact records on one number: the reply goes to the one on the path with the newest texted_at; the Text room's message may sit under the other record"
decisions:
  - "Hook: sms_routing.route_inbound's own-number routed_direct branch, after record_inbound_sms, hands (business, phone, body) to guest_replies.on_reply in a daemon thread (guest_replies.later). A failing hand-off is logged and routing goes on"
  - "A reply = on the path (metadata.new_here.texted_at within 42 days, no ended/ended_at) and not a keyword: STOP/START/HELP (or a text starting with one), GIVE, DAILY, the church's New here word (even with New here off), its texting keyword. An emoji or a one-word answer counts"
  - "The hold: metadata.new_here.hold true, hold_since (the first reply still waiting; kept on later replies), hold_reply_at; every write is compare-and-swap on hold_v (PATCH guarded by metadata->new_here->>hold_v), three tries, the rest of metadata kept as read"
  - "Each reply is a note on the guest's newest open or handed-back guest follow-up: \"Answered the church's text: “…”\" (kind note, author chief). church_history lines never carry the words or the name (hold started, answered, a day late, three days late)"
  - "Who hears: the follow-up's caller when it's open with one: an office login (guest_calls.logins) by guest_calls.tell_login, now taking nav/link/label (push nav operate:sms:<contact id>, email button Open their texts → /?nav=operate:sms:<id>); a member by email (the reply, the guest's number, Open your Lead tab). No caller (no follow-up, none open, handed back): guest_calls.first_guests_login. Nobody reachable (a member with no email, a login nothing reached): the office's alert, without the words"
  - "Words: \"<Name> answered the church's text\" / \"“<reply, 90 chars>” Their texts are on hold until you reply.\" (someone replies, for First-time guests). A nameless guest is \"A guest at (555) 123-4567\""
  - "Quiet hours (member_push.quiet_hour) hold the telling; the sweep tells after. At most one alert a guest every 10 minutes: hold_tell (owed) / hold_told_at claimed in the guest's row before sending; nothing went → owed again. Replies inside the 10 minutes are told by the sweep after, with the latest words"
  - "Cleared by: POST /sms/send after a text went (the Text room; Chief's send_sms_core and the scheduler's sends never come through it), or a REACHED note (Talked, Left a message) by anyone but Chief on the guest's follow-up (church_follow_up._note → on_outcome). hold false, hold_answered_at/_by, note \"Answered by <name>.\" (\"Answered in Text.\" when the login's name can't be read)"
  - "Sweep (guest_replies.sweep, every 10 minutes, scheduler job guest_replies_sweep): churches with an active own number and the path on, contacts with metadata->new_here->>hold=eq.true (per church). Owed alerts; a day after hold_since the caller is reminded once (hold_reminded_at); three days after, the office's alert once (hold_alerted_at, dedup key guest-reply-waited-<contact>-<hold_since>). Never cleared by time"
  - "A read that fails decides nothing: no contact → no hold; no follow-up → held, nobody told until the sweep can read; who-to-tell unread → owed again"
  - "No migration: contacts.metadata.new_here and existing note kinds"
related: [2026-11-20-guest-welcome-path.md, 2026-11-20-who-calls-our-guests.md, 2026-11-20-guests-room.md, 2026-11-20-guest-path-every-door.md, 2026-11-14-new-here-guest-texts.md]
---
Before building I read both repos' `worklog/` (New here 11-14, the guests'
lane 11-17, every door, Who calls our guests and the Guests room 11-20) and
the mock. Nothing set the hold yet: church_guests.py already reads
`metadata.new_here.hold` / `hold_since` as "Texted back: waiting on you" and
its next move "Answer <name>" opens Text on that guest (FE textHandoff).

`guest_replies.py` (new): on_reply, on_person_text, on_outcome, answered,
tell / who_hears, the words, sweep. Hooks: `sms_routing.route_inbound`
(routed_direct), `sms_service.send_sms` (after a send that went),
`church_follow_up._note` (REACHED notes), `guest_calls.tell_login` (optional
nav/link/label; defaults unchanged), the scheduler job in
`kmj_intake_automation.py`, and the sample-church job list.

Tests: `__tests__/test_guest_replies.py` (46).
