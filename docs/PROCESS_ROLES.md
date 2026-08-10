# Process roles — splitting the worker off the web tier

## What this is for

Every replica used to run the full scheduler. That made two unrelated
things the same dial: how much traffic the app can absorb, and how many
copies of the nightly sweep run. Scale the web tier to three replicas
and you had three copies of twenty scheduled jobs firing at once, with a
leader lease as the only thing between that and duplicate sends.

`PROCESS_ROLE` separates them.

| value | serves HTTP | runs scheduled jobs |
| --- | --- | --- |
| *(unset)* | yes | **yes** |
| *(empty, or anything unrecognised)* | yes | **yes** |
| `all` | yes | yes |
| `web` | yes | **no** |
| `worker` | yes | yes |

Unset means `all` — today's behaviour exactly. That is deliberate: this
ships onto a running system where nothing has the variable set, and an
unset variable that changed anything would have stopped every scheduled
job at the moment of the deploy.

Unrecognised values also mean `all`. `PROCESS_ROLE=Worker ` with a
trailing space, or a plain misspelling, fails toward *running* the jobs.
Running them twice is what the lease is for. Running them never is an
outage nobody sees.

Case and surrounding whitespace are forgiven, so `Web` typed into a
dashboard field is understood as `web` rather than silently starting a
second scheduler.

## Configuring it on Railway

**Order matters.** Create the worker first, so there is never a window
with neither.

1. **New service** in the same Railway project, same repo, same start
   command. Copy the environment across — it needs the same Supabase and
   Anthropic credentials the web service has.
2. Set `PROCESS_ROLE=worker` on it. Leave it at **one replica**; more
   than one is harmless (the lease elects a single leader) but pointless.
3. Confirm it is up: its `/health/ready` reports `"role": "worker"` and
   `"scheduler_running": true`.
4. Only then set `PROCESS_ROLE=web` on the existing service. It will
   redeploy and stop running jobs.
5. Confirm the web service reports `"role": "web"`,
   `"scheduler_running": false`, `"ready": true`, and — the one that
   matters — `"scheduler_lease_fresh": true`.

To undo any of this, clear `PROCESS_ROLE` or set it to `all`. Every
service goes back to running everything.

## The failure this creates

Once a process can decline to run jobs, an operator can set **every**
service to `web`, never create the worker, and the scheduled work stops
— while every health check stays green. Each replica is genuinely
healthy and honestly reports that it runs no jobs. Nothing looking at a
single process can distinguish "somebody else does this" from "nobody
does this."

The shared lease is the only thing that can. Whichever process holds it
refreshes it every 30 seconds, so a lease older than a couple of TTLs
means no replica anywhere is running jobs.

`/health/ready` reports it as `scheduler_lease_fresh`, and the external
uptime monitor (`.github/workflows/uptime.yml`) pages when it is
**explicitly false**. The alert names `PROCESS_ROLE=worker`, because
"the lease is stale" means nothing to somebody woken at 3am.

### Why it can be null

`scheduler_lease_fresh` is `null`, never `false`, when the answer is
unknown — the lock disabled, the lease table absent, the read failed.
The monitor stays quiet on `null` on purpose. A monitor that pages on
"could not check" pages ten minutes after every fresh install, forever,
until somebody mutes it — and a muted monitor is the outage.

## Why a stale lease does not fail readiness

`/health/ready` answers "can **this** replica serve traffic". A web
replica serves it perfectly well while the worker is down. Folding the
lease into the verdict would have Railway pull healthy web replicas out
of rotation over a background-job problem, turning a partial outage into
a total one.

The lease is *reported* so something outside the system can act on it.
That separation is pinned by a test.

## A trap that was already caught

The original readiness line was:

```python
ready = supabase_ok and scheduler.running
```

Correct while every process ran the scheduler; a trap the moment one
could decline to. `PROCESS_ROLE=web` makes `scheduler.running` false by
design, so readiness would 503, Railway's healthcheck would fail, and
the entire web tier would never come up — the change meant to stop the
jobs running twenty times would have taken the front door down instead.

It now reads:

```python
scheduler_ok = scheduler.running or not runs_scheduled_jobs()
ready = supabase_ok and scheduler_ok
```

A web replica is ready without a scheduler. A worker whose scheduler
died is not, and still 503s. Supabase remains a hard dependency for
both.

Worth remembering as a class: the bug was in the line the change never
touched. Verifying the fields the split *added* passed a frame that was
broken at the other end.

## Notes

- Jobs are still **registered** on every replica; only `scheduler.start()`
  is gated. An APScheduler that was never started runs nothing, and the
  alternative — a second list of which jobs a web replica may register —
  is a list that drifts out of sync with the first one.
- A web replica logs, at boot, that it is running no jobs and that a
  worker must exist. Silence is how the bad configuration hides.
- Tests: `__tests__/test_process_role.py`.
