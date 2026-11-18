---
title: Faster member app tabs — the look as a shared file, the next tab early, a cross-fade
date: 2026-11-18
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-18: "the members app move slow when send messages in chat, switching from one tab to another… what is the problem and how can that be sped up?" Then, on the four fixes: "yes build all four". This entry is the faster tab switching (the stopwatch and server caching, and instant chat send, are other sessions'').'
status: in review
prs: [kmj-intake-server (this PR)]
migrations: []
left_undone:
  - "Not checked on a real iPhone or Android phone, only Playwright WebKit 26.5 and Chromium 149 on Windows. Worth a tap-through on Kevin's phone once live: the tab bar should stay still and pages cross-fade."
  - "The early start on a phone is the length of a tap (~100 ms): the touch starts the request, the lift uses it. It does not hide the server's own time (0.6-1.4 s a tab, measured 2026-10-20); the stopwatch and server caching work is what shortens that."
  - "Headless Chromium never paints the page after a cross-document view transition (pagereveal never fires; a plain two-page test does the same), so any headless Chromium test that clicks between member pages must run with reduced motion or a visible window. A visible window (Chromium 149) and WebKit 26.5 both run the cross-fade."
  - "Safari re-downloads /my/sw.js (no-cache, no ETag) on every tab, 1.25 KB gzip now (0.8 KB before the early-load code). An ETag answered with 304 would make that ~0; serve_asset has no request to read If-None-Match from, and member_portal.serve is the stopwatch session's, so it was left."
decisions:
  - "One stylesheet file every church shares (/my/app.<hash>.css), plus small Youth, Kids and sign-in files, each linked only where it was inline before and in the same order; a page carries only its church's colours as --mbt-<token> values (~1.3 KB). The templates are unchanged: each $token reads var(--mbt-token) in the file, and a test proves file + colours == the old inline sheet, character for character, for four bases and three spaces."
  - "The file is answered without looking the church up, on any host, public, a year, immutable. A hash from the other side of a deploy still gets today's file but no-store, so neither the browser nor Cloudflare keeps the wrong file under the new name. custom_domain_cache lets only that answer through untouched, so Cloudflare may keep the file once for every custom domain (it is the same for all)."
  - "The offline page keeps the whole sheet inline: with no connection the file may not be there."
  - "Personal pages stay no-store. For Safari, a touch or hover on the tab bar asks the service worker for that tab and the answer waits in the worker's memory, used once, ten seconds at most, dropped by any form, any POST, or any other page opened. Chosen over a short private max-age on tab pages: nothing personal is written to the HTTP cache, Back after sign-out can't show a cached page, and a page after a change can't come from a copy fetched before it."
  - "Chrome gets speculation rules (its own prefetch, kept in memory, dropped if cookies change): moderate with a mouse (200 ms hover or press), conservative on a touch screen (the touch itself; Chrome's phone moderate also prefetched a tab with no touch at all, measured). Rules go only to Chromium (navigator.userAgentData): Playwright WebKit says it supports speculation rules but loads nothing, so each browser asks exactly one way."
  - "Never loaded early: News (its GET marks posts seen), the page you are on, anything outside /my, anything with a query, and any form (sign-out is a POST form). Only links inside the tab bar and the computer sidebar (.mb-nav)."
  - "The cross-fade is one block, member_app_ui.MOTION_CSS: @view-transition inside prefers-reduced-motion:no-preference, a 0.18 s cross-fade of the page and the top bar, and the tab bar never fading (the old one stays drawn and the new one is laid over it). Faded with the page, Safari dimmed the bar mid-way, and on Give it vanished for a few frames: Safari takes the new page's picture before the parser reaches the bar at the foot. The bars are named only while a change is under way (:active-view-transition), so at rest every page draws as before."
  - "Fonts unchanged: Google Fonts' CSS and font files come from the browser's cache on every tab (0 bytes), preconnect and display=swap were already there."
  - "MEMBER_APP_FAST=off is the way back for all of it: the whole sheet inline, nothing early, no cross-fade."
related: [2026-10-20-member-app-speed.md, 2026-10-20-member-app-lookups-together.md]
---
Built in one PR. The member app's whole stylesheet (~88 KB) was inline on every page; now it is
one shared file per look (app, youth, kids, sign-in), kept a year, and a page carries its
church's colours only. The next tab starts loading on a touch (Chrome: speculation rules;
Safari: the service worker's one-use memory), and tabs cross-fade with the tab bar held.

Measured 2026-11-18 on a local copy of the pages with sample data (scratchpad harness: the real
renderers, prod's no-store headers and gzip, a 0.6 s server delay per tab), phone size 390x844,
a 100 ms touch, median of five warm taps, Playwright Chromium 149 and WebKit 26.5:

| | before | after |
|---|---|---|
| bytes per tab tap, Chromium (gzip) | 20.8 KB | 4.3 KB |
| bytes per tab tap, WebKit (gzip, incl. its sw.js check) | 22.1 KB | 6.0 KB |
| touch to the new page's first frame, Chromium | 775 ms | 652 ms |
| touch to the new page's first frame, WebKit | 766 ms | 654 ms |
| requests to the server per tap | 1 | 1 (the early load is the page) |
| frames with the tab bar missing during taps (video) | 0 | 0 |
| cross-fade | none | 0.19 s (Chromium), 0.21-0.23 s (WebKit); none with reduced motion |

A page's HTML went from 95-114 KB to 8-29 KB; the stylesheet is 88 KB once (17.9 KB gzip). A
cold first visit fetches it as one more request, about the bytes it saved on that page; every
page after saves it. Pixel check: 264 Chromium pages (three churches, black / white / light gray
bases and three accents; Church, Youth, Kids; phone, 1280 and 1440 wide; light and dark scheme)
matched origin/main pixel for pixel; WebKit: see the PR. Before building, both repos' worklog/
had only the 2026-10-20 member-app speed work (server reads), nothing on the client side.
