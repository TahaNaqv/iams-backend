#!/usr/bin/env bash
#
# Nightly IAMS backup — Phase 5 Track 4.
#
# What gets backed up:
#   1. Postgres → ``pg_dump`` (custom format, compressed)
#   2. MinIO bucket → ``mc mirror`` to a local staging dir
#   3. (optional) Redis AOF snapshot
#
# Pipeline:
#   pg_dump → age (encrypt with public-key) → restic (NAS + offsite)
#
# The age recipients file holds the public keys of the backup operators
# (anyone allowed to decrypt). Restic handles dedup + incremental
# snapshots + retention pruning.
#
# Invoke from cron:
#   0 2 * * *  /opt/iams/deploy/backup.sh >> /var/log/iams-backup.log 2>&1
#
# Required environment:
#   PG_HOST, PG_DB, PG_USER, PG_PASSWORD
#   MINIO_ENDPOINT, MINIO_ACCESS_KEY, MINIO_SECRET_KEY, MINIO_BUCKET
#   AGE_RECIPIENTS_FILE   — path to a file with one "age1..." key per line
#   RESTIC_REPOSITORY     — restic repo URL/path (e.g. /mnt/nas/iams)
#   RESTIC_PASSWORD       — repo password
#   RESTIC_OFFSITE_REPOSITORY — second repo for offsite mirror (optional)
#
# Required tools on the backup host:
#   pg_dump (postgresql-client), age, restic, mc (MinIO client)

set -euo pipefail

: "${PG_HOST:?required}"
: "${PG_DB:?required}"
: "${PG_USER:?required}"
: "${PG_PASSWORD:?required}"
: "${AGE_RECIPIENTS_FILE:?required}"
: "${RESTIC_REPOSITORY:?required}"
: "${RESTIC_PASSWORD:?required}"

stamp="$(date -u +'%Y-%m-%dT%H-%M-%SZ')"
work="$(mktemp -d /tmp/iams-backup.XXXXXX)"
trap 'rm -rf "$work"' EXIT

log() { printf '[backup] %s\n' "$*"; }
fail() { printf '[backup][ERROR] %s\n' "$*" >&2; exit 1; }

# ──────────────────────────────────────────────────────────────────────
# 1. Postgres dump
# ──────────────────────────────────────────────────────────────────────
pg_file="${work}/iams-${stamp}.pgdump"
log "pg_dump → ${pg_file}"
PGPASSWORD="$PG_PASSWORD" pg_dump \
  --host="$PG_HOST" --username="$PG_USER" --dbname="$PG_DB" \
  --format=custom --compress=6 --file="$pg_file"

# Verify the dump is parseable before we trust it.
PGPASSWORD="$PG_PASSWORD" pg_restore --list "$pg_file" > /dev/null \
  || fail "pg_dump produced an unreadable file"

# ──────────────────────────────────────────────────────────────────────
# 2. MinIO mirror (object storage — evidence files, report outputs)
# ──────────────────────────────────────────────────────────────────────
if [[ -n "${MINIO_ENDPOINT:-}" && -n "${MINIO_BUCKET:-}" ]]; then
  log "mirroring MinIO bucket=${MINIO_BUCKET}"
  mc alias set iams-src "${MINIO_ENDPOINT}" "${MINIO_ACCESS_KEY}" "${MINIO_SECRET_KEY}" > /dev/null
  mc mirror --overwrite "iams-src/${MINIO_BUCKET}" "${work}/minio"
else
  log "skipping MinIO mirror (MINIO_ENDPOINT unset)"
fi

# ──────────────────────────────────────────────────────────────────────
# 3. Encrypt with age (multi-recipient)
# ──────────────────────────────────────────────────────────────────────
log "encrypting with age"
encrypted="${work}/iams-${stamp}.tar.age"
tar -C "$work" -cf - "iams-${stamp}.pgdump" $([ -d "${work}/minio" ] && echo "minio") \
  | age --recipients-file "$AGE_RECIPIENTS_FILE" --output "$encrypted"

# ──────────────────────────────────────────────────────────────────────
# 4. Restic — NAS (primary)
# ──────────────────────────────────────────────────────────────────────
export RESTIC_REPOSITORY RESTIC_PASSWORD
log "restic snapshot → ${RESTIC_REPOSITORY}"
restic snapshots > /dev/null 2>&1 || restic init
restic backup "$encrypted" --tag iams --tag "${stamp}"
restic forget --tag iams --prune \
  --keep-daily 7 --keep-weekly 4 --keep-monthly 12

# ──────────────────────────────────────────────────────────────────────
# 5. Restic — offsite (secondary)
# ──────────────────────────────────────────────────────────────────────
if [[ -n "${RESTIC_OFFSITE_REPOSITORY:-}" ]]; then
  log "restic mirror → ${RESTIC_OFFSITE_REPOSITORY}"
  RESTIC_REPOSITORY="$RESTIC_OFFSITE_REPOSITORY" restic snapshots \
    > /dev/null 2>&1 || RESTIC_REPOSITORY="$RESTIC_OFFSITE_REPOSITORY" restic init
  RESTIC_REPOSITORY="$RESTIC_OFFSITE_REPOSITORY" \
    restic backup "$encrypted" --tag iams --tag "${stamp}"
fi

log "✅ backup complete"
