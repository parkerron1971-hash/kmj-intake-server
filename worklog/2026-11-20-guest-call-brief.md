---
title: The guest call brief, "How did it go?" and the next-step hand-off (Welcome Path step 3), with the card's new questions
date: 2026-11-20
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-20, on the Welcome Path mock (boards "The caller''s phone" and "The guest''s phone" board 2): "chief should be sending a follow up call to the admin of people and care ... top tier", then "build". Builder 5 of wave 2: the call brief, the two-tap outcome, the next-step hand-off, the card''s new questions'
status: in review
prs: [kmj-intake-server (this PR), solutionist-studio (the brief sheet, the outcome sheet, Who calls embedded)]
migrations: []
left_undone:
  - "Live only where GUEST_PATH lets it (unset = owner: the platform's own church). Off is today: no brief, a call's note is the note it always was, the card asks what it asked"
  - "A group's leader gets the guest's group step as a follow-up only when they hold a church role (the Lead tab needs one); a group led by someone with no role, and a guest with no group picked, is a note for People & Care. Group join requests (group_join_requests) are not used for it"
  - "Kids desk names come from the family's children (first names and ages); the mock's 'Tell Kids Club to expect Sofia and Mateo' is not built (no kids-room hand-off)"
  - "Take a class has no stream in church_follow_up, so it is a note for People & Care naming the class when the church has exactly one open; the Academy enrollment is the guest's own"
  - "The brief's 'Monday note' is New here's Monday text (the senior pastor's signature is Builder 4's)"
  - "The mock's push 'Chief: a new guest for you ... The brief is ready.' is guest_calls' (step 2) wording; the push doesn't say 'The brief is ready' yet"
decisions:
  - "guest_brief.py, deterministic (no AI call): GET /church/guests/{business_id}/brief/{follow_up_id}, business_access('manager'); readable by the follow-up's caller (an office login whose person record it was handed to, church_over.Church.login_person), anyone who sees the Guests room (church_guests._areas_ok), the owner and admins. Not a guest's follow-up, the path off, not a church: 404. A failed read is a 503"
  - "The brief reads metadata.new_here (door, texted_at, card, app), the follow-up's answers, the family's children (household_adults, children, child_checkins), chief_scheduled_actions new_here_text rows and outbound sms_messages (church_guests._text_state), groups/group_members, the Serve card's teams and team-leader scopes, academy_courses open to join, and choose() for baptism and pastor_ask. Never ministry_care_requests: the prayer is the card's yes/no only"
  - "Worth mentioning only names the church's real things: groups taking new people (active, not youth, not a team, not by invitation) with their day and time (groups.meet_day/meet_time, else groups.meets) and their leaders; teams to serve on; classes open to join; who takes baptism; a pastor to talk with. No line when the church has nothing"
  - "The opening line: 'Hi {first}, this is {caller's first name} from {church without a trailing Church}. We loved having you (and the kids) {day}. I just wanted to say thank you for coming.' A Plan your visit guest and a member app guest get their own true line"
  - "How did it go: the office's POST /church/follow-ups/{id}/note takes `outcome` (talked/message/noanswer/notnow, the note then optional) and `picks`; office_note logs it as that kind and a reached one finishes Reach out (as leader_note does). The member page's POST /my/lead/note reads pick_<ask> fields. Both then call guest_brief.after_call"
  - "Talked hands each ask through church_follow_up.start as a normal follow-up, card_key call:<ask>, card_name 'Welcome call: <ask>', source_event call-ask:<guest follow-up>:<ask> (unique), first answer 'Asked for on their welcome call', and a note 'Asked for on their welcome call with <caller>': serve (the team picked) and baptism and pastor (pastor_ask) through choose(); a group to its leader when they hold a role (start's new `pick`: a decided hand-off); else a note on the guest's follow-up for People & Care, who hears by guest_calls.tell_login unless they made the call. Nothing twice: Chief's note 'Asked for on their welcome call: <label>.' on the guest's follow-up, the unique receipt, and an open hand-off of theirs (a call:<ask> one, or their own Baptism or Serve card) each say it's done"
  - "A failed read decides nothing: the brief's kids, household and names are a 503 (never 'no kids' or a nameless opening line); a Talked whose groups, teams or roles couldn't be read hands nothing and writes no note for that ask (did says so), so logging it again hands it on. The caller's other guests are a convenience: a failed read leaves them out with others_read false (review of #2014)"
  - "Message, No answer, Not right now hand nothing on (Message finishes Reach out; Talked later still hands the asks on)"
  - "The invite line is New here's own rule (new_here._came_back): 'Keep Thursday's invite, since {first} hasn't been back yet', or 'Skip ...' once they have"
  - "The New here card (/new/<code>) asks, with the path on: Who invited you? (optional), Your kids' names and ages (hidden by CSS while Kids is None), What would you like? (member_im_new.WANTS), Best way to reach you (A call is fine / Text me instead). Kept in metadata.new_here.card (invited_by, kids_names, wants, reach); the follow-up's answers carry them, never the prayer. member_im_new asks Who invited you? and Best way to reach you (and labels ages 'Their names and ages') with the path on"
  - "A church's picked bulletin guest card (settings.new_here.guest_form) whose kind is general or none opens as kind connect, so guest_path.is_guest_follow_up counts it and Who calls our guests routes it (guest_path.py untouched)"
  - "A hand-off from a call says so in its leader's email: '{name} asked for this on their welcome call at {church}: <ask>. Chief handed them to you.' (church_follow_up._came_line)"
related: [2026-11-20-guest-welcome-path.md, 2026-11-20-guest-path-every-door.md, 2026-11-20-who-calls-our-guests.md, 2026-11-20-guests-room.md, 2026-11-19-member-im-new.md, 2026-11-14-new-here-guest-texts.md]
---
Step 3 of the Welcome Path. Before building I read both repos' `worklog/`
(the Welcome Path's own four entries, New here 11-14, the guest lane and print
cards 11-17, the member app's I'm new here 11-19) and the mock boards
CallerPhone (the brief, How did it go?) and GuestPhone board 2 (the card's
four new questions). Nothing had built a brief or an outcome hand-off.

New `guest_brief.py` (the brief, after_call, the route), mounted after the
Guests room. `church_follow_up.py`: start's `pick`, office_note's `outcome`,
on_intake_form's guest card, the told email's line for a call hand-off.
`church_router.py`: the note's `outcome` and `picks`, and `did` back.
`member_portal_lead.py`: Chief's brief on a guest's file, the Chief will lines
per tap (CSS :has, no script), pick_<ask> selects, after_call on Save.
`new_here.py`: card_html's path questions, card_send and save_card.
`member_im_new.py`: the two questions.

Tests: `__tests__/test_guest_brief.py` (28): the brief's lines with and
without kids, who invited them and asks; the prayer flag (its words never
read); real groups only; the texts; what Chief will do; access (the caller,
the room's logins, admin, outsiders, the switch); each hand-off stream and no
duplicates; skip; an ask already open; the other taps; the Lead tab's page;
the card's and the member app's questions; the general guest card.
