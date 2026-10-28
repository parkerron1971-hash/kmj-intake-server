---
title: Important church news reaches the people without the app (text the yes, email the rest)
date: 2026-10-28
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-10-28, after the worst-case texting costs: "look into texting only people without app alerts", then "build text the rest feature now. important post only with email as you shared i agree"'
status: shipped
prs: [kmj-intake-server#1629, solutionist-studio (the composer line, the per-post count, the switch, next)]
migrations: [supabase/APPLY-2026-10-28-news-reach.sql (applied)]
left_undone:
  - "Texts need the church registered to text under its own name (TEXTING_REGISTRATION_OPEN, Kevin's yes): until then every church's important news reaches the rest by email only. Love City has no registration yet"
  - "Who pays for the texts isn't decided: the cap is the platform's (NEWS_TEXTS_MONTH, default 500 a church a month) and the office sees counts, never a price"
  - "Guests (contacts.status lead) aren't sent whole-church news; say so if Kevin wants them in"
  - "A text that fails mid-way isn't retried; that person gets the email"
decisions:
  - "Only posts marked Important. Push first is unchanged (news_alerts); this reaches the people the post is for whose phone has no app alerts (no member_push_subscriptions row) and who didn't choose Off or mute News, adults only, never whoever posted it"
  - "A text only from the church's own registered name and its own ACTIVE number (never the shared number), only to people who said yes (sms_alerts.said_yes_to_texts, the mixed rule), only while member_push_prefs.news_texts isn't false; one plain GSM-7 part sized so send_sms_core's name lead and STOP line still fit"
  - "Everyone else with a valid address gets the email (group_email's layout, unsubscribe, adults only, Resend idempotency per post and person); a text that fails becomes the email; one email per address"
  - "Once per post: church_posts.reached_at claimed by PATCH ... reached_at=is.null; a failed read puts it back for the sweep; quiet hours (9 PM to 7 AM, member_push.quiet_hour) wait for the sweep; at most 3 a day; older than 36 hours is let go ({why: old})"
  - "Church switch settings.news.reach_rest (default on), /church/news/settings reach_rest; GET /church/news/reach (member+) gives the composer counts: phones, texts, emails, texting, used, cap"
  - "Member side: Me, Celebrations shows 'Text me important news' only when the church texts under its own name, the member has a number and no app alerts on a phone; turning it on writes their yes (sms_consents source member_app) once, with the carrier words and the Texting terms and Privacy links under it"
  - "Whole church = contacts not marked lead or inactive"
related: [2026-10-28-bulletin-said-yes.md, 2026-10-23-church-news-alerts.md]
---
Before building I read both repos' `worklog/`: the nearest thing was a
group's "Email the rest" (`group_email.py`, leader's choice per group post);
nothing reached a whole church past the app. This rides the bulletin's
consent helper (`sms_alerts.said_yes_to_texts`, #1627).

`news_reach.py`: `plan()` (who'd get what, also the composer's count),
`reach()` (once), `sweep_tick()` (every 15 minutes, `kmj_intake_automation`
"news_reach"), `record_yes()`. `news_alerts.alert_later` starts it for an
important post going up now. Love City today: 160 members, 1 phone with app
alerts, about 30 numbers that said yes, no texting registration, so an
important post would email the members with an address.
