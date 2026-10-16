---
title: Love City's Watch page plays the YouTube live stream
date: 2026-10-16
agent: Claude Code (Claude Opus 5.5)
asked: "Love City will stream through Solutionist's relay to BOTH YouTube and Facebook... update Love City's website Watch page" (Kevin's decision, via KAI)
status: waiting on Kevin
prs: [kmj-intake-server#1463]
migrations: []
left_undone: ["Kevin: delete the stale scheduled stream 'Sunday Morning Worship 5.16.21' (Vxcz5vw2Kyk) in YouTube Studio, which the channel's /live page still points to", "after #1460 merges: connect @lovecitychurch in the app and propose a one-time import of recent past services, deduped against relay drafts; ask Kevin drafts or published"]
decisions: ["the live player loads only from 15 minutes before a gathering until it ends, or when a visitor taps Open the live player, because YouTube's channel live embed shows 'This video is unavailable' whenever the channel isn't live", "no automatic YouTube import and no auto Go-live: the relay (#1460/#1461) owns both for Love City"]
related: [2026-10-14-love-city-better-photos.md]
---
Love City's YouTube channel is @lovecitychurch (UCb5vWtszeeCfdI98_mZFSrg). It holds about 400 past live services; Facebook's past-live list is empty. lovecityc.com/watch said Facebook was the only place to watch live. It now:
- says services stream live on YouTube and Facebook, with a button for each;
- loads the channel's live player (youtube-nocookie, by channel id) during service times, using the schedule site.js already uses for its "Next" line;
- keeps the latest message the rest of the week;
- links the channel in every page's footer.

The text-override key moved from `watch.facebook` to `watch.live`. Love City had no saved text overrides on 2026-10-16, so nothing was lost.

Before building more here, see the overlap notes on #1460. While the relay is on, a YouTube importer or live watcher would see every service twice.
