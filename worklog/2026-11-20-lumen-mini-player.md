---
title: Member app Look 5.1 — the mini player (a message keeps playing while you move around)
date: 2026-11-20
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, approving Look 5.1 of the member app''s new look: "this is awesome. much better design. lets build this including the new still to build!" This part (helper G, "mini"): playback that survives moving around the app, with the mock''s mini player above the tab bar (frames a-mini, a-player): picture, title, "Playing · 12:04 of 38:12", play/pause, close, a hairline of progress; tapping it goes back to the message at the same spot. Behind its own switch, MEMBER_MINI_PLAYER = off|preview|on, default preview. Nothing changes for anyone when nothing is playing.'
status: shipped
prs: [kmj-intake-server (this PR)]
migrations: []
left_undone:
  - "A video from another site (YouTube, Vimeo, Loom, Facebook, our own recording's player) keeps playing across pages the same way, but its time can't be read from outside its frame: its bar says 'Back to the message' with close (which stops it) and no play/pause or time. The page counts it as playing once the member has tapped into it (the window loses focus to that player). If a phone doesn't report that tap (not checked on a real iPhone), leaving its page stops it, as today. YouTube's and Vimeo's own message protocols could give the time and a pause button later."
  - "One message at a time: opening another message's page from inside loads it the ordinary way (the playing one stops), and a devotional's Listen or any audio started in the frame pauses the message."
  - "Not on a real phone yet. Unchecked there: iPhone home-screen app safe areas inside the frame (the frame is inset by the page's safe areas and paints the strips in the page's colour; if WebKit hands the frame its own insets the script notices and drops the inset), the keyboard in a conversation opened over a playing message, the lock-screen controls (Media Session), and Android's app."
  - "What video_url values look like in production wasn't checked: the read-only query was refused from this session. The query for Kevin is in the PR."
decisions:
  - "The app in a frame, only while something plays (not swapping page content in place). Every tap in the member app is a whole server page, and each page's scripts expect to run once on a fresh page (document-level listeners, polls, the motion script). A frame runs every page exactly as it is (its scripts, forms, view transitions, tab bar) with zero changes to any page, so the risk stays on the message page. The message page stays the page in the browser with its player never moved (moving an <iframe> reloads it); a tap on one of the app's links while playing pushes the link's address and opens its page in a full-screen frame laid over the message; inside the frame it's ordinary browsing."
  - "History is the browser's: pages inside the frame are the frame's history, back past its first page shows the message, forward shows the frame again; the address bar follows the frame (replaceState on each page), so reload loads that page as an ordinary page and playback stops cleanly. The bar's tap pushes the message's address and shows it (or, if nothing happened in the frame yet, goes back)."
  - "The bar lives on the message page, laid over the frame, so it never reloads or blinks between pages. It takes the frame's page colours (its --bg, --fg, --lm-line... read from the page, so Light, Dark, Same as my phone and the cinema all work), sits 8 px over the frame's tab bar at the tab bar's width (beside the sidebar on a computer), and the frame's page gets room at its foot (body.lm-mini-pad). Hidden on pages with no tab bar (the reader, a devotional's day, a conversation), while typing, in the live room (which pauses the message; a video from another site stops), and on the message itself."
  - "Loads the ordinary way (playback stops): another site, downloads, new-window links, Give and gifts (payments), the statement, a group's live meeting (camera, microphone), photos, Kids, the preview links, another message, and any page that isn't a new-look page (signed out, an error, Youth, the old look) or that the frame can't show."
  - "Headers: member pages refuse every frame (X-Frame-Options DENY, frame-ancestors 'none'). member_mini.FrameForStage (pure ASGI, kmj_intake_automation) answers a page asked for by a same-site frame (Sec-Fetch-Dest: iframe and Sec-Fetch-Site: same-origin, under /my, switch not off) with SAMEORIGIN and 'self'; another site's frame is still refused, and a browser without fetch metadata gets the refusal (the script then loads the page the ordinary way). Any other value is left alone."
  - "The service worker leaves a frame's page to the browser (member_app_install.SW_JS: `if (e.request.destination === 'iframe') return;`). Measured in Chromium: the worker's own copy of a frame's page goes out with Sec-Fetch-Dest: empty, so it was refused. No /my page was framed before, so nobody else is affected; it does make every member's phone pick up the new sw.js once."
  - "The Look 5.1 contract: a playable element carries data-lm-media, data-title, data-sub, data-thumb, data-href (on the element or a box around it). Until the Watch helper's page lands, member_portal_sermons.render_sermon marks the existing player (member_mini.mark) when the switch shows it; the picture is the series' own art, else the church's photo named for the series (the message art's rules), else the church colour. The script is added by _shell to a new-look page whose markup has a marked player, so it follows the Watch page's markup."
  - "The switch: off | preview | on, preview by default; only on a page in the new look; preview is the platform owner's preview or own sign-in (under MEMBER_LUMEN=preview that is already who sees the new look; otherwise member_lumen's cached church-owner answer, asked only for the owner's own sessions). No reads."
related: [2026-11-19-lumen-next-motion.md, 2026-11-18-member-app-tabs-fast.md, 2026-11-19-member-lumen-give.md]
---

# Look 5.1 — the mini player

## What a tap does while a message plays

| Where the tap goes | What happens |
|---|---|
| Any app page under /my (Home, Connect, Bible, Messages, Me, a group, events…) | opens over the message in the frame; the message plays on; the bar sits over the tab bar |
| The playing message (the bar, or any link to it) | the frame hides; the player is where it was, still playing, the page scrolled where it was |
| Browser back / forward | the frame's own history, then the message; forward shows the frame again |
| Reload | the page in the address bar loads the ordinary way; playback stops |
| Another message, Give, gifts, statement, a group's live meeting, a photo, Kids, the preview links | the ordinary page load; playback stops |
| Another site, a download, a new-window link | as today |
| Close (×) | stops it; the bar goes; the next tap is an ordinary page load |
| Nothing has played | nothing changes: every tap is the ordinary page load |

## Checked

- Chromium and WebKit 26.5 (Windows), 390×844 @2x, light and dark: play, Home, Connect, a link the page answers itself (stays the page's), pause and resume from the bar, Bible (bar), the reader (no bar, still playing), back to the message (same spot), back ×2 / forward ×2, back past the frame's first page, live (pauses, hides) and back (Paused), Give (ordinary load), close (stops; next tap ordinary), reload (stops), a YouTube message ("Back to the message"). Every check passes in both, twice.
- Page dumps against origin/main (the home harness, 82 pages × 8 scenes, and the Bible harness, 59 × 5): the new look off (switch on): 951 identical; the new look on with the switch off, on, and both switches at their defaults: 951 identical each, the sheet's hash aside (the bar's rules are in it). The mini harness (messages with an audio file and a YouTube link, 6 pages × 3 looks): identical with the switch off; switched on, only the two message pages differ (the marks and the script).
- Reads: the same on all 82 pages (the home list plus both messages) with the switch on, off, and on main.
- Server-Timing medians (30 warm requests), main / branch on / branch asked by the frame: Home 10.2 / 11.1 / 9.6 ms, Watch 4.0 / 4.5 / 4.3, a message 4.1 / 4.2 / 4.3, Connect 5.5 / 6.2 / 6.2, Bible 5.8 / 5.4 / 4.9, Me 4.2 / 4.4 / 4.2 (noise). The message page is 14.1 KB bigger (the script; 5.3 KB gzipped); no other page changes.
