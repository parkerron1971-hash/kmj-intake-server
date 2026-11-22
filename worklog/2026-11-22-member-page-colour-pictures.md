---
title: "Member page: App colour, Highlight colour and Pictures from the office (backend)"
date: 2026-11-22
agent: Claude Code (Claude Opus 5.5)
asked: "Kevin approved the Member page mock ('this is a good build'), then the Highlight colour addition ('build this'): App colour, Highlight colour and Pictures on Settings → Member page."
status: shipped
prs: []
migrations: []
left_undone:
  - "'Use another' on the latest message and on a series: those pictures pick themselves (series art, else the YouTube still) and no spot in the app stores a choice for them, so the office lists them as automatic, with no Change. Giving them a spot means teaching each place that draws a message's art (member_portal_sermons._art, member_lumen_share, member_mini, member_lumen_stories) to read it."
  - "The Bible reader's own night paper keeps its fixed gold (member_lumen_bible, the lm-read night sheet); the highlight feeds the --gold tokens everywhere else in the new look."
decisions:
  - "App colour is settings.member_portal.app_colour, read FIRST by member_app_ui.brand_colour; unset (or not a wearable colour) it changes nothing. Callers that aren't the member app pass app=False: church_move_setup/_ready (the brand kit check) and devotional_daily (/daily, which never names the app)."
  - "Highlight is settings.member_portal.app_highlight. It replaces the gold slot of the palette (gold, on-gold, gold-ink, deep, night, lit) only on pages in the new look (member_lumen.page()), so today's look keeps its gold Bible tab. Ink is 4.5:1 on the base (a deeper shade on white) and lit is checked on black."
  - "Office pictures (member_pictures_office.py) save through member_app_pictures.put, the app's own save now shared by both routes: same store (settings.member_portal.pictures), same upload checks (type, 12 MB, size, the small model's check), same rate limit, same cache forget."
  - "Who may in the office: the owner; or someone with an office login on the church whose login email is the email on a named photo editor's record. Everyone else 403 (a stranger with no login gets the usual 404)."
  - "A message's video still is fetched on the server (member_yt_pictures.get, wide), made safe like an upload and kept; not sent to the model check, since the app already shows these stills unchecked."
  - "Remove = the spot's default picture (url ''), the same as the app's 'Use the default picture'."
related: []
---
The office can now give the member app its own colour and highlight, and change every picture spot
from Settings → Member page. Member pages are byte-identical with nothing set (dumps: 951 pages, both
looks, main vs branch).
