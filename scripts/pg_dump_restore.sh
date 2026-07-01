#!/usr/bin/env bash
# pg_dump_restore.sh — Round 1 dev data port (CH-02)
#
# Dumps catalog subset from legacy EC2 Postgres and restores to producer dev RDS.
# See docs/contenthub-migration-plan.md §8 for table list and validation steps.
#
# Usage:
#   ./scripts/pg_dump_restore.sh dump   SOURCE_DATABASE_URL OUT.dump
#   ./scripts/pg_dump_restore.sh restore TARGET_DATABASE_URL IN.dump
#   ./scripts/pg_dump_restore.sh validate TARGET_DATABASE_URL

set -euo pipefail

CATALOG_TABLES=(
  clips posts shoots kols kol_groups kol_group_members playlist_tags
  hcps hcp_signals tag_audit tag_proposal
)

cmd="${1:-}"
shift || true

case "$cmd" in
  dump)
    src="${1:?source DATABASE_URL required}"
    out="${2:?output .dump path required}"
    table_args=()
    for t in "${CATALOG_TABLES[@]}"; do
      table_args+=("-t" "$t")
    done
    echo "→ pg_dump catalog subset → $out"
    pg_dump "$src" "${table_args[@]}" --no-owner --no-acl -Fc -f "$out"
    ;;
  restore)
    dst="${1:?target DATABASE_URL required}"
    inp="${2:?input .dump path required}"
    echo "→ pg_restore → producer dev RDS"
    pg_restore --clean --if-exists --no-owner --no-acl -d "$dst" "$inp"
    ;;
  validate)
    dst="${1:?target DATABASE_URL required}"
    echo "→ row counts"
    for t in "${CATALOG_TABLES[@]}"; do
      count=$(psql "$dst" -Atc "SELECT count(*) FROM $t" 2>/dev/null || echo "MISSING")
      printf "  %-24s %s\n" "$t" "$count"
    done
    ;;
  *)
    echo "Usage: $0 dump|restore|validate ..."
    exit 1
    ;;
esac

echo "✓ done"
