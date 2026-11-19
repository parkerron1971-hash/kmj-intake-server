---
title: Member app new look (Lumen Next) — the type, and each church picks its pairing
date: 2026-11-19
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, after the Lumen Next mock and its type board: "go with font A and build all the moments but allow for each church to choose what font they want for the list that we selected from." A = Literata + Figtree (default), B = Fraunces + Onest with Literata for reading, C = Mona Sans with Source Serif 4 for reading. Self-host the fonts, apply them in Lumen to the type board''s scale, and let the church''s owner pick A, B or C in Settings → Member page.'
status: shipped
prs: [kmj-intake-server (this PR), solutionist-studio (the picker, after this deploys)]
migrations: []
left_undone:
  - "Home's layout is untouched (Kevin is still deciding Home); Home's headings only take the new faces and sizes."
  - "Not checked on a real phone. Playwright's Windows WebKit build doesn't apply a variable font's weight from font-weight: it draws each face at its default instance (Figtree 300, Fraunces 900, Mona Sans 200), as it drew Geist before this. Its shots show the faces, sizes and metrics, not the weights. Safari on iPhone and Mac maps font-weight to the weight axis."
  - "Fonts are latin and latin-ext only, as on the type board. A name in another script draws in the phone's own font."
decisions:
  - "The files are Google Fonts' own woff2 (variable, latin + latin-ext per style), unmodified, in assets/member-fonts with each family's OFL licence and a README naming every source URL. Served at /my/fonts/<face>.<hash>.woff2 (member_lumen_fonts.serve): the same file for every church and host, public a year and immutable when the hash is today's, no-store for another hash, Access-Control-Allow-Origin * so the owner's settings can show samples. custom_domain_cache passes them through on a custom domain like the stylesheets (SHARED_FONT_RE)."
  - "A Lumen page drops today's Google Fonts link (member_app_ui.FONTS: one render-blocking stylesheet and two more connections) and preloads its pairing's faces instead (A and B two, C one). The italic and the reading face come when a page uses them."
  - "Every face, its fallback (Georgia or Arial, sized with size-adjust and ascent/descent overrides so nothing jumps) and each pairing's variables are the last part of the Lumen sheet (member_lumen_fonts.template(), after every page's block), so the type sets every block's fonts. body.lm sets --mb-ui, --mb-serif, --mb-display and --font-body (re-declared so the give page's var(--font-body) follows), plus --lm-read, --lm-num, --lm-dw/--lm-iw (heading and italic weight), --lm-dtr, --lm-dvar, --lm-dst, --lm-nw/--lm-nst/--lm-nvn. body.lm.lm-fb and body.lm.lm-fc change them for B and C."
  - "The type board's numbers: Display XL 44/44 (.lm-disp), Display M 36 (.lm-disp.s; .m is 40), Title 20/24, Body line-height 23/15, Bible reading 19/33, Give's amount 94 in the pairing's figures (tabular for A and B; C's tabular zero is slashed, so regular figures). Labels were already 11/13 650 +14%."
  - "The pick is businesses.settings.member_portal.fonts (a, b or c; nothing is A), read from the church's row the page already has: no new read. PATCH /member-portal/{biz} {fonts} is owner-only like every other member-page setting (a 400 for anything else, nothing written). GET returns fonts, font_choices, fonts_default, font_faces (for samples) and fonts_open: whether the new look can be seen at this church (MEMBER_LUMEN: preview only the platform owner at his church, owner that church, on everywhere; preview asks nothing for anyone else)."
  - "Off is byte for byte today's look: 217 pages through the Give/Watch harness (giving on/off × LIVE_ROOM on/off × normal day, Sunday, live) and 81 through the people harness, compared against the same commit before the change (clock times in the fake data aside)."
related: [2026-11-18-member-lumen.md, 2026-11-19-member-lumen-give.md, 2026-11-18-member-app-tabs-fast.md]
---
`member_lumen_fonts.py` holds the pairings, the faces, the pick and the type rules.
Tests: `__tests__/test_member_lumen_fonts.py`.

Font bytes (latin files; a phone fetches latin-ext only for a name that needs it):

| | First load | Repeat load |
|---|---|---|
| Today (Google: Geist + Newsreader roman and italic) | 308 KB, plus Google's stylesheet and two connections | the stylesheet is asked again every day |
| A (Figtree + Literata roman and italic) | 243 KB | 0 (same address for every church, kept a year) |
| B (Onest + Fraunces roman and italic; Literata on Bible pages) | 304 KB, +110 KB on a Bible page | 0 |
| C (Mona Sans roman and italic; Source Serif 4 on Bible pages) | 203 KB, +122 KB on a Bible page | 0 |

The Lumen sheet grows 12.5 KB (1.6 KB with brotli), once. A Lumen page's HTML is 104 bytes
smaller (the Google link is longer than the two preloads).

Measured locally (the Give/Watch harness over the test fake, so database time is ~0;
median of 30 Server-Timing totals, main / this branch, fresh harnesses): with the switch on,
Home 4.0 / 4.3 ms, Bible 2.2 / 2.3, a chapter 2.0 / 2.0, Give 1.7 / 2.1, a group chat 3.8 / 4.5,
Connect 2.7 / 2.8, Watch 2.2 / 2.2; off is the same spread (medians move a millisecond or two
run to run). Reads per page are identical on main and this branch,
off and on.
