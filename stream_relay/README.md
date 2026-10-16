# Stream relay

Our own server between a church's streaming software and YouTube/Facebook.
Kevin chose it on 2026-10-16 over Cloudflare Stream (priced per viewer) and
Railway (same platform as everything else; a Railway outage would take the
app and Sunday down together).

```
Church's streaming software ── one stream ──▶  stream.<domain>:1935  (this droplet)
                                                 │  MediaMTX receives it
                                                 │  relay_agent.py makes copies, unchanged:
                                                 ├─▶ YouTube   (rtmps, the church's key)
                                                 ├─▶ Facebook  (rtmps, the church's key)
                                                 └─▶ R2: live/<church>/<session>/index.m3u8 + segments
                                                        ├─ members watch live in the app (player.html)
                                                        └─ when it ends: a sermon draft with the recording
```

Nothing is re-encoded (`-c copy`), so one $6 droplet carries a church, and a
$24 one about 25 churches streaming at once. Viewers never touch the droplet:
they watch from R2 through Cloudflare, which costs nothing per viewer.

The backend side is `stream_relay_router.py` (the church's key and
destinations, and the three routes the agent calls with the shared secret).

## Files

| File | What |
|---|---|
| `mediamtx.yml` | MediaMTX 1.9.3: RTMP on :1935 public; API and RTSP on 127.0.0.1 only; every publish asks the agent |
| `agent/relay_agent.py` | Who may stream, the copies, the R2 uploads, the end of a service |
| `agent/Dockerfile`, `agent/requirements.txt` | Python 3.12 + Debian ffmpeg; aiohttp, boto3 |
| `player.html` | The player members see (hls.js 1.5.17 with SRI). The agent uploads it to the bucket root on start |
| `docker-compose.yml` | Both containers, host networking, restart on their own |
| `setup/cloud-init.yaml` | Droplet first boot: Docker, firewall (22 + 1935 only), automatic security updates |
| `setup/deploy.sh` | Copy this folder to the droplet and restart; refuses while a church is live |

## One-time setup

Steps marked **Kevin** need his account or card; the rest I can do.

1. **Kevin:** create the DigitalOcean account and add a card.
2. **Kevin:** add the SSH public key I hand over (Settings → Security → SSH keys).
3. **Kevin:** create the droplet. Ubuntu 24.04, Basic, Regular, $6 (1 GB). Region New York or Toronto. Choose that SSH key. Paste `setup/cloud-init.yaml` into **User data**. Then give it a **Reserved IP**, which is free while attached. The church's address points at that IP, so a replacement droplet can take it over without anyone changing anything.
4. **Kevin, in Cloudflare:**
   - **R2:** turn on R2 (free tier) and create a bucket, `solutionist-media`.
   - **Custom domain:** connect `media.<domain>` to the bucket (Settings → Custom Domains).
   - **API token:** create an R2 token with *Object Read & Write* on that bucket only.
   - **DNS:** add an `A` record `stream` → the reserved IP, **DNS only** (grey cloud). RTMP can't go through Cloudflare's proxy.
5. **The droplet's `.env`:** copy `.env.example` to `/opt/stream_relay/.env` and fill in the R2 values, the bucket and the shared secret. Then run `setup/deploy.sh root@stream.<domain>`.
6. **Railway:** set `STREAM_RELAY_SECRET` (the same value), `STREAM_DEST_ENCRYPTION_KEY` (a new Fernet key), `STREAM_INGEST_URL=rtmp://stream.<domain>/live` and `MEDIA_PUBLIC_BASE=https://media.<domain>`.
7. **Database:** apply `supabase/APPLY-2026-10-16-stream-relay.sql`.

## A church sets it up once

In the church's settings, make the stream key, then paste the **server** and **key** into the streaming software's custom RTMP settings.
- **OBS:** Settings → Stream → Service: Custom.
- **ProPresenter:** Stream → Custom RTMP.

Then paste the YouTube and Facebook stream keys into the church's settings. Use YouTube's **persistent** key and Facebook's **persistent** stream key, so they never change week to week.

Keep a second saved profile in the streaming software, "Straight to YouTube". If the relay ever fails, switching to it takes about 30 seconds.

## When something goes wrong on a Sunday

| What breaks | What happens | Who does anything |
|---|---|---|
| A copy (YouTube/Facebook) drops | The agent restarts that copy, waiting 1s, 2s, 4s… up to 30s | Nobody |
| The church's internet blinks | The church's software reconnects; the agent keeps the **same** recording for up to `GRACE_S` (10 min) | Nobody |
| The agent or MediaMTX crashes | Docker restarts it in seconds. A restarted agent picks up the live stream and resumes the same recording | Nobody |
| Railway (the backend) is down | Keys that streamed here in the last 30 days still work, and copies go to the remembered destinations. The recording uploads and the sermon draft is made once Railway is back | Nobody |
| The droplet dies | **Not automatic yet:** the church clicks "Straight to YouTube"; I move the reserved IP to a new droplet | The church, then me |

## Operating it

```bash
ssh root@stream.<domain>
cd /opt/stream_relay
docker compose logs -f agent        # what the relay is doing (no stream keys are logged)
docker compose restart agent        # never during a service
curl -s 127.0.0.1:9100/health       # {"ok": true, "live": <streams right now>}
```

Deploy only outside service times; `deploy.sh` checks for you.

## Not built yet

- **A standby droplet and a watcher that moves the reserved IP**, so a dead droplet switches over on its own (layer 2 of the plan Kevin approved).
- **An uptime alert** to Kevin's phone, separate from DigitalOcean's free droplet monitoring.
- **Encrypted ingest (RTMPS on 443)** for streaming software that supports it.
- **Trimming a recording to the preaching**, and an MP4 for clips and downloads.
