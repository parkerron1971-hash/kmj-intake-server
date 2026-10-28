---
title: The bulletin texts only people who said yes (sms/broadcast consent)
date: 2026-10-28
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-10-28, after I found the Text screen''s "All-points bulletin" texts every number on the list: "fix the button, build text the rest feature now"'
status: shipped
prs: [kmj-intake-server#1627, solutionist-studio (the Text screen's count and wording, next)]
migrations: []
left_undone:
  - "The bulletin still goes from the shared number for a business without its own registered name: words the owner wrote, on the platform's campaign. Consent is fixed here; the sender isn't (Kevin's call)"
  - "Still at most 500 contacts per press (unchanged)"
decisions:
  - "Who gets it: sms_alerts.said_yes_to_texts. On the shared number, THE CONSENT RULE for many (has_sms_consent's filters: the business's consent rows but not the offers-only box, the platform's web form, a keyword binding). Under its own registered name, the mixed rule for many (agreed_under_own_name: agreed under its name, or texted it, since it registered). STOP wins either way, the platform's and the business's own"
  - "A read that fails means nothing is sent (503), never 'everyone'"
  - "A number shared by two contacts gets one text"
  - "GET /sms/broadcast/reach (admin) answers {with_phone, said_yes} so the Text screen can say who it will reach before anything is written; the POST adds not_yes to its answer and its event"
related: [2026-10-12-texting-words-not-twilio.md]
---
Before building I read both repos' `worklog/`: nothing on the bulletin's
consent. `/sms/broadcast` texted every contact with a phone (up to 500),
skipping only STOP. At Love City that was 145 numbers, of whom about 30 had
ever said yes (30 keyword bindings, no consent rows).

`said_yes_to_texts` is the consent rule for a whole list at once (reads in
chunks of 100 phones), and it's what the church news texts will use next
(the "text the rest" work). Its shared-number filters are pinned to
`_positive_consent`'s by a test, so the two can't drift apart quietly.
