#!/usr/bin/env bash
# Delete the orphaned `ets_event_files` storage bucket.
#
#   bash C:/Users/kmccl/kmj-intake-server/scripts/delete_orphan_ets_bucket.sh
#
# THE SITUATION. Two buckets exist whose names differ only by an
# underscore vs a hyphen:
#
#   ets_event_files   created 2026-04-10 16:03, 0 objects, never touched
#   ets-event-files   created 2026-04-10 16:53, 4 folders of real content
#
# Somebody renamed within the hour and left the first behind.
#
# THE TRAP THAT NEARLY GOT THE WRONG ONE DELETED. Grepping the ETS app
# for "ets_event_files" returns hits in three page components — which
# looks like proof the underscore bucket is the live one. It is not.
# `ets_event_files` is also a DATABASE TABLE, and every one of those
# hits is a PostgREST embedded select (`.select("*, ets_event_files(*)")`)
# joining that table. The app never calls storage at all: it reads
# file_url out of the table and renders it.
#
# So the deciding evidence is the URLs themselves, and every one points
# at the HYPHENATED bucket.
#
# This script re-establishes all of that at run time rather than
# trusting the paragraph above, and refuses if anything disagrees.

set -uo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)" || exit 1

ORPHAN="ets_event_files"      # underscore — the one being deleted
LIVE="ets-event-files"        # hyphen — the one holding the data

T="$(mktemp)"; trap 'rm -f "$T"' EXIT
railway variables --service kmj-intake-server --json > "$T" || {
  echo "could not read Railway variables — is the CLI logged in?"; exit 1; }
eval "$(python -c "
import json,sys,shlex
d=json.load(open(sys.argv[1],encoding='utf-8'))
for k in ('SUPABASE_URL','SUPABASE_SERVICE_ROLE_KEY'):
    print(f'export {k}={shlex.quote(str(d.get(k) or \"\"))}')
" "$(cygpath -w "$T" 2>/dev/null || echo "$T")")"

[ -n "${SUPABASE_URL:-}" ] || { echo "SUPABASE_URL missing"; exit 1; }
SVC=(-H "apikey: $SUPABASE_SERVICE_ROLE_KEY"
     -H "Authorization: Bearer $SUPABASE_SERVICE_ROLE_KEY")

count_objects() {
  curl -s -X POST "$SUPABASE_URL/storage/v1/object/list/$1" "${SVC[@]}" \
    -H "Content-Type: application/json" -d '{"prefix":"","limit":1000}' \
  | python -c "
import sys,json
try: print(len(json.load(sys.stdin)))
except Exception: print(-1)
"
}

echo "── check 1: is '$ORPHAN' empty? ─────────────────────────────"
n_orphan="$(count_objects "$ORPHAN")"
echo "  objects: $n_orphan"
if [ "$n_orphan" = "-1" ]; then
  echo "  could not read the bucket. Refusing — an unreadable bucket is"
  echo "  not an empty one."; exit 1
fi
if [ "$n_orphan" != "0" ]; then
  echo "  NOT EMPTY. Refusing. Something started using it since the audit,"
  echo "  and deleting it would destroy those files."; exit 1
fi

echo
echo "── check 2: does anything still POINT at it? ────────────────"
# The table holds the URLs the public site actually renders. If any of
# them names the orphan, it is not an orphan.
refs="$(curl -s "$SUPABASE_URL/rest/v1/ets_event_files?select=file_url&limit=1000" "${SVC[@]}" \
  | python -c "
import sys,json,re
try: rows=json.load(sys.stdin)
except Exception: print('ERR'); raise SystemExit
if isinstance(rows,dict): print('ERR'); raise SystemExit
import collections
c=collections.Counter()
for r in rows:
    m=re.search(r'/object/(?:public/)?([^/]+)/', r.get('file_url') or '')
    if m: c[m.group(1)]+=1
print(json.dumps(c))
")"
if [ "$refs" = "ERR" ]; then
  echo "  could not read ets_event_files. Refusing rather than guessing."; exit 1
fi
echo "  buckets referenced by live file_urls: $refs"
if printf '%s' "$refs" | grep -q "\"$ORPHAN\""; then
  echo "  A LIVE URL POINTS AT '$ORPHAN'. Refusing — it is in use."; exit 1
fi

echo
echo "── check 3: is the live bucket the one with the data? ───────"
n_live="$(count_objects "$LIVE")"
echo "  '$LIVE' objects: $n_live"
if [ "$n_live" = "0" ] || [ "$n_live" = "-1" ]; then
  echo "  The bucket believed to be live is empty or unreadable. That"
  echo "  contradicts the premise, so stop and look before deleting"
  echo "  anything."; exit 1
fi

echo
echo "── deleting '$ORPHAN' ──────────────────────────────────────"
curl -s -X DELETE "$SUPABASE_URL/storage/v1/bucket/$ORPHAN" "${SVC[@]}" | head -c 200
echo

echo
echo "── result ───────────────────────────────────────────────────"
curl -s "$SUPABASE_URL/storage/v1/bucket" "${SVC[@]}" | python -c "
import sys,json
rows=json.load(sys.stdin)
for x in rows:
    print(f\"  {'PUBLIC ' if x.get('public') else 'private'}  {x.get('name')}\")
names=[x.get('name') for x in rows]
print()
print('  ets_event_files gone:', 'ets_event_files' not in names)
print('  ets-event-files kept:', 'ets-event-files' in names)
"
