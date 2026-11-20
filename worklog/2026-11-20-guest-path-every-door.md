---
title: Welcome Path step 1 — every guest door joins New here's texts, with a "Text me" yes on each door
date: 2026-11-20
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-20, on the Welcome Path mock: "capture visitors, place them in a flow where they receive automated texts from the church ... top tier", then "build". This is build step 1, "One path for every door" (the mock''s gaps 1, 2 and part of 7).'
status: in review
prs: [kmj-intake-server#2008, solutionist-studio#1658 (the kids desk box and New here's doors)]
migrations: []
left_undone:
  - "Live only where GUEST_PATH lets it (unset = owner: the platform's own church). Every church: GUEST_PATH=on. Texts also need New here on for the church (settings.new_here.on) and its own active number: until then every door puts the guest on the path with texts_ok false and texts 'new_here_off' or 'no_number', and no Text me box shows"
  - "Love City has New here OFF (settings.new_here.on unset, 11-17), so its doors list guests but text no one until it is switched on in Text, New here"
  - "The welcome words are the same for every door (the church's welcome). The mock's per-door welcome ('We loved having Sofia and Mateo in Kids today') is not built"
  - "The invite's default words say 'see you again'; a Plan your visit guest gets it too. Wording per door is a later choice"
  - "The office's First time: no new UI (the app writes attendance itself), so its guests get texts only when that phone already has a yes at the church (a kids desk yes, the texts sign-up page, any sms_consents row of the church's)"
  - "A first check-in that finds an open follow-up from another door adds no note (the sweep re-reads First time rows every 10 minutes for a day; a note there would repeat)"
  - "Builder 2 (Who calls our guests) routes the follow-ups; this PR only decides one guest = one follow-up at the card doors"
  - "Kevin's call (review of #2008): a public card's Text me box can be ticked for any number, as every website consent box here can; the welcome carries STOP. A reply-to-confirm step before the welcome would close it"
  - "Kevin's call: at the kids desk and the welcome desk any sms_consents row of the church's for that number counts as the yes (the texts sign-up page, a booking opt-in), not only the kids desk's box"
decisions:
  - "new_here.enroll(business, contact, door, texts_ok, phone, visit_at): metadata.new_here gets door, texted_at (the path's start for every door), texts_ok, a card code, visits, and `texts` ('on' or why not: new_here_off, no_yes, no_phone, no_number, stopped, unread), New here's own keys kept. No migration"
  - "The welcome is a new_here_text row with step 'welcome' (run_scheduled), run_at now inside the church's automatic-text hours (texting_hours) with 10 minutes to spare, else the next opening. The scheduler ticks every minute, so 'now' is within about a minute, and STOP, the switches and the hours are read again at send time like every other New here text. A welcome found outside the hours at send time is moved to the morning, never dropped"
  - "Monday note and invite from the path's start, as the text door plans them, never within an hour of the welcome. The thank-you ('for worshiping with us today') only for a door that saw them at church that day (kids desk: now; welcome desk: the check-in time), at least an hour after the welcome, never past the day's last slot"
  - "One guest, one path: a door inside REVISIT_DAYS starts nothing, except the first set of texts when the earlier door had no yes and this one has (the path keeps its first door and start). After REVISIT_DAYS a door is a new visit, as a second NEW is"
  - "The text door records door 'text', texts_ok true; texting the word while on another door's path without texts starts the texts on that path"
  - "Texts go only with a kept yes: every door's yes is an sms_consents row (kids_checkin, connect_card, guest_form, member_app_new) with consented_at and the request's ip and user agent, kept once per number and door. The texts go to the number the yes was given for"
  - "The box shows only where a yes brings texts now (new_here.can_text: the path on, NEW_HERE and settings.new_here.on, the church's own number), unticked. Words: 'Text me. Yes, {church} may text me about my visit and next steps, up to 4 msgs a week. Msg & data rates may apply. Reply STOP to end, HELP for help.' The kids desk reads it out: 'Ask first, and tick only if they say yes: “May {church} text you about ...”'"
  - "Doors: kids desk = Add a family's box (kids_router: GET /kids/families guest_texts, POST texts_ok) then the first check-in (church_first_visit.join_path, door kids); office First time = the sweep (door desk, texts_ok from a yes already kept); website connect card = a <!--solutionist:guest-texts--> slot public_site fills, sms_consent sent apart from the answers (door web; a card that says 'regular' doesn't join); church cards = a box on the public form page for a connect / Plan your visit card or the bulletin's guest card with a 'phone' field (door form; intake_endpoint.church_card); member app = a box on I'm new here (door app, only for 'I'm new')"
  - "A second card door with a guest follow-up already open adds a note there instead of a second follow-up (new_here.second_door), at the website card, church cards, the New here card and the member app"
  - "New here's list (guests_of) shows every door: door, texts_ok, texts, and the follow-up any door made. Resend refuses a guest whose texts_ok is false"
  - "GUEST_PATH off (or a failed read) = exactly the old behavior at every door; queued texts from a non-text door stop"
  - "A yes that can't be read (tried twice) or a welcome that can't be queued is texts 'unread', never 'no yes' or 'on', and the next door this week (or the same one again) tries again; a door that says no never settles it"
related: [2026-11-20-guest-welcome-path.md, 2026-11-14-new-here-guest-texts.md, 2026-11-17-guest-lane-new-here.md, 2026-11-17-guest-print-cards.md, 2026-10-26-checkin-welcome-handoff.md, 2026-10-13-church-website-forms.md]
---
Before building I read both repos' `worklog/` (new-here 11-14, guest-lane
11-17, guest-print 11-17, checkin handoff 10-26, church website forms 10-13)
and the Welcome Path spec and mock. Nothing had joined the other doors to New
here's texts; only the text door kept a yes.

`new_here.py`: the "every door" section (enroll, enroll_by_id, keep_yes,
has_yes, can_text, text_me_words, form_door, text_me_for_form, second_door,
welcome_time, plan_path), the welcome step in run_scheduled, the text door's
door, guests_of's doors, resend's guard, save_card's second door.
`church_follow_up.py`: on_intake_form and on_connect_card only.
`church_first_visit.py`: join_path from the kids desk and the office's First
time. `kids_router.py`: guest_texts and the family's yes. `member_im_new.py`:
the box, join_path, second door. `intake_endpoint.py` (church_card) and
`form_page_renderer.py` (the box, TEXTS_NAME). `public_site.py`: the
connect card's slot and its yes. `sites/love-city-church/`: the slot and
forms.js sending sms_consent apart.

Tests: `__tests__/test_guest_path_doors.py` (new), plus the Welcome Path
sections added to `test_church_first_visit.py` (through the real kids desk
and sweep) and `test_member_im_new.py` (through the real form and POST).
