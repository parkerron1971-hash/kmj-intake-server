---
title: A church sets its own texting hours, quiet hours, alerts a day and New here's times
date: 2026-11-14
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-14, on the Church Texting Playbook: "we need to make sure that people know they can adjust the window when automatic texts can go out. and any other rule we have as default that they can make the changes", then "yes build the texting hours panel"'
status: in review
prs: [kmj-intake-server (this PR), solutionist-studio (the Texting hours panel)]
migrations: []
left_undone:
  - "The playbook artifact (6Sp8M9cdkdjFhhcEq8y2UC) gets 'you can change this' notes once the panel ships"
  - "Not adjustable, on purpose: the DAILY devotional's 7:30 PM text (one evening send for every church), sign-in and pickup codes (sent when asked for), announcements (sent when someone presses Send or picks a time), booking reminders and campaigns (businesses, Eastern time)"
decisions:
  - "settings.texting_hours, read through texting_hours.of(): anything saved outside what's allowed reads as the default, so a church that never opens the panel behaves exactly as before"
  - "Automatic-text hours 9 AM to 8 PM by default, start 8 AM to noon, end 5 PM to 9 PM: never outside the federal 8 AM to 9 PM calling hours. They govern New here's thank-you (held to 15 minutes before the end), note and invite, and its send-time check"
  - "Quiet hours 9 PM to 7 AM by default (start 7 to 11 PM, end 5 to 9 AM). member_push.quiet_hour now reads the church's, so everything that already asked it follows: held group/message/news alerts, serving asks (sunday_serving_alerts), Important posts' texts and emails (news_reach), the Board's after-hours offer. is_quiet_hour(hour) with no church is unchanged"
  - "Alerts a day 3 by default, 1 to 5: the member_push announce cap and news_alerts.daily_max(business) (shared with News posts that ring); church_news and the member Write page show the church's number. Birthday notes stop at the church's quiet start"
  - "New here's note and invite: a weekday Monday to Saturday and an hour inside the automatic-text hours (Monday 10 AM, Thursday 6 PM by default); a saved hour the church's hours later exclude is held inside them. The invite still never goes the next day"
  - "Who: the panel reads for any login; saving is whoever sends announcements (sms_routing._may_announce), as for New here"
related: [2026-11-14-new-here-guest-texts.md, 2026-10-20-quiet-hours-after-hours-alert.md, 2026-10-23-church-news-alerts.md]
---
Before building I read both repos' `worklog/`: quiet hours (10-20) and news
alerts (10-23) set the 9 PM / 7 AM and 3-a-day defaults as constants; nothing
let a church change them.

`texting_hours.py` (new): `of`, `in_auto_window`, `is_quiet`, `alerts_per_day`,
`hour_words`, GET/PUT `/texting-hours/{business_id}`. Wired into
`member_push` (quiet hours, the announce cap), `news_alerts` (`daily_max`,
birthdays), `church_news` and `member_portal_write` (the cap they show),
`new_here` (`plan_times`, `run_scheduled`, the room's `hours`), and the app.

Tests: `__tests__/test_texting_hours.py` (8). 795 passed across the member
push, quiet hours, news, serving, New here, texting, SMS, ownership and
scheduler files.
