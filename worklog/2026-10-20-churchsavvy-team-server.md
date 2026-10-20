---
title: ChurchSavvy — team and roles, the booth's typo fix, workspace colors (server)
date: 2026-10-20
agent: Claude Code (Claude Opus 5.5)
asked: '"these are a go" (Kevin 2026-10-20, canvas board 30: Setup, Team and roles, Workspace colors)'
status: in progress
prs: [kmj-intake-server#1533]
migrations: [supabase/APPLY-2026-10-20-worship-team.sql (APPLIED LIVE 10/20 after a rollback probe)]
left_undone: ["the Setup page, Team and roles, Workspace colors and the booth's fix in the app (solutionist-studio, next PR)", "invites by text from our own number (texting isn't open yet): the invite gives a link to copy and send any way", "the step-up passcode Solutionist asks before granting a seat isn't asked here (a team part opens only the worship routes, never the business)"]
decisions: ["a volunteer is NOT a Solutionist seat: any active business_users row reads the whole business through is_business_member (people, giving, books), so the team lives in its own server-only table (worship_team) and opens only the worship routes", "four parts, more than one each: planner (plans, runs), worship leader (plans, songs; never the screens), booth (runs, fixes a typo; never the plan), admin (everything, the setup, the team); the owner, an admin or a manager of the church is an admin without an invite; a viewer or member seat reads only", "an invite is a link (/churchsavvy/join?t=…) that works once, for a month, emailed when there's an email; joining a church you're already on adds the new parts", "the booth's fix changes the slide's own lines in the song, the same number of lines, and refuses (409) when the song changed since the slide went up", "the church's starting workspace colors (dark, light, or light to plan and dark to run) live in the look"]
related: [kmj-intake-server worklog/2026-10-20-churchsavvy-loops-quick-server.md]
---
Step 7 of the approved round-4 ChurchSavvy build (canvas board 30), server side.

**The team (`worship_team.py`, new):**
- Admin routes: `GET /worship/team`, `POST /worship/team/invite`, `PUT` and `DELETE /worship/team/{id}`.
- For the person joining: `GET /worship/team/invite?t=` tells the sign-up screen whose team it is (no sign-in), `POST /worship/team/accept` takes the link, and `GET /worship/team/mine` lists the churches they're on.
- `roles_of` / `require(biz, user, what)` decide every worship route now (songs, Sundays, screens, look, live, library):
  - plan: planner, worship leader, admin
  - songs and library: planner, worship leader, admin
  - run the screens: planner, booth, admin
  - fix a typo: every part
  - setup: admin
- Refusals say which part does it.
- `/worship/status` and the Sundays list now answer `can` (each part) and `roles`.
- Only the setup sees screen links.

**The booth's typo fix:** `POST /worship/songs/{id}/fix` (board "Live": "Fix the words on slide 5"). The slide's lines, as they were, become the fixed ones in the song itself.

**Workspace colors:** the look keeps `workspace`: dark, light, or split (light to plan, dark to run).

**The ratchet:** the invite link is a gate of its own (`invite_from_token`, a HINT beside `screen_from_token`). The church comes from the invite row, never from the caller.

**Checks:**
- The worship suites, the access ratchet and the sweep pass (184).
- `test_worship_team.py` (new) covers invites, joining, each part's yes and no, removal, the fix and workspace colors.
- `worship_team_db.mjs` (new, in CI) runs 16 checks on a real Postgres.
- Sabotage rehearsals went red, then green after restoring:
  - letting the worship leader run the screens;
  - letting any seat be an admin.

**After an independent review (8 findings; the server's four fixed here):**
- `worship_team` now has an entry in account_lifecycle's EXPORT_EXCLUDED; without it the export list's own test failed.
- An invite a month old shows as expired, doesn't block inviting the same email again, and gets a fresh link (`POST /worship/team/{id}/new-link`, which retires the old link).
- A second accept that lost a race to the same person's first now reads as joined, not 503.
- The fix names its slide (`start`, from each lyric slide's place in its part, `worship_lyrics.slide_starts`), so a chorus that repeats lines gets the copy the booth means. It refuses a blank line, which would re-split the slides mid-service.
- Sabotage rehearsals for the race and the slide's place went red, then green.
