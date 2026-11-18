---
title: The Monday leaders note goes as a short text too, and My week says how many people get the church's texts
date: 2026-11-17
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-17, on two ideas for Naiya (Office & Leadership): "Send the Monday leaders note as a short text to the leaders" and "check how many people have signed up for texts each week": "I approve your ideas. make this happen please."'
status: in review
prs: [kmj-intake-server (this PR), solutionist-studio (Text it too on the leaders note, My week's fact line)]
migrations: []
left_undone:
  - "A text that couldn't go (who said yes unreadable, every send failed) can't be sent again that week: the note goes once a week, email and text together. The sent page says why"
  - "Quiet hours refuse the text (409) rather than hold it till morning: holding would need its own scheduled action type and runner (sms_announcement's runner texts the whole list or a group, not the leaders room)"
  - "My week's count is on the weekly text's job only; the office team page (church_team_week) and Chief don't say it"
  - "Love City: 37 of its 149 numbers get texts (keyword texters), and its texting registration has never been sent, so My week shows the note until the owner sends it (Text, the gear, Your name on texts)"
decisions:
  - "Lane: Build, Kevin's direct approval of the two ideas"
  - "The text's gate is the note's own (owner, admins, a Manager holding leaders_note): the same note to the same people, so no weekly_text duty. Announcements to the whole church stay weekly_text's"
  - "The text is text_version(subject, text): the subject and the note's lines in order, headings left out, cut at a word to 300 letters with plain dots, the calendar's ' · ' a dash and curly quotes plain (twilio_sms.gsm_safe) so it never bills as UCS-2. Only the note's own words. The app's textVersion mirrors it, checked on the same cases in both repos"
  - "Sent by sms_routing.text_people, which shares the announcement's send loop (_text_each, split out of announce, behaviour unchanged): only numbers that said yes (sms_alerts.said_yes_to_texts), one text a number, STOP checked again, the church's name first and the way out last, the allowance heads-up after (_after_texts). Logged as events 'leaders_note_text', never 'sms_broadcast', so it never ticks the weekly text's Done"
  - "Before the week is taken: billing_limits.require_card(biz, 'texts') and the church's quiet hours (member_push.quiet_hour). Then the emails; the text only after an email went. The send record keeps texts {sent: leaders reached, texts, skipped, failed, body, error}"
  - "GET /church/leaders-note returns texts {leaders, reach, numbers, quiet, quiet_words, name, most}, or null when who said yes can't be read (the note itself stays a 200)"
  - "My week: the weekly_text item carries fact ('37 people get the church's texts (+2 this week)', 'no one new this week' at zero) and fact_note while texting_registration.is_sent is false. The count is sms_routing.said_yes_count (the whole-list announcement's reach); this week is who says yes now and had no yes before Monday on the church's clock (said_yes_to_texts(before=)). Kept 30 minutes a church a replica, read on a thread My week waits 2.5 s for; a failed read says nothing (kept a minute). MY_WEEK_TEXT_COUNT=off leaves it out; off in unit tests (conftest)"
  - "The note's words are true to the rule rather than the brief's 'only people who texted the keyword': before registration a member-app yes counts too"
related: [2026-10-27-church-leaders-note.md, 2026-11-03-church-text-allowance.md, 2026-11-13-church-texting-registration.md, 2026-11-14-texting-hours.md]
---
Before building I read both repos' `worklog/`: the leaders note (10-27) left
"Email only" undone; texting hours (11-14), the text allowance (11-03) and
church texting registration (11-13) set the rules this follows. Nothing had
texted the leaders room or counted sign-ups.

`church_leaders_note.py` (text_version, text_reach, text_leaders, quiet_now,
the send's also_text), `sms_routing.py` (_text_each, _after_texts,
text_people, said_yes_count), `sms_alerts.py` (said_yes_to_texts `before`),
`church_my_week.py` (texts_fact). Docs: `docs/CHURCH_DUTIES.md`'s
leaders_note row, `.env.example`.

Tests: `test_church_leaders_note_text.py` (16), `test_sms_said_yes_count.py`
(6), `test_church_my_week_texts.py` (10). 503 passed across those and the
leaders note, SMS, announcement, church texts, news reach, texting hours,
text room, My week, rhythm, team week, duties, card and ownership files.
