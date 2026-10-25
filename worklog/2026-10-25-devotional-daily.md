---
title: The devotional a day at a time, by page and evening text, before the app
date: 2026-10-25
agent: Claude Code (Claude Opus 5.5)
asked: "how can we make this devotional available where people can get them daily before i reveal the app? ... yes do that and then build the page and nightly text (Kevin, 2026-10-25; Love City's 21 days: Focus, Finances, Food)"
status: in progress
prs: [kmj-intake-server#1580]
migrations: [supabase/APPLY-2026-10-25-devotional-texts.sql (applied 2026-10-25)]
left_undone: ["the shared number's 10DLC registration was written for bookings and replies; the evening devotional is opt-in content, not marketing, but if Kevin wants it under Love City's own name the church's texting registration (Settings) is the step", "only Love City is on (DEVOTIONAL_DAILY_BUSINESSES unset); every church is a Thursday switch-on: set it to * and add a What's New line", "the owner has no screen for sign-ups yet: who joined is in devotional_texts and each person is a contact (texts land in the inbox history as system sends)", "no Listen file on the page: it uses the phone's own voice (speechSynthesis), not devotional_voice", "a person can't stop the evening texts without STOP, which stops every text from the church"]
decisions: ["the page reads the same devotionals rows as the member app, so a day is written once; nothing on the page names the app", "a day opens on its date and tomorrow's the evening before (the text links it at 7:30 so it's read that night)", "a devotional_texts row is the consent for these texts only, never an sms_consents row, so campaigns and reminders can't count it; STOP still wins at send time", "the evening claim is last_key moved by one filtered PATCH, so a second replica or tick never sends a day twice; a text that didn't go is put back for the next tick", "DAILY works only on a church's own number, like GIVE; on the shared number a word belongs to one business", "each week of the 21 days is its own devotional (Focus Week, Finance Week, Fasting Week) so each week's checklist grows by one practice, as the plan does", "the parser's list mark now takes a markdown task ('- [ ] '), so a doc exported as markdown pastes with its whole checklist"]
related: [2026-10-19-member-app-devotionals.md, 2026-10-19-devotional-paste-reader.md]
---
`/daily` on a church's own address (lovecityc.com/daily) shows today's day of
the published devotional that has a start date covering today: the scripture
(the Bible here, KJV), the words, the line to hold, Pray / Do today /
Together, the checklist (ticks kept on the phone), the week's days, and a
sign-up box. Before the first day it shows the welcome; after the last, every
day stays open. `POST /daily/join` saves a devotional_texts row (the words
agreed to kept on it), makes the contact, and sends a welcome text inside
texting hours. DAILY texted to the church's own number does the same
(sms_routing, beside GIVE). `devotional_daily_texts` runs every 10 minutes on
the leader; from 7:30 to 7:58 PM Eastern it texts each live row tomorrow's
title, scripture reference and link, once, skipping anyone who texted STOP.

Checks: 18 tests in test_devotional_daily.py (days across three back-to-back
weeks, tomorrow-only opening, 404 where off, sign-up validation and the bot
box, the evening window, once a person, STOP, put-back on a failed send, after
the last day nothing) plus DAILY routing in test_sms_numbers_inbound.py and a
markdown checklist case in test_member_devotionals.py. Rendered at 390px in
light and dark with the real Week 2 text.
