# Desk: live-media

## 1. What it owns

- **Sunday streaming through our relay.** The church points its streaming
  software (OBS, ProPresenter…) at one address and key from the Stream card;
  the relay passes copies to YouTube and Facebook, members watch live in the
  member app, and the recording becomes an unpublished sermon draft.
- **The live room:** the team's Live page (start, chat moderation, pin,
  hearts) and the members' `/my/live` room.
- **In-app live video on LiveKit:** live classes (Academy) and church group
  meetings. Sunday broadcasts are NOT on LiveKit.
- **Recordings and storage:** the storage allowance per church plan, the
  smaller copy made two weeks after a service (also its download), deleting
  recordings.
- **Clips and video:** "Find my best clips" (uploads and services streamed
  through us), clip covers and posting, and Video Studio (short made videos).
- **ChurchSavvy presentation:** the Sunday presenter — songs, Scripture,
  slides, lower thirds, room screens, the booth, countdowns, lobby.

## 2. Where the code is

Backend (`kmj-intake-server`):
- Relay, system side: `stream_relay_router.py` — `/stream-relay` (overview),
  `/stream-relay/key`, `/stream-relay/settings`, `/stream-relay/watch/{session}`,
  `/stream-relay/media/{session}/index.m3u8`, and the relay's own calls
  `/stream-relay/relay/{verify,confirm,started,ended}` (`X-Relay-Secret`).
- Relay server: `stream_relay/` (MediaMTX `mediamtx.yml`, `agent/relay_agent.py`,
  `docker-compose.yml`, `setup/deploy.sh`, `setup/busy_check.py`, `README.md`).
  Runs on its own droplet; a merge does NOT deploy it.
- Live room: `live_router.py` (`/live`, `/live/start`, `/live/{sid}/chat|pin|mute|end`),
  `member_portal_live.py` (`/my/live/*`, the room's HTML/CSS/JS; shared with member-app).
- LiveKit: `academy_live_router.py` (`/academy-live`, shared with church-office),
  `academy_recordings.py`, `group_live_router.py` (`/group-live`),
  `member_portal_group_live.py` (member side, shared with member-app).
- Storage + copies: `church_storage.py`, `church_storage_router.py`
  (`/church/storage`, `DELETE /church/storage/recordings/{session_id}`),
  `recording_copy.py` (scheduler `copy_tick`, every 2 min).
- Clips: `service_clips.py`, `clip_finder.py`, `clip_covers.py` and
  `clip_posting.py` (both under `/media-library`), `media_library.py`,
  `media_library_router.py`, `clipper_worker/` (separate Railway service;
  vendored engine under `clipper_worker/vendor/`, `empty_spots.py`).
- Video Studio: `video_studio.py`, `video_studio_router.py` (`/video-studio`),
  `video_studio_worker.py`, `video_studio_models.py`, `video_cloud_renderer.py`,
  `video_hyperframes.py`, `video_*.py`, `video_worker/` (renderer service).
- ChurchSavvy: `worship_router.py`, `worship_show.py`, `worship_show_router.py`,
  `worship_media_router.py`, `worship_lyrics.py`, `worship_scripture.py`,
  `worship_sermons.py`, `worship_announce*.py`, `worship_team.py`,
  `worship_ministries.py`, `worship_proclaim.py`, `worship_count_auto.py`
  — all under `/worship`. Sermons shown publicly: `sermons_public.py`,
  `member_lumen_watch.py` (shared with member-app / websites).
- Tables: `church_streams`, `stream_sessions`, `live_sessions`, `live_chat`,
  `live_mutes`, `live_presence`, `group_live_sessions`, `academy_live_*`,
  `media_assets`, `media_clip_runs`, `video_projects|jobs|assets|revisions|messages`,
  `worship_services|screens|live|songs|team|media|settings|announcements|calendar|ministries`,
  `sermons`, `sermon_series`.
- Media lives in private Cloudflare R2 buckets (stream media, class recordings);
  everything is handed out as short-lived presigned links.

Frontend (`solutionist-studio`):
- `src/core/components/church/`: `LivePanel.tsx`, `StreamSetup.tsx`, `streamApi.ts`,
  `liveApi.ts`, `groupLiveApi.ts`, `SermonsPanel.tsx`, `StorageCard.tsx`,
  `ExtraStorage.tsx`, `worship/` (ChurchSavvy; standalone app at
  `worship/standalone/ChurchSavvyApp.tsx`).
- `src/core/components/media/` (`SermonClips.tsx`, `FindBestClips.tsx`, `ClipStudio.tsx`,
  `ClipDeck.tsx`, `ClipPost.tsx`, `serviceClips.ts`), `src/core/components/video/VideoStudio.tsx`.
- `src/core/components/course/live/`, `LiveClassroom.tsx`, `LiveClasses.tsx`,
  `src/core/lib/academyLive.ts`, `src/core/lib/worship*.ts`, `src/core/lib/churchStorage.ts`.

## 3. Rules that must not break

- Relay calls fail closed: no or wrong `X-Relay-Secret` is refused; 403 while
  streaming is switched off. `/relay/confirm` answers 503 on any failed read,
  never a short list (a key left out is cut).
- The media bucket is never public. Playback is live, a PUBLISHED sermon, or a
  manager's signed link; anything else 404s.
- A stream key is shown once; store only its hash.
- Never pull video from YouTube (its rules, datacenter blocks, rights): sermons
  on YouTube get the download-then-upload steps.
- Class messages reach the LiveKit room from the backend only (`send_data`),
  so a held message never reaches students.
- Storage and copy jobs: a failed read decides nothing (no hold, warning or
  removal on a guess). Clips always go before copies on the clip service.
- The clip service holds no DB or storage credentials; it fetches only from
  allow-listed hosts (`CLIPPER_SOURCE_HOSTS`, `CLIPPER_COPY_HOSTS`).
- ChurchSavvy: the church brings its own song words (we never ship lyrics);
  each worship-team part writes only its own part.
- Columns a live endpoint selects (e.g. `live_sessions.hearts`) must be applied
  before the deploy that reads them.
- Switches default safe: `SERVICE_CLIPS`, `CHURCH_STORAGE`,
  `CHURCH_STORAGE_SMALL_COPY` ship off/owner; `LIVE_ROOM` defaults on
  (`off` is the rollback). Turning one on for everyone is a Thursday + What's New.

## 4. Traps already hit

- A run on a church's real key has no quiet mode: members get "Live now" pushes and YouTube goes public.
- A standing YouTube stream needs no event: the first press is PUBLIC at once. Read Studio's `/livestreaming` page itself.
- MediaMTX default `writeQueueSize` overflowed on large keyframes, not bitrate; raised to 4096.
- Copy writers can exit once before the first keyframe and reconnect ~2 s later; harmless.
- Facebook auto-go-live needs Meta business verification + Live Video API review: parked; persistent key + manual Go live.
- Never deploy the relay during a service; `deploy.sh` refuses when it can't tell.
- Merging a `clipper_worker/` change redeploys the clip service and kills a running job: check `/health` busy false first.
- ffmpeg skips an unreadable segment and still exits 0; a crashed relay leaves no `EXT-X-ENDLIST`.
- The YouTube channel live embed fails when the channel isn't live or runs several lives; top-level it shows Error 153.
- LiveKit's plan has hard caps (participants, ingress, transcode minutes) that fail rather than bill.
- Deleting a business leaves its relay recordings in R2 (only Supabase Storage files are deleted).
- The media library's own upload cap still applies under a bigger church storage allowance.
- A Media-team person with no office seat opens ChurchSavvy via a team invite, not a login seat.
- The auto-mode classifier blocks prod container restarts and direct prod reads; plan checks around it.

## 5. How to check work

- `python -m pytest -q __tests__/test_stream_relay*.py __tests__/test_live.py __tests__/test_group_live.py __tests__/test_academy_live.py __tests__/test_class_recordings.py`
- `python -m pytest -q __tests__/test_service_clips.py __tests__/test_clip_*.py __tests__/test_clipper_service.py __tests__/test_recording_copy.py __tests__/test_church_storage.py __tests__/test_storage_path_confinement.py`
- `python -m pytest -q __tests__/test_video_studio.py __tests__/test_video_eyes.py __tests__/test_video_plan_repair.py __tests__/test_worship_*.py __tests__/test_member_lumen_watch*.py __tests__/test_sermons_public.py`
- Real-Postgres migration checks (PGlite): `PGLITE_MODULE=<…/pglite/dist/index.js> node __tests__/recording_small_copy_db.mjs`
  (also `church_storage_db.mjs`, `worship_*_db.mjs`).
- Frontend: `node scripts/check-stream-setup.mjs`, `check-service-clips.mjs`, `check-church-storage.mjs`,
  `run-academy-live-checks.mjs`, `npm run check:video-studio`, `python scripts/check-video-studio-ui.py`;
  previews under `tests/` (`stream-setup-preview.html`, `video-clips-preview.html`, `video-studio-preview.html`,
  `church-show-preview.html`, `church-songs-preview.html`, `class-live-preview.html`, `church-storage-preview.html`).
- Stream tests use a test church's key, never a real church's. Read `worklog/` (stream relay, recording copy,
  service clips) in both repos before more work here.

## 6. Edges

- **member-app:** `/my/live`, `/my/sermons` (Watch), group live on the phone — shared files
  `member_portal_live.py`, `member_portal_group_live.py`, `member_lumen_watch.py`.
- **church-office:** Academy classes own the course; this desk owns the live room and recordings.
  Sunday planning / Serve teams (`sunday_planning.py`, `worship_team` invites) sit on the seam.
- **websites:** a site's watch page and `sermons_public.py`.
- **messaging:** "Live now" pushes to members.
- **money:** ChurchSavvy billing (`churchsavvy_billing.py`), extra storage pricing.
- **system:** R2/Railway env, the scheduler (`recording_copy`, storage sweeps), separate services.
