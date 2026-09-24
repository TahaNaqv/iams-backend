#!/usr/bin/env bash
#
# IAMS restore — the *other half* of backup.sh. Run this for the
# quarterly restore drill. The point is to verify the backup is
# usable; don't trust untested backups.
#
# Usage:
#   AGE_IDENTITY_FILE=~/iams-backup-key.txt \
#   RESTIC_REPOSITORY=/mnt/nas/iams \
#   RESTIC_PASSWORD=... \
#   ./deploy/restore.sh <snapshot-id|latest> <target-db-url>
#
# The script:
#   1. ``restic restore`` the chosen snapshot to a temp dir.
#   2. ``age -d`` to decrypt the tar.
#   3. ``pg_restore`` into a *new* database (you supply the target URL,
#      e.g. ``postgres://iams:pw@dr-replica:5432/iams_drill``).
#   4. Optionally re-mirror the MinIO contents to a drill bucket.
#
# The drill verifies the dump is parseable end-to-end; the actual data
# correctness is verified by spot-checking row counts against the
# previous day's production.

set -euo pipefail

: "${AGE_IDENTITY_FILE:?required (path to age private-key file)}"
: "${RESTIC_REPOSITORY:?required}"
: "${RESTIC_PASSWORD:?required}"
: "${1:?usage: restore.sh <snapshot-id|latest> <target-db-url>}"
: "${2:?target db url required (postgres://...)}"

snapshot="$1"
target_db="$2"

work="$(mktemp -d /tmp/iams-restore.XXXXXX)"
trap 'rm -rf "$work"' EXIT

export RESTIC_REPOSITORY RESTIC_PASSWORD
echo "[restore] restic restore ${snapshot} → ${work}"
restic restore "$snapshot" --target "$work"

# Find the encrypted tar
enc_file="$(find "$work" -name 'iams-*.tar.age' | head -1)"
[[ -n "$enc_file" ]] || { echo "[restore] no encrypted tar found"; exit 1; }

echo "[restore] decrypting ${enc_file}"
age -d --identity "$AGE_IDENTITY_FILE" "$enc_file" \
  | tar -C "$work" -xf -

pg_file="$(find "$work" -name 'iams-*.pgdump' | head -1)"
[[ -n "$pg_file" ]] || { echo "[restore] pgdump missing from archive"; exit 1; }

echo "[restore] pg_restore → ${target_db}"
pg_restore --no-owner --no-privileges --clean --if-exists \
  --dbname="$target_db" --jobs=4 "$pg_file"

echo "[restore] ✅ database restored. Spot-check row counts before declaring success."
