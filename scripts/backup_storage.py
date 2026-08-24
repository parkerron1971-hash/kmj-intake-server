#!/usr/bin/env python3
"""backup_storage.py — the half a Postgres backup does not contain.

Supabase's daily physical backups cover the DATABASE. They do not cover
Storage. Every object in every bucket -- practitioner documents,
proposals, product files, brand assets, site images -- lives outside
them, and until this script there was no copy of any of it anywhere.

`storage.objects` rows ARE in the database backup, which is the trap:
restore the database alone and you get a table full of working-looking
references to files that no longer exist. Both halves or neither.

WHAT IT DOES

Lists every bucket, walks every object (recursively -- Storage's list
endpoint returns one directory level at a time), downloads each one via
the service role, and writes a manifest recording what it saw and what
it got. The manifest is the thing verify_backup.py checks: a run that
silently downloaded nothing still produces a directory, and a directory
is not evidence.

CREDENTIALS

SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY. The service role reads private
buckets, which is the point -- business-documents and proposals are
private and are exactly the ones worth having.

Usage:
  SUPABASE_URL=... SUPABASE_SERVICE_ROLE_KEY=... \
      python scripts/backup_storage.py --out backup/storage
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

TIMEOUT = 120
PAGE = 100


def _req(url: str, key: str, method: str = "GET", body: bytes | None = None):
    req = urllib.request.Request(url, method=method, data=body)
    req.add_header("Authorization", f"Bearer {key}")
    req.add_header("apikey", key)
    if body is not None:
        req.add_header("Content-Type", "application/json")
    return urllib.request.urlopen(req, timeout=TIMEOUT)


def list_buckets(base: str, key: str) -> list[dict]:
    with _req(f"{base}/storage/v1/bucket", key) as r:
        return json.loads(r.read().decode("utf-8"))


def list_objects(base: str, key: str, bucket: str, prefix: str = "") -> list[dict]:
    """Every object under `prefix`, recursing into folders.

    Storage's list returns ONE level: entries with an `id` are objects,
    entries without are folders. A non-recursive version of this looked
    like it worked -- it just quietly skipped everything nested, which on
    this project is most of it (objects are stored under a per-business
    folder). Recursion is not an optimisation here, it is the difference
    between backing up 45 files and backing up 6.
    """
    found: list[dict] = []
    offset = 0
    while True:
        payload = json.dumps({
            "prefix": prefix,
            "limit": PAGE,
            "offset": offset,
            "sortBy": {"column": "name", "order": "asc"},
        }).encode("utf-8")
        with _req(f"{base}/storage/v1/object/list/{bucket}", key,
                  "POST", payload) as r:
            page = json.loads(r.read().decode("utf-8"))
        if not page:
            break
        for entry in page:
            name = entry.get("name")
            if not name:
                continue
            path = f"{prefix}{name}"
            if entry.get("id"):
                entry["_path"] = path
                found.append(entry)
            else:
                found.extend(list_objects(base, key, bucket, f"{path}/"))
        if len(page) < PAGE:
            break
        offset += PAGE
    return found


def download(base: str, key: str, bucket: str, path: str) -> bytes:
    quoted = urllib.parse.quote(path)
    with _req(f"{base}/storage/v1/object/{bucket}/{quoted}", key) as r:
        return r.read()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="backup/storage")
    args = ap.parse_args()

    base = (os.environ.get("SUPABASE_URL") or "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or ""
    if not base or not key:
        print("FATAL: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required",
              file=sys.stderr)
        return 2

    os.makedirs(args.out, exist_ok=True)
    manifest: dict = {"buckets": [], "objects": [], "errors": []}

    try:
        buckets = list_buckets(base, key)
    except urllib.error.HTTPError as e:
        print(f"FATAL: cannot list buckets: {e.code} {e.read()[:200]!r}",
              file=sys.stderr)
        return 2

    total = 0
    for b in buckets:
        name = b["name"]
        manifest["buckets"].append({"name": name, "public": b.get("public")})
        try:
            objects = list_objects(base, key, name)
        except urllib.error.HTTPError as e:
            manifest["errors"].append(f"list {name}: {e.code}")
            print(f"  ! {name}: list failed {e.code}", file=sys.stderr)
            continue

        print(f"  {name}: {len(objects)} object(s)")
        for o in objects:
            path = o["_path"]
            try:
                blob = download(base, key, name, path)
            except urllib.error.HTTPError as e:
                manifest["errors"].append(f"get {name}/{path}: {e.code}")
                print(f"  ! {name}/{path}: {e.code}", file=sys.stderr)
                continue
            dest = os.path.join(args.out, name, path.replace("/", os.sep))
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with open(dest, "wb") as fh:
                fh.write(blob)
            manifest["objects"].append({
                "bucket": name,
                "path": path,
                "bytes": len(blob),
                "sha256": hashlib.sha256(blob).hexdigest(),
            })
            total += len(blob)

    manifest["total_objects"] = len(manifest["objects"])
    manifest["total_bytes"] = total
    with open(os.path.join(args.out, "manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=1)

    print(f"\n{manifest['total_objects']} object(s), {total} bytes, "
          f"{len(manifest['errors'])} error(s)")

    # A partial backup that exits 0 is how you find out at restore time.
    if manifest["errors"]:
        print("FAILED: some objects could not be backed up", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
