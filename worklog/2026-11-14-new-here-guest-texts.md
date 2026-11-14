---
title: New here — a guest texts NEW to the church's number, gets a welcome, a card, a thank-you and the week's texts
date: 2026-11-14
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-14: "the new here for guest is very important. can we update for our system and create a space for that on the system now", then on the mock (canvas QKF6rdSMuGtLp74RtVEy4Z, "yes to both ... a thank you for coming after church automatically"): "build this."'
status: in review
prs: [kmj-intake-server (this PR), solutionist-studio (the New here room in Text)]
migrations: []
left_undone:
  - "Switch: NEW_HERE unset = owner (the platform's own churches). Every church: NEW_HERE=on, on a Thursday"
  - "It needs the church's own active number (the word is never on the shared number). A church without one sees that in the room"
  - "The setup guide with pictures (keywords, best uses, text vs app) Kevin asked for after this"
  - "The thank-you goes `hours` after the guest's text (3 by default), not '2 hours after the service ends' as the mock said: service end times aren't read here yet"
  - "Incoming texts still aren't recorded in the Costs view (about 1 cent each)"
decisions:
  - "Lane: a new feature; Kevin's 'build this' put it in Build"
  - "Like GIVE and DAILY: answered in sms_routing on the church's OWN number only, after DAILY, before the inbox. Anything that isn't one short word stops before a read, so ordinary texts cost nothing extra"
  - "The welcome is the TwiML reply (metered like any text), under the platform's name ('Solutionist System for Grace Hill Church: ...') until the church texts under its own registered name, as GIVE does. It carries the keyword sign-up words (Up to 4 msgs, rates, STOP, HELP); the room refuses a welcome without {card link} or STOP"
  - "No migration: the guest's place is contacts.metadata.new_here {code, texted_at, visits, card_at, card}; the three texts are chief_scheduled_actions rows of type new_here_text, run by chief_scheduler through new_here.run_scheduled, which reads the switch, the church's words, the guest, STOP, quiet hours (9 AM to 8 PM church time) and, for the invite, a check-in since, again at send time. Off or not needed is 'done', not 'failed'"
  - "A second NEW within 7 days is the same visit: same card, nothing scheduled twice"
  - "Times on the church's clock (business_marketing.business_tz, else Eastern): thank-you `hours` after the text, held to 7:45 PM and skipped when that's within 30 minutes; the next Monday 10 AM (never the same day); the Thursday before the next Sunday 6 PM (never within a day of the text)"
  - "The card is /new/<code> on the church's site, served by public_site AFTER a hand-built page claims the path (so a church's own /new page still wins); the code (8 chars) is the only thing in the address. It works after the church turns New here off, for guests who already got the link"
  - "Saving the card: names a number-named guest, sets an email only where there was none, tags a first timer 'first-time guest', ties their earlier texts to them, keeps a prayer as a confidential ministry_care_requests row (pastors only, church_prayer.on_new), and starts church_follow_up (card_key text:new_here, kind connect, routed like a first text) with the card's answers and never the prayer"
  - "Who: the room reads for any login (viewer); changing it is whoever sends announcements (sms_routing._may_announce); 'Send the card again' is member+"
related: [2026-10-25-devotional-daily.md, 2026-10-30-text-room-people.md, 2026-11-13-church-texting-registration.md, 2026-10-26-checkin-welcome-handoff.md]
---
Before building I read both repos' `worklog/`: nothing had built a guest
keyword. The nearest were the DAILY word (devotional_daily, the model for this),
First text → guest card (text_room.save_guest) and first check-ins handing a
welcome follow-up on (church_first_visit).

`new_here.py` (new): settings, the word, the times, `on_text`, `run_scheduled`,
the card (`page_for`, POST `/new/{code}`, `save_card`) and the room
(GET/PUT `/new-here/{business_id}`, POST `/new-here/{business_id}/resend`).
Wired into `sms_routing.route_inbound`, `chief_scheduler` (like
sms_announcement), `public_site` (the card's pages), `kmj_intake_automation`
(the router) and `rate_limit` (`new_here_card`, strict).

Tests: `__tests__/test_new_here.py` (18). 730 passed across the SMS, texting,
devotional, scheduler, public site, ownership, rate limit and follow-up files.
