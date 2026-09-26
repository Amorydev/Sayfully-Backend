#!/usr/bin/env bash
# pg_dump (custom format) → $BACKUP_DIR trên VPS, giữ 14 bản mới nhất. Cron: 0 3 * * * ~/sayfully/scripts/backup.sh
# Không đẩy lên bucket R2 media: bucket đó public, dump chứa email + hash mật khẩu.
set -euo pipefail
cd "$(dirname "$0")/.."
# Chỉ source .env.db; .env là env_file của docker (giá trị kiểu `Tên <email>` làm shell lỗi).
set -a; . ./.env.db; set +a

BACKUP_DIR="${BACKUP_DIR:-$HOME/sayfully-data/backups}"
KEEP=14
mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"

STAMP=$(date -u +%Y%m%dT%H%M%SZ)
FILE="$BACKUP_DIR/sayfully-${STAMP}.dump"
COMPOSE="docker compose -f compose.prod.yml $( [ -f compose.local.yml ] && echo "-f compose.local.yml" )"

# Ghi ra .part rồi mới đổi tên, để dump hỏng giữa chừng không bị tính là một bản backup.
$COMPOSE exec -T db pg_dump -U "$POSTGRES_USER" -Fc "$POSTGRES_DB" > "$FILE.part"
$COMPOSE exec -T db pg_restore -l < "$FILE.part" > /dev/null
mv "$FILE.part" "$FILE"
chmod 600 "$FILE"

# Xoá bản cũ hơn $KEEP bản mới nhất (tên theo mốc giờ UTC nên sắp theo tên là theo thời gian)
ls -1 "$BACKUP_DIR"/sayfully-*.dump | sort | head -n -"$KEEP" | xargs -r rm -f
echo "backup OK ${STAMP} $(du -h "$FILE" | cut -f1)"
