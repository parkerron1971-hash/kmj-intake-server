---
title: Member app Lumen Next — motion, and Watch and Live as a cinema
date: 2026-11-19
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, on the Lumen Next mock (artifact 2nFp9X3q72qbs78oGVh9A4): "go with font A and build all the moments". This part: the motion system (shared-element page moves, a springy tab highlight, spring easing, content arriving in a stagger, headlines settling with the italic word last, reduced motion respected), Watch and the live room dark and full-bleed, and live reactions rising over the video from what the room already has. Not the mini-player (an app-shell change), not Home (Kevin is still deciding it), not fonts (another helper).'
status: shipped
prs: [kmj-intake-server (this PR)]
migrations: []
left_undone:
  - "The mini-player (a sermon docked above the tabs while you browse): every tap still loads a new server page, which stops the player. Phase 3, an app-shell change."
  - "Home's moments (pull to refresh, I'm coming turning into a pass, Sunday morning Home): waiting on Kevin's Home decision. Home does get the shared moves, the stagger and the settling heading, like every main tab."
  - "Live reactions: only hearts are real reactions (the service's hearts count). 'Amen' and 'Praying' are the room's quick replies: a tap sends the chat line (at most one each six seconds per word; taps in between only rise on your phone), and any chat line that is just Amen, Hallelujah or Praying rises over the video for everyone. Reactions that don't post a chat line would need a count per kind on live_sessions (a migration)."
  - "Who's watching shows initials (the room's faces: you once you're here, then who spoke last) and 'N here with you'. The mock's photos and 'Maya, Luis, Dana and N others' would need the here list's names and photos (a read the room doesn't make today)."
  - "Watch's 'Next live' row has no Remind me (NEW in the mock; no reminder exists)."
  - "Praying hands use the app's prayer icon (a heart in a speech bubble), not the mock's hands."
  - "Not checked on a real phone. WebKit (Playwright 26.5 on Windows) never paints a moving element's new picture while a cross-document view transition runs: the top bar, the player and the conversation's face appear when the move ends. main's cross-fade shows the same in that build, so the bars keep main's 0.18 s; real Safari 18.2+ needs checking."
decisions:
  - "One new module, member_lumen_motion.py: its CSS is the last block of member_lumen_ui.templates() (so it's in /my/lumen.<hash>.css and nowhere else); its script (JS, 2.2 KB) goes in a Lumen page's <head> (member_portal._shell, so pagereveal is heard even when a long page is first painted before its foot is parsed); Give draws its own document, so there it rides at the foot (member_portal.lumen_chrome)."
  - "Direction: a click on one of our links notes the page it leaves (depth: main tab 0, pushed page 1, conversation 2) in sessionStorage; the next page, on pagereveal with a view transition, sets html[data-vt=push|pop|tab|fade] and removes it when the move ends. Coming back (shallower), it names the link that leads to the page it came from, so the picture or the face flies back into its row."
  - "What travels: on the way out the script names the clicked thing (a conversation row's face and name; a message link's picture in Watch's latest, a row's thumbnail or Home's tile); on the way in the CSS names the player (.mb-player) and the conversation bar's face and name, only under html:active-view-transition. The tabs are named one by one by href during a change, so the floating highlight slides under their labels."
  - "The tab bar floats (12 px off the edges, rounded, var(--bg) solid, a ring and a soft shadow) with a tinted highlight that springs (linear() spring) to your tab, and the tab's icon pops; a computer's sidebar is unchanged."
  - "The cinema is every page under the Watch tab (body.pg-watch: Watch, a series, a message, the live room, Live between services). It takes the new look's one dark switch (member_portal._shell's lumen_dark, the reader at night's from #1966: body.lm-dark and the phone's bar), and this sheet makes that dark the cinema's neutral black (body.lm.lm-dark.pg-watch) instead of the reader's warm night: dark tokens over the app's own variables (the family inks become their -lit shades, the deep surfaces their -night shades, the church colour its -lit shade lightened toward white), html behind it black and the phone's bar #050506 (member_lumen_motion.CINE_BG). Pages in today's markup (a series, a message) darken through the same variables; the old look's black base was built on them."
  - "Watch: the visually hidden heading 'Watch & listen' (the bar says whose it is), the next live as a card (red when live), the latest message edge to edge (310 px), 'Latest message · <date>' and its title in serif with the last word italic, Watch as a white button, the series as posters on a rail (the art over the kicker and the serif name), every message as rows with wide thumbnails."
  - "Live: the room's hearts rise over the video instead of beside the box (#lv-hearts is hidden; the reactions script mirrors each heart the room's script draws there), and Amen/Hallelujah/Praying chat lines rise too (lines the page already had, and redraws, never). member_portal_live.ROOM_JS is untouched; the new look appends member_lumen_motion.ROOM_JS. Under the title: the room's faces and 'N here with you' (the count kept fresh by the room's own poll through data-here-n), then Amen · heart · Praying while the box is open."
  - "Reduced motion: every animation, transition and view-transition rule sits in @media (prefers-reduced-motion:no-preference) (a test walks the CSS), except the reactions, which fade in place. The script names nothing when the phone asks for less motion."
  - "Off is byte for byte today's look: 217 pages from the Give/Watch harness (12 scenes) and 81 from the people harness, compared with origin/main (clock times aside: the fake's rows are minutes old). The same reads off and on (a test, and the read counter over Watch, Live, Give)."
related: [2026-11-18-member-lumen.md, 2026-11-19-member-lumen-give.md, 2026-11-18-member-app-tabs-fast.md]
---

# Lumen Next — motion and the cinema

## What moves

| Move | Where | How |
|---|---|---|
| Push / pop / tab | every Lumen page | cross-document view transitions; html[data-vt] picks the keyframes |
| A message's picture into the player | Watch, Home's tile → a message | named on click (out), `.mb-player` named during the change (in) |
| A face and a name into the bar | Messages → a conversation, and back | same, `.lm-irow` → `.lm-thead` |
| The tab highlight | the tab bar | `lm-ind` group with a linear() spring; tabs named over it |
| Arrive | a main tab's blocks | `lmArrive`, 60 ms apart, fill backwards (no transform left behind) |
| Settle | every `.lm-disp` heading | `lmSettle`, the `<em>` 0.22 s later |
| Press | buttons, rows, tiles, posters | spring back on release |
| Reactions | the live room | hearts mirrored from the room's script; Amen/Praying chat lines |

## Checked

- Chromium (renderer never backgrounded, so the view transition finishes headless) and WebKit 26.5, 390×844 @2x: Watch, Watch live, the room, between services, a message, Home, Bible, Connect, Messages, the church conversation; mid-move frames for Watch → message and back, a tab change, a conversation and back, first paint; reactions over the video.
- Switch off: 298 page dumps identical to origin/main.
- Reads: identical off and on.
