---
title: ChurchSavvy's home page, version 3 — the church from above, a booth you can try, what's in the booth
date: 2026-10-25
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-10-25, on canvas FDAysirAGzcrWosHuzijSA: "the mock designs could be much better ... creative and somewhat tech ... the animation feel"; "can we create a mock where people can test it out or type something in?"; "the hero area seems to have a similar feel to every website design we have made"; "really think about church and stages position"; "the booth test doesn''t fit my big screen ... have the ability to see both functioning"; "do you think the website reveal enough about churchsavvy?" then "yes mock the what''s in the booth section"; then, through the other session: "tell other so the updates can take place to the site."'
status: done
prs: [kmj-intake-server (this PR)]
migrations: []
left_undone:
  - "Before the site is public: SUNDAY_PLANNING and CHURCHSAVVY_BILLING are unset (Planning is owner-only, buying is off), the STRIPE_PRICE_ID_CS_* lines are empty, and CHURCHSAVVY_APP_URL / CHURCHSAVVY_SIGNIN_URL are unset, so Start goes to the Solutionist app's sign-up. The home page sells Planning and Both, as the pricing page already did. Kevin's switches."
  - "The pricing and Solutionist pages keep their 10/24 design; only the home page is new."
decisions:
  - "The home page is its own design, kept as files beside the module (churchsavvy_site/home.html, home.css, home.js, three drawings), like church_site/: a 230 KB page would bury churchsavvy_site.py. {{APP}} {{HOME}} {{PRICING}} {{SOLUTIONIST}} are filled per request and escaped; the drawings are inlined once (they need the page's CSS for their colors and motion). The drawings are made by scripts/churchsavvy_art_church.py and scripts/churchsavvy_art_stage.py and regenerate byte for byte."
  - "Order: the church from above (an isometric cutaway: the stage, the screen on the wall, the projector, pews with people, the stage display, the stream camera, the TV by the doors, the booth at the back, light from the booth to every screen), Plan it / Show it / Serve it, Try the booth, What's in the booth, Planning, The internet drops, then the rest. Planning moved above The internet drops so the two dark sections aren't back to back."
  - "Try the booth: the room from the back of the sanctuary (a truss, a stage with steps to the aisle, a lectern, mics, wedges, two side screens, people in rows) beside a booth you can use: type a reference or any line, Enter, and it goes up on the room's three screens, the stage display, the stream's lower third and a booth preview; four looks; Rehearse/Live; Start over. Side by side from 860px so the stage and the controls are on screen together (checked 1280x640 to 2560x1240); on a phone the room stays pinned while you type."
  - "The booth carries a few KJV passages (Psalm 23 and 100 whole, John 3:16, Proverbs 3:5-6 ...). All 66 book names are known, so a verse it doesn't carry says so ('every verse of the KJV and the WEB is there') instead of becoming a slide. Never a song's words: songs are titles and parts only. What a visitor types goes on the screens by textContent, never as markup; a test refuses innerHTML, outerHTML, insertAdjacentHTML, document.write and eval in the page's script."
  - "What's in the booth: six tiles, every claim checked against the app (solutionist-studio module-system, src/core/components/church/worship and lib/worshipShow.ts), and every one open to a church today (WORSHIP_SONGS=on; the screens, look, media, loops, keys and stage display have no switch): songs with parts, arrangements (Main/Short work), the key and times sung this year; the stage display's Band/Pastor/Notes/Countdown layouts (they work), with the app's own sample sermon points; the item kinds and the starter templates Classic Sunday, Simple service, Worship night; media and loops; Clear/Logo/Black and quick screens (they work); the look on the projector, an LED wall, the livestream (see-through for OBS, vMix or Resi), the stage and the lobby, following the booth above."
  - "The sample church is 'Your Church' (Riverbend Church is a real Austin church). The tagline is 'Every service, ready.' (#1579). og:image stays og-2.png on the apex."
related: [2026-10-24-churchsavvy-website.md]
---
The home page at churchsavvy.app (and /churchsavvy/site) is version 3 of the canvas Kevin worked through on 10/25. The pricing and Solutionist pages keep the 10/24 design, and their old home-only rules left the stylesheet.

Checks:
- `test_churchsavvy_site.py`: 9 tests, 2 of them new. One holds the plan values exact: `?signup=1&plan=churchsavvy|planning|both` on the home and pricing pages. The other holds the home page itself: every token filled, the drawings inlined, the section order, the booth's input, no markup-writing calls in its script, KJV in its data, no real church names.
- Every test file touching the public site and this module: 72 files, 1932 passed.
- In a real browser at 1440 and 390, with no script errors and no sideways scroll:
  - typing Psalm 23 puts it up on the room, the stage display and the stream;
  - typed `<img onerror>` shows as words;
  - Hebrews 11:1 says it isn't in the demo;
  - a look recolors the room and the tiles;
  - Rehearse leaves the room alone and Live puts the slide up;
  - Start over resets;
  - the stage layouts, the arrangements and the keys work;
  - the phone menu opens.
- Section positions match the approved mock to the pixel down to Pricing. Side-by-side screenshots are in the PR.
