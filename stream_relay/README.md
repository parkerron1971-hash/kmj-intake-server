# Stream relay

Our own server between a church's streaming software and YouTube/Facebook.
Kevin chose it on 2026-10-16 over Cloudflare Stream (priced per viewer) and
Railway (same platform as everything else; a Railway outage would take the
app and Sunday down together). Codex reviewed it the same day; the fixes are
in this version (findings R1–R11 in the review), and so are the two its
re-check found (R3-R, R6-R; fixed 2026-10-29).

```
Church's streaming software ── one encrypted stream (RTMPS) ──▶ stream.<domain>:443  (this droplet)
   key: <stream id>?key=<secret>                                  │  MediaMTX receives it on live/<stream id>
                                                                  │  relay_agent.py makes copies, unchanged:
                                                                  ├─▶ YouTube   (rtmps, the church's key)
                                                                  ├─▶ Facebook  (rtmps, the church's key)
                                                                  └─▶ PRIVATE R2 bucket: live/<church>/<session>/…
                                                                         │
   member app / church site ── /stream-relay/watch/<session> (backend) ─┘  signed links, hours long
```

Nothing is re-encoded (`-c copy`), so one $6 droplet carries a church, and a
$24 one about 25 churches streaming at once. Viewers never touch the droplet,
and nothing in the bucket is public: the backend's player page checks each
request (live → anyone; afterwards → only once a published sermon carries
it, or a manager's signed link) and hands out presigned links to the
segments that expire after a few hours.

The backend side is `stream_relay_router.py` (the church's key and
destinations, the player and its signed playlist, and the three routes the
agent calls with the shared secret).

## Files

| File | What |
|---|---|
| `mediamtx.yml` | MediaMTX 1.9.3: RTMPS on :443 only (no plain RTMP); API and RTSP on 127.0.0.1 only; every publish asks the agent |
| `agent/relay_agent.py` | Who may stream, the copies, the heartbeat, the R2 uploads, the journals, the limits, the end of a service |
| `agent/Dockerfile`, `agent/requirements.txt` | Python 3.12 + Debian ffmpeg, run as user 10001; aiohttp, boto3 |
| `docker-compose.yml` | Both containers, host networking, read-only, no capabilities (MediaMTX keeps only "bind :443"), memory and process caps |
| `setup/cloud-init.yaml` | Droplet first boot: Docker, certbot, firewall (22, 80, 443 only), key-only SSH, automatic security updates, the relay user |
| `setup/tls.sh`, `setup/install-cert.sh` | The Let's Encrypt certificate for `stream.<domain>`; renewals copy it in and MediaMTX reloads it without a restart |
| `setup/deploy.sh`, `setup/busy_check.py` | Copy this folder to the droplet and restart; refuses unless it can see nobody is streaming |

## The church's key

`POST /stream-relay/key` gives the church one string, shown once:
`<stream id>?key=<secret>`. The stream id (20 hex characters, derived from
the church) is the path MediaMTX uses and logs — not a secret. The secret is
the query, which MediaMTX passes to the agent's `/auth` and never logs; the
backend stores only its sha256. A new key keeps the same stream id, so the
church pastes only the key again, and the stream on the old key is cut at
the agent's next heartbeat (within a minute). The agent remembers one key
per church (its sha256, never the key) and re-confirms it with the backend
every hour (`POST /stream-relay/relay/confirm`, `GRANT_SYNC_S`), so an old
key it remembers is forgotten within the hour too.

## One-time setup

Steps marked **Kevin** need his account or card; the rest I can do.

1. **Kevin:** create the DigitalOcean account and add a card.
2. **Kevin:** add the SSH public key I hand over (Settings → Security → SSH keys).
3. **Kevin:** create the droplet. Ubuntu 24.04, Basic, Regular, $6 (1 GB). Region New York or Toronto. Choose that SSH key. Paste `setup/cloud-init.yaml` into **User data**. Then give it a **Reserved IP**, which is free while attached. The church's address points at that IP, so a replacement droplet can take it over without anyone changing anything.
4. **Kevin, in Cloudflare:**
   - **R2:** turn on R2 (free tier) and create a bucket, `solutionist-media`. Keep it **private**: leave the **r2.dev** address disabled and connect **no custom domain** (either one would make every recording public).
   - **CORS** (bucket → Settings → CORS policy), so members' browsers may fetch the signed segments from our player:
     ```json
     [{"AllowedOrigins": ["https://kmj-intake-server-production.up.railway.app"],
       "AllowedMethods": ["GET", "HEAD"], "AllowedHeaders": ["*"], "MaxAgeSeconds": 3600}]
     ```
   - **Two API tokens**, each limited to that bucket: *Object Read & Write* for the droplet, *Object Read* only for Railway.
   - **DNS:** an `A` record `stream` → the reserved IP, **DNS only** (grey cloud). RTMPS can't go through Cloudflare's proxy.
5. **The droplet's `.env`:** copy `.env.example` to `/opt/stream_relay/.env` and fill in `STREAM_HOST`, the shared secret and the read-write R2 token. Then `FIRST=1 setup/deploy.sh root@stream.<domain>` (it makes the certificate first; port 80 must reach the droplet).
6. **Railway:** `STREAM_RELAY_SECRET` (the same value), `STREAM_DEST_ENCRYPTION_KEY` (a new Fernet key), `STREAM_INGEST_URL=rtmps://stream.<domain>:443/live`, and `STREAM_R2_ENDPOINT`, `STREAM_R2_BUCKET`, `STREAM_R2_ACCESS_KEY_ID`, `STREAM_R2_SECRET_ACCESS_KEY` (the read-only token). Until all seven are set and sane, the church's Stream panel stays hidden and the relay's routes refuse every stream.
7. **Database (Kevin):** `supabase/APPLY-2026-10-16-stream-relay.sql` (applied) and `supabase/APPLY-2026-10-16-stream-relay-heartbeat.sql` (not yet).
8. **Check:** an anonymous request for any object in the bucket (r2.dev or otherwise) must fail; a test stream must play through `/stream-relay/watch/<session>` while live and stop playing for a signed-out viewer once it ends.

## A church sets it up once

In the church's settings, make the stream key, then paste the **server** (`rtmps://stream.<domain>:443/live`) and the whole **key** into the streaming software's custom settings. The software must support RTMPS: OBS, ProPresenter 7 and vMix do.
- **OBS:** Settings → Stream → Service: Custom.
- **ProPresenter:** Stream → Custom RTMP.

Then paste the YouTube and Facebook stream keys into the church's settings. Use YouTube's **persistent** key and Facebook's **persistent** stream key, so they never change week to week. A change there reaches a live stream within a minute.

Keep a second saved profile in the streaming software, "Straight to YouTube". If the relay ever fails, switching to it takes about 30 seconds.

## When something goes wrong on a Sunday

| What breaks | What happens | Who does anything |
|---|---|---|
| A copy (YouTube/Facebook) drops | The agent restarts that copy, waiting 1s, 2s, 4s… up to 30s | Nobody |
| The church's internet blinks | The church's software reconnects; the agent keeps the **same** recording for up to `GRACE_S` (10 min) | Nobody |
| The agent crashes or restarts | Docker restarts it in seconds. It reads its journals: a stream still coming in carries on in the same recording; one that doesn't come back is finished after the grace | Nobody |
| Railway (the backend) is down | Every key the agent remembers is re-confirmed hourly while Railway is up, so when it goes down each key still works for 24 hours (`OFFLINE_GRANT_S`) from its last re-check: an outage that starts Saturday night doesn't stop Sunday. A stream starts, carries on and reconnects after a blip, with copies to the remembered destinations. The recording uploads and the sermon draft is made once Railway is back; a finish retries until it is acknowledged. 24 hours after a key's last confirmation, a stream still on it is disconnected and its copies and recording stop, and a new stream on it is refused | Nobody, unless Railway is down a whole day: then the church uses "Straight to YouTube" |
| Railway is down for more than 45 minutes mid-service | The backend's sweep may close the session when it's back; the agent then carries on in a new recording (the service becomes two drafts) | Kevin merges the drafts if he wants one |
| The droplet dies | **Not automatic yet:** the church clicks "Straight to YouTube"; I move the reserved IP to a new droplet. The backend closes the lost session after 45 minutes | The church, then me |
| The disk fills, or a recording runs past 6 hours | New streams are refused while free disk is under 2 GB (or the disk can't be read); a recording stops (copies to YouTube/Facebook continue) past 6 hours, a 6 GB upload backlog, or 1 GB free. These checks run even while MediaMTX's API is down | Me, from the logs |
| More churches start at once than `MAX_STREAMS` (4) | Each church holds its place from the moment it is let in, one admission at a time, and a church waiting out its grace keeps its place; the one past the limit is refused, and any publisher found past it is disconnected | Me, if it happens: a bigger droplet |

## Operating it

```bash
ssh root@stream.<domain>
cd /opt/stream_relay
docker compose logs -f agent        # what the relay is doing (no stream keys are logged)
docker compose logs -f mediamtx     # paths only (live/<stream id>), never the secret
docker compose restart agent        # safe-ish (journals), but never during a service
curl -s 127.0.0.1:9100/health       # {"ok", "recovered", "live", "waiting", "finishing", "uptime_s"}
```

Deploy only outside service times; `deploy.sh` checks for you and refuses when it can't tell.

## Not built yet

- **A standby droplet and a watcher that moves the reserved IP**, so a dead droplet switches over on its own (layer 2 of the plan Kevin approved).
- **An uptime alert** to Kevin's phone, separate from DigitalOcean's free droplet monitoring.
- **Recording retention and deletion (Codex R9):** how long unpublished drafts' recordings stay in R2, and deleting a church's recordings when it deletes its account. Needs Kevin's call on retention; until then nothing in R2 expires, and `unreported/` folders on the droplet are kept for a person to look at.
- **Trimming a recording to the preaching**, and an MP4 for clips and downloads.
