#!/usr/bin/env bash
# pg_dump (custom format) → R2 backups/pg/, giữ 14 bản mới nhất. Cron: 0 3 * * * ~/sayfully/scripts/backup.sh
# Cần trong .env: R2_ACCOUNT_ID R2_ACCESS_KEY_ID R2_SECRET_ACCESS_KEY R2_BUCKET; cần `aws` CLI trên VPS.
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; . ./.env; . ./.env.db; set +a

STAMP=$(date -u +%Y%m%dT%H%M%SZ)
FILE="/tmp/sayfully-${STAMP}.dump"
docker compose -f compose.prod.yml exec -T db pg_dump -U "$POSTGRES_USER" -Fc "$POSTGRES_DB" > "$FILE"

export AWS_ACCESS_KEY_ID="$R2_ACCESS_KEY_ID" AWS_SECRET_ACCESS_KEY="$R2_SECRET_ACCESS_KEY" AWS_DEFAULT_REGION=auto
ENDPOINT="https://${R2_ACCOUNT_ID}.r2.cloudflarestorage.com"
aws --endpoint-url "$ENDPOINT" s3 cp "$FILE" "s3://${R2_BUCKET}/backups/pg/$(basename "$FILE")" --only-show-errors
rm -f "$FILE"

# Xoá bản cũ hơn 14 bản mới nhất
aws --endpoint-url "$ENDPOINT" s3 ls "s3://${R2_BUCKET}/backups/pg/" | awk '{print $4}' | sort | head -n -14 \
  | while read -r old; do [ -n "$old" ] && aws --endpoint-url "$ENDPOINT" s3 rm "s3://${R2_BUCKET}/backups/pg/${old}" --only-show-errors; done
echo "backup OK ${STAMP}"
