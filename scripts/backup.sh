#!/usr/bin/env bash
#
# Резервное копирование SD (Этап 10).
#
# Снимает три вещи, потому что восстановление любой одной из них по
# отдельности бесполезно:
#   1. дамп PostgreSQL — заявки, переписка, договоры, настройки каналов;
#   2. каталог вложений — файлы лежат на диске, в БД только пути;
#   3. .env — там ключ SETTINGS_ENCRYPTION_KEY, без которого секреты
#      интеграций в дампе невозможно расшифровать. Дамп без ключа
#      восстановит систему, но все токены каналов придётся вводить заново.
#
# Запуск: scripts/backup.sh [каталог]
# Cron:   0 3 * * * /srv/sd/scripts/backup.sh >> /var/log/sd-backup.log 2>&1

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKUP_DIR="${1:-${SD_BACKUP_DIR:-/var/backups/sd}}"
RETENTION_DAYS="${SD_BACKUP_RETENTION_DAYS:-14}"
STAMP="$(date +%Y%m%d-%H%M%S)"
TARGET="${BACKUP_DIR}/${STAMP}"

cd "$PROJECT_DIR"

# Читаем POSTGRES_* из .env, не затирая уже заданные переменные окружения.
if [[ -f .env ]]; then
    set -a; source .env; set +a
fi
POSTGRES_USER="${POSTGRES_USER:-sd}"
POSTGRES_DB="${POSTGRES_DB:-sd}"

echo "[$(date +%H:%M:%S)] Резервное копирование в ${TARGET}"
mkdir -p "$TARGET"

# --- 1. База данных -------------------------------------------------------
# --clean --if-exists: восстановление на непустую базу не потребует ручной
# очистки. Пишем через docker exec, чтобы не требовать psql на хосте.
echo "  БД…"
docker compose exec -T db pg_dump \
    --username "$POSTGRES_USER" \
    --dbname "$POSTGRES_DB" \
    --clean --if-exists --no-owner \
    | gzip > "${TARGET}/database.sql.gz"

# --- 2. Вложения ----------------------------------------------------------
# Именованный том, поэтому копируем изнутри контейнера, а не с хоста.
echo "  вложения…"
docker compose exec -T app tar czf - -C /data attachments > "${TARGET}/attachments.tar.gz" 2>/dev/null \
    || echo "    (каталог вложений пуст либо недоступен — пропущено)"

# --- 3. Конфигурация ------------------------------------------------------
if [[ -f .env ]]; then
    cp .env "${TARGET}/env.backup"
    chmod 600 "${TARGET}/env.backup"
fi

# --- Проверка целостности дампа -------------------------------------------
# Пустой или обрезанный дамп выглядит как успешный бэкап до самого момента
# восстановления — проверяем сразу, пока есть кому об этом сообщить.
if ! gzip -t "${TARGET}/database.sql.gz" 2>/dev/null; then
    echo "ОШИБКА: дамп БД повреждён" >&2
    exit 1
fi
DUMP_SIZE=$(stat -f%z "${TARGET}/database.sql.gz" 2>/dev/null || stat -c%s "${TARGET}/database.sql.gz")
if [[ "$DUMP_SIZE" -lt 1024 ]]; then
    echo "ОШИБКА: дамп БД подозрительно мал (${DUMP_SIZE} байт)" >&2
    exit 1
fi

# --- Ротация --------------------------------------------------------------
find "$BACKUP_DIR" -mindepth 1 -maxdepth 1 -type d -mtime "+${RETENTION_DAYS}" -exec rm -rf {} + 2>/dev/null || true

echo "[$(date +%H:%M:%S)] Готово: $(du -sh "$TARGET" | cut -f1), хранение ${RETENTION_DAYS} дн."
echo
echo "ВАЖНО: копию нужно увозить с этой машины (rsync/S3/внешний диск) —"
echo "бэкап на том же сервере не спасёт от отказа диска или шифровальщика."
