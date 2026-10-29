---
title: The devotional's evening text runs on the clock, and a missed one goes out the next morning
date: 2026-10-28
agent: Claude Code (Claude Opus 5.5)
asked: "the devotional didn't get pushed for tomorrow at 7:30pm" then "make sure you send the one that was suppose to be sent out at 7:30pm as soon as you can. (Kevin, 2026-10-28, 8:35 and 8:50 PM; Day 4 of Love City's 21 days)"
status: done
prs: [kmj-intake-server#1642]
migrations: []
left_undone: ["the exact cause of 10-28's miss is not proven: the worker was up 7:14 to 7:50 PM, it was the leader (other jobs ran), the plan had 37 people due, and the logs show no exception, no 'missed', no 'max instances'; the sweep printed only when it sent, so a run that returned early or never started looked the same"]
decisions: ["a cron trigger by the Eastern clock (7:30, 7:35 ... 7:55, DST included) instead of an interval that restarts with every deploy (that night: deploys at 7:10, 7:48, 8:05)", "misfire_grace_time 240 s so a run that starts late on a busy loop still runs; coalesce so a backlog runs once; last_key's claim still keeps it to one text a person", "every run in the window prints a line, sent or not, so the next miss has a trace", "Day 4 was not sent that night: Kevin asked at 8:50 PM, after texting's 8 PM quiet-hours cutoff. 'As soon as you can' = 9:00 AM, so the server does it: a morning catch-up (9:00 ... 9:25 AM ET) texts today's day, worded 'Today's devotional', only to people still on the evening before's key (they missed it), never to a late sign-up (last_key None) or anyone who has it; the claim moves only from that key"]
related: [2026-10-25-devotional-daily.md]
---
The evening sweep (`devotional_daily.sweep_tick`) was an interval job:
every 10 minutes counted from whenever the worker last booted. On 10-28
nobody on Love City's list (37 people) got Day 4, though the worker was up
the whole 7:30 to 7:58 window and the plan, run by hand afterwards, had all
37 due with the right text.

Now it is scheduled at fixed Eastern times, six a night, each inside the
send window, with a 4-minute grace for a late start. `SWEEP_CRON` lives in
devotional_daily.py so a test can pin it: every run falls inside
SEND_FROM to SEND_UNTIL before and after the Nov 1 clock change.

And a missed evening is no longer lost: `morning_tick` at 9:00 the next
morning sends that day as today's to whoever had the evening before's
text and not this one. Dry run against prod for 2026-10-29: 37 due, "Love
City Church: Today's devotional (Focus Week, day 4): Set Your Mind,
Colossians 3:2. Read it: https://lovecityc.com/daily?date=2026-10-29&t=1".

Checks: 24 devotional tests (four new: the evening clock, the morning
catch-up to those who missed it and nobody else, nothing after an evening
that went, the morning clock after quiet hours) and 17 scheduler tests
pass.
