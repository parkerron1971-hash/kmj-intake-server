---
title: "Member app: the church's own icon, name under it, and opening screen (backend)"
date: 2026-11-22
agent: Claude Code (Claude Opus 5.5)
asked: "Kevin approved the Member page mock's 'Icon & opening screen' ('build this')."
status: shipped
prs: []
migrations: []
left_undone:
  - "An SVG logo can't be drawn on the server (Pillow reads JPG, PNG and WebP). A church whose only logo is an SVG gets its initials on the chosen background, and can upload a square icon instead."
  - "Phones that already added the app keep their old icon until they add it again (iOS). Android picks up the new icon within about a day. That's how phones work, and the office page says so."
decisions:
  - "Default: the initials icon stays until the church saves a choice, even when a brand logo exists. A wide wordmark can look small inside the safe zone, so the church sees the preview first. The office pre-selects 'Your logo' when there is one, so it's one Save. Member pages and dumps are unchanged until then."
  - "Storage: settings.member_portal.app_icon {source logo|upload, background colour|black|white|photo, photo, ground, at}, app_icon_upload (the uploaded 1024 PNG) and app_short_name (12 at most)."
  - "Icons and opening screens are drawn on the server with Pillow, from the church's own storage or site files only (member_lumen_share.picture_bytes), and kept per server copy. The bytes are kept for an hour per choice and the drawings are LRU'd. They're served with Cache-Control a day plus an ETag, and every address carries ?v=<choice> so a new choice is a new picture."
  - "The logo sits inside the maskable safe zone (the middle 80% circle, with 8% air). A see-through logo that stands less than 1.8:1 off its background is drawn in white or near-black."
  - "The in-app opening screen is two pseudo-elements on <html> (the background plus /my/opening-mark.png, and 'POWERED BY / Solutionist' as CSS text). A head script adds the class only in display-mode standalone, once per launch (sessionStorage). It lifts after about a second, or at load, and always by 2.5 s. With reduced motion there's no fade. Without script, nothing covers the page."
  - "The manifest gets maskable icons, background_color = the background and short_name only when the church chose them."
  - "An uploaded icon is checked like the app's pictures (type, 12 MB, square within 2%, at least 1024, the small model's check)."
related: [2026-11-22-member-page-colour-pictures.md]
---
Settings → Member page → Icon & opening screen saves here (PATCH app_icon, app_short_name; POST /member-portal/{biz}/app-icon).
The iPhone opening screens (/my/startup-WxH.png, 18 device sizes) and the in-app opening screen ship only with a saved choice.
