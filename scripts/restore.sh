#!/usr/bin/env bash
#
# Восстановление SD из резервной копии (Этап 10).
#
# Запуск: scripts/restore.sh /var/backups/sd/20260803-030000
#
# Операция разрушительная: текущая база будет заменена содержимым копии.
# Поэтому требует явного подтверждения и сначала снимает страховочный дамп
# того, что есть сейчас — восстановление не из той копии случается чаще,
# чем хотелось бы.

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE="${1:-}"

if [[ -z "$SOURCE" || ! -d "$SOURCE" ]]; then
    echo "Использование: $0 <каталог-резервной-копии>" >&2
    echo "Доступные копии:" >&2
    ls -1 "${SD_BACKUP_DIR:-/var/backups/sd}" 2>/dev/null | tail -20 >&2 || echo "  (каталог копий не найден)" >&2
    exit 1
fi

if [[ ! -f "${SOURCE}/database.sql.gz" ]]; then
    echo "ОШИБКА: в ${SOURCE} нет database.sql.gz" >&2
    exit 1
fi

cd "$PROJECT_DIR"
if [[ -f .env ]]; then set -a; source .env; set +a; fi
POSTGRES_USER="${POSTGRES_USER:-sd}"
POSTGRES_DB="${POSTGRES_DB:-sd}"

echo "Будет восстановлено из: ${SOURCE}"
echo "Текущая база ${POSTGRES_DB} будет ЗАМЕНЕНА."
read -r -p "Продолжить? Введите 'да' для подтверждения: " CONFIRM
[[ "$CONFIRM" == "да" ]] || { echo "Отменено."; exit 1; }

SAFETY="/tmp/sd-pre-restore-$(date +%Y%m%d-%H%M%S).sql.gz"
echo "Страховочный дамп текущего состояния → ${SAFETY}"
docker compose exec -T db pg_dump --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" --clean --if-exists --no-owner \
    | gzip > "$SAFETY"

# Воркер и приложение останавливаются: иначе они продолжат писать в базу
# прямо во время восстановления и получат ошибки на пропавших таблицах.
echo "Останавливаю app и worker…"
docker compose stop app worker >/dev/null

echo "Восстанавливаю базу…"
gunzip -c "${SOURCE}/database.sql.gz" | docker compose exec -T db psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" >/dev/null

if [[ -f "${SOURCE}/attachments.tar.gz" ]]; then
    echo "Восстанавливаю вложения…"
    docker compose start app >/dev/null
    sleep 5
    docker compose exec -T app tar xzf - -C /data < "${SOURCE}/attachments.tar.gz"
else
    docker compose start app >/dev/null
fi

docker compose start worker >/dev/null

echo
echo "Готово. Страховочный дамп прежнего состояния: ${SAFETY}"
echo
echo "ПРОВЕРЬТЕ: если .env отличается от того, что был на момент копии,"
echo "секреты интеграций (токены ботов, пароль почты) не расшифруются —"
echo "их нужно ввести заново в Настройки → Каналы. Ключ шифрования лежит"
echo "в env.backup рядом с копией."
