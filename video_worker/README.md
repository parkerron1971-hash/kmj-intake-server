# Video Studio renderer

The existing application scheduler worker runs the durable job supervisor, Chief calls and narration. The API handles user requests, tenant checks and private storage. The separate Railway renderer receives a frozen composition bundle and returns MP4 bytes. It has **no Supabase, Anthropic or OpenAI credentials**. Its only secret is `VIDEO_RENDER_TOKEN`, generated separately from provider credentials. The child Node/Chrome process does not inherit that token.

The supervisor polls every eight seconds. Database claims serialize jobs across API replicas, renew a two-minute lease, fence stale completion, and retry an interrupted render at most once. Planning interruptions fail visibly instead of repeating paid model calls. Cancelling terminates the renderer subprocess. All outputs are checked for duration and FFmpeg decoding before private storage.

## Deploy

Create a dedicated service. Assemble a temporary deployment directory containing `video_cloud_renderer.py`, `.dockerignore`, `video_worker/{Dockerfile,railway.toml,requirements.txt,package.json,package-lock.json}`. Also copy `video_worker/railway.toml` and `video_worker/Dockerfile` to that directory's root as `railway.toml` and `Dockerfile`. Set the renderer service variable `RAILWAY_DOCKERFILE_PATH=Dockerfile`. Upload that directory with `railway up --path-as-root --service solutionist-video-renderer`. Do not change the API service's build configuration.

Set a new random `VIDEO_RENDER_TOKEN` on the existing API, existing scheduler worker, and isolated renderer without printing it. Set `VIDEO_RENDER_URL` on the API and existing scheduler worker to the renderer HTTPS origin. Apply `supabase/APPLY-2026-09-07-video-studio.sql` once. After worker verification set `VIDEO_STUDIO_ENABLED=on` and `VIDEO_RENDER_ENABLED=on` on both the API and existing scheduler worker. The web-role API does not start scheduled jobs; enabling only the API leaves jobs queued. The renderer health route is `/health`; all job routes require the rendering-only token. Roll back availability by switching the two API flags off; existing project data remains intact.

## Scope and limits

Editable title, split, image, quote, feature, statistic and closing scenes; three themes; three aspect ratios; pictures, trimmed video, uploaded music, optional TTS narration and timed phrase captions. Up to three minutes, twelve 100 MB files (300 MB/project), thirty minutes rendered per tenant/day, twenty job requests/hour. Source video audio is muted. No invented testimonials or statistics, generated stock footage, automatic highlights, full-recording transcript, arbitrary model code, social publishing or word-synchronized captions.

Render compute is included during early access, with limits enforced in SQL. Chief planning uses existing AI metering; narration is cost-logged. Interrupted renders can repeat narration generation once. Operating costs are Railway compute, storage and provider usage; this integration does not use a paid hosted HyperFrames subscription.

The compiler vendors pinned GSAP 3.15.0 (license notice retained in the JS header) and Inter 5.2.8 (OFL included). Node 22 and HyperFrames 0.8.31 are pinned in the renderer. Frame-file encoding is used because streaming encoding failed Windows verification.
