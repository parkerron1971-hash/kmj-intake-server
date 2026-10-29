---
title: A church's office door (its own sign-in, invites and the lane by name)
date: 2026-10-28
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-10-28: "should we consider change up solutionist key access for those that have a key so it doesn''t look like the admin access point?", then "yes build the church-branded office door"'
status: shipped
prs: [kmj-intake-server#1639, solutionist-studio#1401, solutionist-studio#1402]
migrations: [supabase/APPLY-2026-10-28-seat-lane.sql]
left_undone:
  - "The door's address is the app's (mysolutionist.app/office/<slug>); the church's own address only sends people there (a session lives on the app's address)"
  - "Logins that signed up before the lane was kept show their lane only when their areas are exactly one lane's; an admin given no lane shows none (Minnie's Treasurer seat is set by hand)"
decisions:
  - "office_door.py: a church's live site (business_sites, not offline, is_church) has a door. Its look is the member app's (member_app_ui.palette over public_form_theme.resolve_theme): base, colour, logo (the brand kit's, else the hand-built site's wordmark on the API host). Only what the public site already shows"
  - "GET /team/door?church=<slug> (no auth) gives the look; {ok: false} for anything else"
  - "/team/validate adds `door` for a church's invite, so links sent before the door existed open branded too"
  - "A church's invite opens at <app>/office/<slug>?team_invite=…, and its email comes from the church ('Your Love City Church office login'), with no Solutionist sign-up pitch. Other businesses keep the plain link and email"
  - "<church address>/office (public_site's catch-all, beside /my and /here) sends a church's address to its door; any other site keeps its own /office page"
  - "business_users.lane keeps the lane by name: written by an invite that carries one and by Logins & areas (the lane the areas are exactly). /team/my-role returns `lane` (stored, else the areas' lane) for the office's header; only the stored one can say Treasurer"
---

Office logins signed in on Solutionist's own page, the owner's door. A church's office now has its own: its name, colours and logo, "Office", and invites that come from the church.

Shipped 2026-10-29: #1639 merged at 00:48 UTC (deployed; migration applied before it), the app's half (solutionist-studio#1401) at 00:51, and #1402 (the door's logo up to 88px tall) at 01:06. Checked live, signed out: lovecityc.com/office opens Love City's door in black and magenta with its logo. Kevin then asked for the logo itself to be fixed: Love City's brand kit logo (a 1080x1080 square with the wordmark in its middle) was cropped to the wordmark (947x374), uploaded beside it, and set as logo_url and assets.primary; the original stays as assets.square.
