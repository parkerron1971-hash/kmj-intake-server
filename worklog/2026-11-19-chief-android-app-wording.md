---
title: Chief never sells our plans or add-ons inside the Android app
date: 2026-11-19
agent: Claude Code (Claude Opus 5.5)
asked: "build it that way (Chief inside the Android app: no upgrade, buy, credits, storage, logins or add-a-card talk; may say which plan has a feature; asked how to change the plan, the owner hears Settings → Billing and plan at mysolutionist.app in a browser with no link, anyone else is told to ask the owner)"
status: in progress
prs: [kmj-intake-server (this PR, branch chief-android-app-wording)]
migrations: []
left_undone:
  - "Not gated, not Chief's words: the 402 messages the app's own screens show (billing_limits feature_locked / out of credits / trial ended / no plan, business_users_router seat cap, launch_access business cap, clip_finder, no_card_trial phone check). The app replaces the 402 toast (solutionist-studio #1646); check any other place that prints detail.message."
  - "Not gated: sample_church.MESSAGE ('Start your church to do this for real.'), the sample guard's 409 the app reads; outreach_journeys 'Upgrade to switch it on.' (a 409); business_marketing_planner.NO_PLAN 'Choose a plan to get one.'; trial and lifecycle emails."
  - "Not gated (low risk): chief_truth's answer check and prose repair, which only correct the reply they are given; Chief's background briefs and Home lines, written by the scheduler, not a request."
  - "Not checked on a real phone: the server reads the user agent, so a WebView that drops SolutionistAndroid/ from fetch() would get the browser's Chief."
decisions:
  - "The flag is the user agent (SolutionistAndroid/, solutionist-studio #1644), read by a pure ASGI layer (android_app.AndroidAppMarker) into a ContextVar per request and reset after; tasks the request starts copy it."
  - "The rules go at the END of the built prompt: always inside the last, uncached segment for every shape, and the last thing the model reads. The cached segments are byte-identical with and without them (tested as sent)."
  - "Owner or not is businesses.owner_id against the signed-in login (no owner_id reads as not the owner, so nobody is told where to pay by mistake); the owner's name is settings.practitioner_name."
  - "Quick lanes (the fast answer, the headline, the voice preview) don't carry the full rules: in the app they hand anything about plans or buying to the full turn (NEED_RECORDS / NEED_MORE). The first track's opening is told never to mention them. A fast answer cached in a browser is never replayed in the app."
  - "Server lines Chief passes on lose their 'Upgrade' / 'add a card' clause in the app (android_app.wording): the texting-number refusal, the no-card trial refusals and their 'Waits for a card' label, the Transactions-drawer and /ai/proxy message caps, the sample church's 'once you choose a plan' lines."
  - "Switch: CHIEF_ANDROID_APP=off makes the app's Chief the browser's again."
related: [solutionist-studio 2026-11-19-play-app-hide-plan-buying.md, 2026-11-19-chief-reply-report.md]
---
android_app.py holds the flag, the middleware and every line Chief is told in
the app. chief_of_staff._with_android_app_rules adds the main block to the
turn (the stream endpoint runs the same turn); _compose_post_action_reply,
chief_fast_track (opener, fast answer, its cache key), chief_headline,
chief_voice_bridge, fallback_brain and sample_chief each add their own short
line, all empty outside the app. Tests: __tests__/test_android_app_chief.py.
No live model evals were run.
