#!/usr/bin/env bash
# Make the `product-files` bucket private, and prove it.
#
#   bash C:/Users/kmccl/kmj-intake-server/scripts/close_product_files_bucket.sh
#
# WHAT IS WRONG. store_files.py's own docstring says "private Supabase
# bucket product-files", and mints a 300-second signed URL for every
# download. The bucket is public=true. A public Supabase bucket serves
# /object/public/<path> to anyone, with no key, no expiry and no RLS —
# so the signing, the expiry, the rate limit and the purchase gate in
# front of it are all decorative.
#
# OBSERVED, not assumed: an anonymous GET of an uploaded object returned
# 200 with the file body, using no credentials at all.
#
# NOT CURRENTLY EXPLOITED: the bucket is empty. This is a loaded gun,
# and it fires the first time a practitioner sells a digital product.
#
# Also removes the probe object left behind by that test, which the
# session that found this could not delete.
#
# Safe to re-run. Nothing here touches any other bucket.

set -uo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)" || exit 1

BUCKET="product-files"

T="$(mktemp)"; trap 'rm -f "$T"' EXIT
railway variables --service kmj-intake-server --json > "$T" || {
  echo "could not read Railway variables — is the CLI logged in?"; exit 1; }

# Values move from the JSON into the environment without passing through
# a command line or the terminal.
eval "$(python -c "
import json,sys,shlex
d=json.load(open(sys.argv[1],encoding='utf-8'))
for k in ('SUPABASE_URL','SUPABASE_SERVICE_ROLE_KEY'):
    print(f'export {k}={shlex.quote(str(d.get(k) or \"\"))}')
" "$(cygpath -w "$T" 2>/dev/null || echo "$T")")"

[ -n "${SUPABASE_URL:-}" ] || { echo "SUPABASE_URL missing"; exit 1; }
SVC=(-H "apikey: $SUPABASE_SERVICE_ROLE_KEY"
     -H "Authorization: Bearer $SUPABASE_SERVICE_ROLE_KEY")

probe="_verify/$$.txt"

echo "── 1/5  clearing probe objects left by the audit ────────────"
for p in $(curl -s -X POST "$SUPABASE_URL/storage/v1/object/list/$BUCKET" "${SVC[@]}" \
             -H "Content-Type: application/json" \
             -d '{"prefix":"_claude_probe","limit":100}' \
           | python -c "
import sys,json
try: rows=json.load(sys.stdin)
except Exception: rows=[]
for r in rows:
    n=r.get('name')
    if n: print('_claude_probe/'+n)
"); do
  curl -s -o /dev/null -w "  removed $p (%{http_code})\n" \
    -X DELETE "$SUPABASE_URL/storage/v1/object/$BUCKET/$p" "${SVC[@]}"
done

echo
echo "── 2/5  proving the hole is real, before closing it ─────────"
curl -s -o /dev/null -w "  upload probe        -> %{http_code}\n" \
  -X POST "$SUPABASE_URL/storage/v1/object/$BUCKET/$probe" "${SVC[@]}" \
  -H "Content-Type: text/plain" --data "verify"
before=$(curl -s -o /dev/null -w '%{http_code}' \
  "$SUPABASE_URL/storage/v1/object/public/$BUCKET/$probe")
echo "  anonymous GET       -> $before   (200 here means wide open)"

echo
echo "── 3/5  setting public=false ────────────────────────────────"
curl -s -X PUT "$SUPABASE_URL/storage/v1/bucket/$BUCKET" "${SVC[@]}" \
  -H "Content-Type: application/json" -d '{"public":false}' | head -c 200
echo

echo
echo "── 4/5  proving it is closed, same request ──────────────────"
after=$(curl -s -o /dev/null -w '%{http_code}' \
  "$SUPABASE_URL/storage/v1/object/public/$BUCKET/$probe")
echo "  anonymous GET       -> $after   (400/404 is the fix)"

# And the way the app ACTUALLY serves a purchased file must still work.
# Closing the bucket is only correct if it does not break paid delivery.
signed=$(curl -s -X POST "$SUPABASE_URL/storage/v1/object/sign/$BUCKET/$probe" \
  "${SVC[@]}" -H "Content-Type: application/json" -d '{"expiresIn":300}' \
  | python -c "
import sys,json
try: print(json.load(sys.stdin).get('signedURL') or '')
except Exception: print('')
")
if [ -n "$signed" ]; then
  code=$(curl -s -o /dev/null -w '%{http_code}' "$SUPABASE_URL/storage/v1$signed")
  echo "  signed URL          -> $code   (200 = paid delivery still works)"
else
  echo "  signed URL          -> COULD NOT SIGN — do not stop here"
fi

echo
echo "── 5/5  removing the verification probe ─────────────────────"
curl -s -o /dev/null -w "  deleted (%{http_code})\n" \
  -X DELETE "$SUPABASE_URL/storage/v1/object/$BUCKET/$probe" "${SVC[@]}"

echo
echo "─────────────────────────────────────────────────────────────"
if [ "$before" = "200" ] && [ "$after" != "200" ]; then
  echo "CLOSED. Anonymous access went $before -> $after on the same object."
elif [ "$before" != "200" ]; then
  echo "Already closed before this ran (anonymous GET was $before)."
else
  echo "STILL OPEN — anonymous GET is $after. Do not assume this worked."
fi
