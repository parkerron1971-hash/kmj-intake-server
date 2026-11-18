# Clip service (Video Clips → Find my best clips)

A separate Railway service that turns one long recording (a sermon, a talk, a
webinar) into short vertical clips with captions. It runs apart from the API
for the same reason `video_worker/` does: deploying the API restarts it, and a
restart in the middle of a 10-minute job would throw the work away.

It holds one secret besides its own token: an **OpenRouter key**, used only by
the clipping engine. It has no database or storage credentials. The API hands
it a short-lived signed link to the recording and collects the finished clips
afterwards.

## What it does with a job

1. Downloads the recording from the signed link (https, approved host only, no
   redirects, 5 GB and 2 hours at most).
2. Runs the pinned BridgeClip engine: transcribe (MAI Transcribe 2), choose
   complete moments (Claude Opus 5.5), frame each one vertically following the
   speaker, burn in captions, run Jev's editorial check.
3. Checks every finished clip for stretches of 2+ seconds with nobody on screen
   (`empty_spots.py`) and picks a poster frame where the speaker is visible.
   At that same moment it takes a clean frame from the recording itself (no
   captions, no title card, up to 1920 wide): what a cover is designed from.
   It also saves a head-and-shoulders close-up of the speaker, so a cover can
   keep the face and hair: of 14 moments spread across the clip plus five
   within 1.5 s of the poster, the face that best faces the camera, is sharp,
   big and surely a face (`face_score`; strong profiles and tiny faces are never
   used; a two-person shot looks only around the poster). The recording is
   deleted once the frames are taken.
4. Keeps the clips, posters and a result manifest until the API deletes the job
   or `CLIPPER_RESULT_TTL` passes.

One job at a time. A second `POST` while busy gets `409`; the API queues.

## A service recording's smaller copy (`POST /copies/{uuid}`)

The API's `recording_copy.py` (switch `CHURCH_STORAGE_SMALL_COPY`) also has
this service make one smaller MP4 of each church service recorded through the
stream relay: about 720p (aspect kept, never upscaled), H.264 ~1.5 Mbps,
AAC 96 kbps, `+faststart`, about 0.7 GB an hour. The API sends the recording's
HLS playlist with every segment a signed link, and a signed `PUT` link for the
finished file; this service still holds no storage key.

1. Checks the playlist: every segment and the upload link are https on
   `CLIPPER_COPY_HOSTS` (the media bucket's host alone; clip jobs keep reading
   `CLIPPER_SOURCE_HOSTS`), no tag points anywhere else, and it is read as a
   finished video (`#EXT-X-ENDLIST` added when missing).
2. ffmpeg reads the segments over https (`-seg_max_retry 3`) and encodes. A
   segment it couldn't read fails the job, never a copy with a hole in it. No
   progress for 10 minutes, or `CLIPPER_COPY_SECONDS`, stops it.
3. Probes the result (`seconds`, `width`, `height`, `audio`), uploads it in
   one `PUT` with its length declared, checks the bucket's ETag against the
   file's MD5, and deletes it here. The API reads the size back and checks the
   length before it relies on the copy.

**Clip jobs go first.** A `POST /jobs/{uuid}` that arrives while a copy is
being made stops the copy (status `cancelled`, code `job.yielded`) and takes
the service within `YIELD_WAIT_SECONDS`; the API makes that copy again later
without counting it as a failed try. A copy never stops a clip job: `POST
/copies` while anything runs is a `409`.

Measured with this command on a 22-core desktop limited to 8 threads
(2026-11-17, a 1080p30 7 Mbps test recording with a resume in the middle):
`veryfast` encoded at about 6x real time and wrote 1.63 Mbps (1.4 GB for two
hours). Railway's 8 vCPU should be roughly half that: 20 to 40 minutes for a
two-hour service.

## API (all but `/health` need `Authorization: Bearer $CLIPPER_TOKEN`)

| Call | What it does |
| --- | --- |
| `GET /health` | `{ok, engine, busy, ready}`. `ready` is false until both secrets are set. |
| `POST /jobs/{uuid}` | `{source_url, options}` → `202`. Options: `durations` (`xshort` `short` `medium` `long`), `caption_preset`, `aspect_ratio` (`9:16` or `16:9`), `clip_request`, `keyterms`, `max_clips`. |
| `GET /jobs/{uuid}` | `{status, stage, percent, clips_done, clips_total, error, result}`. `status` is `working`, `completed`, `failed` or `cancelled`. `stage` is `downloading`, `listening`, `choosing`, `framing`, `checking` or `done`. |
| `GET /jobs/{uuid}/files/{clip_NN.mp4, clip_NN.jpg, clip_NN_frame.jpg or clip_NN_face.jpg}` | One finished clip, poster, clean frame or face close-up. |
| `POST /faces` `{source_url, start, end, count?}` | A face close-up (JPEG) from that stretch of a video, read with one ffmpeg pass over range requests; with `count` 2-3, JSON with that many, best first. 404 when no usable face, 502 when the video cannot be read. |
| `POST /likeness` `{image_b64, references_b64[1-4]}` | How much the face on a design looks like the person in the photos: SFace cosine, best over the photos (`score`, `scores`, `face_found`). |
| `DELETE /jobs/{uuid}` | Stops a running job, or forgets a finished one and deletes its files. |
| `POST /copies/{uuid}` | `{playlist, upload_url, seconds}` → `202`. A recording's smaller copy (above). `422` for a link off `CLIPPER_COPY_HOSTS`, `409` while busy. |
| `GET /copies/{uuid}` | `{status, stage, percent, error, result}`. `stage` is `making`, `checking`, `uploading` or `done`; `result` is `{seconds, bytes, width, height, audio, md5, timings}`. |
| `DELETE /copies/{uuid}` | Stops a copy being made, or forgets a finished one. |

`GET /health` also says `copies` (`CLIPPER_COPY_HOSTS` is set) and `job`
(`clips` or `copy` while busy).

`result.clips[]` carries `index`, `title`, `start_ms`, `end_ms`, `duration_ms`,
`score`, `tags`, `layout`, `review_flags`, `video`, `poster`, `frame`, `face`, `bytes`,
`empty_spots` (`[{from, to, seconds}]`) and `face_coverage`. `result.cost` is the
engine's own provider-reported cost breakdown; OpenRouter's bill is the authority.

## Environment

| Variable | Required | Notes |
| --- | --- | --- |
| `CLIPPER_TOKEN` | yes | 32+ characters. The API sends it as a bearer token. |
| `OPENROUTER_API_KEY` | yes | Used only by the engine process. Never logged. |
| `CLIPPER_SOURCE_HOSTS` | yes | Comma-separated hostnames signed links may come from (the Supabase project host). Empty means every job is refused. |
| `CLIPPER_MAX_SOURCE_BYTES` | no | Default 5 GB. |
| `CLIPPER_MAX_SOURCE_SECONDS` | no | Default 7200 (2 hours). |
| `CLIPPER_JOB_SECONDS` | no | Default 3600. A job running longer is stopped. |
| `CLIPPER_RESULT_TTL` | no | Default 7200. Finished jobs are forgotten after this. |
| `CLIPPER_COPY_HOSTS` | for copies | The media bucket's hostname (`<account>.r2.cloudflarestorage.com`, the host of the API's `STREAM_R2_ENDPOINT`). Empty means every copy is refused and `/health` says `copies: false`. |
| `CLIPPER_COPY_SECONDS` | no | Default 10800. A copy taking longer is stopped. |
| `CLIPPER_COPY_MAX_SECONDS` | no | Default 21600 (6 hours): the longest recording copied (one upload stays under 5 GB). |

On Railway: the `solutionist-clipper` service, connected to this repo's `main`
with **Root Directory `/clipper_worker`**. The Dockerfile builds from this
folder, so the backend's `railway.toml` and `nixpacks.toml` at the repo root are
never read; connected without a root directory, the service picked them up and
started building the API (2026-10-06). **Watch Paths `/clipper_worker/**`**, so a
merge that only touches the API never restarts a running job, and a `/health`
healthcheck, so a broken build never replaces a working one. Config as Code is
deprecated and ignored for this service: `railway.toml` here records the
dashboard settings. Give it room: 8 vCPU / 8 GB is plenty for one job.

A merge to `main` that touches this folder deploys it. By hand, only if
needed: check `/health` says `busy: false`, stage the folder keeping its name
(`git archive origin/main clipper_worker | tar -x -C C:/Users/kmccl/clipper-deploy`;
the root directory applies to CLI uploads too), then
`railway up C:/Users/kmccl/clipper-deploy --path-as-root --ci -s solutionist-clipper -e production`.

## The vendored engine (`vendor/bridgeclip/`)

[BridgeClip](https://github.com/bridge-mind/bridgeclip) by BridgeMind, MIT
license (`vendor/bridgeclip/LICENSE`; bundled fonts are OFL and the YuNet face
model is MIT, see `vendor/bridgeclip/engine/THIRD_PARTY_NOTICES.md`).

- **Commit:** `b996820ef80fa324a3ad233bef1aac5cc6936804` (2026-10-01, v0.1.19).
- **Files:** `engine/clip_engine`, `engine/assets`, `engine/requirements.lock`,
  `bridge/bridge_runner.py`, `bridge/network_guard.py`, and the license files,
  exported with `git archive` from that commit. The desktop app (Electron) and
  the engine's own tests are not copied.
- **Local changes:** none. Keep it that way; put anything Solutionist-specific
  in `service.py` or `empty_spots.py` so an upgrade is a clean re-export.
- **We call it the way the desktop app does:** `bridge_runner.py` with the
  version 3 JSON job contract on stdin and JSON-line progress on stdout, in
  `LOCAL_MODE`.

To upgrade: export the new commit's same paths over `vendor/bridgeclip/`, update
`ENGINE_COMMIT` in `service.py` and the commit above, run the upstream engine
suite on that commit (`python -m pytest -q engine/tests` in a BridgeClip clone),
then rehearse one real recording before deploying.

## Measured on a real sermon (2026-10-05, a 22-core desktop)

A 62.7-minute 720p sermon produced 16 clips (19 s to 2:27) in 5 minutes:
transcription 72 s, choosing 31 s, editorial review 5 s, rendering 187 s.
Provider-reported AI cost $0.367 (transcription $0.105, Opus $0.229, framing
vision $0.027, Jev $0.006). The empty-spot check flagged 5 of the 16 clips;
every flagged spot was a real empty stage. Expect Railway to be slower; one
minute of finished 1080×1920 clip took about 78 s of CPU to encode.
