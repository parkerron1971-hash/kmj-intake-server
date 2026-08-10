#!/usr/bin/env bash
# Create the Railway worker service and give it the same environment as
# the web service.
#
#   bash C:/Users/kmccl/kmj-intake-server/scripts/create_worker_service.sh
#
# Safe to re-run: creating a service that already exists fails
# harmlessly, and setting a variable to the value it already holds is a
# no-op.
#
# NO SECRET IS EVER PRINTED OR PASSED ON A COMMAND LINE. Each value goes
# straight from the JSON dump into `railway variable set --stdin` down a
# pipe, so nothing reaches the terminal, shell history, or a process
# listing. The dump itself is a temp file, deleted on exit including on
# failure.
#
# It does NOT touch the existing service. Switching that one to
# PROCESS_ROLE=web restarts the thing serving all production traffic,
# and is deliberately a separate decision.

set -uo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR" || exit 1

SRC="kmj-intake-server"      # the existing service — read only
DST="kmj-intake-worker"      # the one being created
GH_REPO="parkerron1971-hash/kmj-intake-server"

TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT
# Python here is the Windows build: it reads "/tmp/x" as C:\tmp\x, which
# is not where Git Bash put it. Every path handed to Python is converted.
winpath() { cygpath -w "$1" 2>/dev/null || echo "$1"; }

# ── 0/3  is this session allowed to WRITE? ───────────────────────────
#
# `railway whoami` answering with an email is not the same as being
# authorised. Reads keep working against an expired session while every
# mutation returns "Unauthorized. Please run `railway login` again."
#
# The first run of this script hit exactly that: `railway add` failed
# for that reason, and then 75 variable sets failed for the SAME reason
# — reported as 75 separate FAILs, with the cause invisible because
# their stderr was being discarded. One broken thing must not print as
# seventy-five.
echo "── 0/3  checking write access ───────────────────────────────"
probe="$(railway add --service "$DST" --repo "$GH_REPO" \
           --variables "PROCESS_ROLE=worker" 2>&1)"
add_rc=$?
echo "$probe"

if printf '%s' "$probe" | grep -qi "unauthor\|please run .railway login\|not logged in"; then
  cat <<'MSG'

  ──────────────────────────────────────────────────────────────
  STOPPED. This Railway session can read but not write.

  `railway whoami` still answers with your email — that is not
  the same as being authorised, and is why this looked fine
  until the first mutation.

  Fix it with:      railway login

  then run this script again. Nothing was created or changed.
  ──────────────────────────────────────────────────────────────
MSG
  exit 1
fi

if [ $add_rc -ne 0 ]; then
  if printf '%s' "$probe" | grep -qi "already exists\|name.*taken"; then
    echo "  service already exists — continuing to the variable copy"
  else
    echo
    echo "  'railway add' failed for a reason this script does not"
    echo "  recognise (above). Stopping rather than half-building a"
    echo "  service. Nothing was changed."
    exit 1
  fi
fi

echo
echo "── 2/3  copying environment from '$SRC' ─────────────────────"
railway variables --service "$SRC" --json > "$TMP" || {
  echo "  could not read variables from '$SRC' — stopping"; exit 1; }

TMPW="$(winpath "$TMP")"

# RAILWAY_* are injected per-service and describe the service they
# belong to; copying RAILWAY_SERVICE_ID or RAILWAY_PUBLIC_DOMAIN onto a
# different service produces one that thinks it is another one.
#
# PROCESS_ROLE is skipped for the obvious reason: the source says
# `worker` today and `web` tomorrow, and this service must not follow.
KEYS="$(python -c "
import json,sys
d=json.load(open(sys.argv[1],encoding='utf-8'))
print('\n'.join(sorted(k for k in d
      if not k.startswith('RAILWAY_') and k != 'PROCESS_ROLE')))
" "$TMPW")" || { echo "  could not parse the variable dump"; exit 1; }

total=$(printf '%s\n' "$KEYS" | grep -c .)
echo "  $total to copy (Railway-injected vars and PROCESS_ROLE skipped)"

i=0
failed=""
err=""
while IFS= read -r k; do
  [ -z "$k" ] && continue
  i=$((i+1))
  # The value goes down this pipe and nowhere else. stderr is CAPTURED,
  # not discarded — the first version threw it away, which turned one
  # auth failure into 75 mystery FAILs.
  out="$(python -c "
import json,sys
d=json.load(open(sys.argv[1],encoding='utf-8'))
v=d.get(sys.argv[2])
sys.stdout.write('' if v is None else str(v))
" "$TMPW" "$k" | railway variable set --service "$DST" --stdin --skip-deploys "$k" 2>&1)"
  if [ $? -eq 0 ]; then
    printf '  [%2d/%d] ok   %s\n' "$i" "$total" "$k"
  else
    printf '  [%2d/%d] FAIL %s\n' "$i" "$total" "$k"
    failed="$failed $k"
    err="$out"
    # STOP AT THE FIRST ONE. Every remaining key would fail the same
    # way, and a wall of identical failures buries the one line that
    # says why. It also means a half-populated service is never left
    # sitting there looking plausible.
    echo
    echo "  Reason given by Railway:"
    printf '%s\n' "$err" | sed 's/^/    /'
    break
  fi
done <<< "$KEYS"

if [ -n "$failed" ]; then
  echo
  echo "  Stopped at the first failure ($i of $total). Nothing deployed."
  echo "  A worker missing a credential starts, looks healthy, and fails"
  echo "  the jobs that need it — so a partial copy is not worth having."
  echo "  Fix the cause above and re-run; already-copied variables are"
  echo "  simply set again."
  exit 1
fi

echo
echo "── 3/3  deploying '$DST' ────────────────────────────────────"
# Everything above used --skip-deploys, so nothing has picked the
# variables up yet. This is the first build with a complete environment.
railway redeploy --service "$DST" --yes

echo
echo "─────────────────────────────────────────────────────────────"
echo "Done. Expect several minutes — nixpacks.toml installs Chromium"
echo "for the vision grader."
echo
echo "NOTHING HAS CHANGED FOR PRODUCTION YET. The existing service is"
echo "still running every job. Two schedulers is harmless: the lease"
echo "elects one leader."
echo
echo "Tell Claude when this finishes."
