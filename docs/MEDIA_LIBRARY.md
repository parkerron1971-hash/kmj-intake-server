# Selected recordings and reviewed clips

`/media-library/{business_id}` requires an active manager or owner. Source
recordings, job credentials and finished clips are service-mediated; the browser
cannot access the media table or private storage directly. Signed playback and
download links expire after 15 minutes. Account erasure includes the bucket;
account JSON exports include metadata and reviews but exclude credentials. File
bytes are available through the authorized media interface, separately from JSON.

Google Picker requests only `drive.file`, with accumulated scopes disabled.
The server verifies the token audience, exact scope, current file metadata and
download permission. An import makes an authorized private copy, not a continuing
mirror of Drive permissions. The short-lived grant is encrypted using a dedicated
Fernet key, or a domain-separated key derived from the runtime TIN encryption key.
It is erased when the job finishes or expires. No refresh token is retained.

Runtime prerequisites: `GOOGLE_CLIENT_ID`, a browser/referrer-restricted
`GOOGLE_PICKER_API_KEY` for the same Google Cloud project, and its
`GOOGLE_CLOUD_PROJECT_NUMBER`. Enable Drive API and Picker API and authorize the
production JavaScript origin on the OAuth client. Google console configuration
and the customer's consent must be completed before describing Drive as connected.

Install FFmpeg and FFprobe in the runtime image (`RAILPACK_DEPLOY_APT_PACKAGES`
includes `ffmpeg`) and set `MEDIA_PROCESSING=on` on server and worker. Work runs
through the existing leader-gated scheduler, at most one processor globally and
one pending job per business. Interrupted jobs fail visibly and require a new
selection or clip. There are no silent retries or automatic provider sends.

Limits: MP4/MOV/WebM, 1 GB per recording, two hours, 4K input, 20 GB per business;
clips are 5–90 seconds and render to 720x1280 H.264/AAC with padding to preserve
framing. Browser playback depends on source codec support. Download, render and
upload phases have bounded time and size limits; subprocesses cannot fetch
network protocols. No recording enters an AI model or business-learning memory.

The operator selects timestamps and writes a post caption. Caption text is a
separate handoff file; this release does not transcribe, burn subtitles into the
video, select highlights automatically, or publish/schedule Reels. Review covers
the exact clip bytes, caption and destination. Editing requires a new clip and
review. A reviewed download does not itself deliver content to a third party.

Validation: Python authorization, bounds, credential exclusion, approval hashing,
interruption cleanup and real FFmpeg tests; desktop/mobile synthetic UI checks;
rollback SQL checks for job concurrency, immutable content and storage grants.
