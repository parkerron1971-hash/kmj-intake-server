---
title: Love City Church site photos from the church's Facebook originals
date: 2026-10-14
agent: Claude Code (Claude Opus 5.5)
asked: "Get Connected should show fellowship, What We Believe needs no picture, Join us live needs live worship; look deep on Facebook for better photos; only photos from the last 2 years"
status: in progress
prs: [kmj-intake-server#PENDING]
migrations: []
left_undone: ["Pastor portraits (kevin, jessica, pastors.webp) came from the old website and can't be dated; Facebook has nothing recent to replace them", "Sisters in the City uses a Pink Out Sunday photo (Oct 16, 2024): Facebook has only flyers for Sisters in the City events", "minister-podium.webp was already unused before this work and is still in assets/"]
decisions: ["Photos come only from facebook.com/lovecitynation (the church's real page), posted on or after 2024-10-13, people only, no child as the main subject", "Each photo is the full-size original from Facebook's Download, made into the site's plum duotone WebP under the 150 KB test cap", "What We Believe and the Give header have no picture; Give's photo moved to About", "Every ministry in the list has a photo, one 3:2 shape, beside the words on a wide screen and under the name on a phone", "Love Works shows the pantry's opening day (Oct 7, 2025), not Community Day", "No asset name contains 'prayer': the forms test flags any request URL containing it", "Poster --fit values are measured widest line x 1.008, so no headline wraps from 360px to 1440px"]
related: [2026-10-13-love-city-church-site.md]
---
Kevin's photo pass on the Love City Church site (`sites/love-city-church/`),
reviewed with him in two rounds of before/after previews. All 14 Facebook
photos that were already on the site are now made from full-size originals
instead of viewer-resolution captures. New photos: Get Connected (City Serve
volunteers arm in arm), Join us live (the worship leader on stage), a hug for
"There's a place for you", one photo per ministry (youth, Sisters in the City,
prayer circle, pastoral care, baptism), the pantry's opening day for Love
Works, Training (the ministers at Good Friday 2026), Serve with us (Love in
Action Day), the VBS 2026 team on Events, and the prayer circle beside the
Connect prayer form. The poster headlines were refit to their measured width
so none wraps onto an extra line. Unused assets were removed. Before swapping a photo here, check
its Facebook post date against the two-year rule.
