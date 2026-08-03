# Развёртывание и администрирование SD

Инструкция для системного администратора «Открытых Горизонтов». Предполагается
чистая Linux-ВМ с Docker и Docker Compose. Всё, что описано ниже, выполняется
на самой ВМ — внешних сервисов, кроме API мессенджеров и телефонии, система не
использует (ТЗ р. 1).

---

## 1. Первичная установка

```bash
git clone <репозиторий> /srv/sd
cd /srv/sd
cp .env.example .env
```

Дальше **обязательно** заполнить секреты (см. раздел 2), иначе система
поднимется с общеизвестными значениями из репозитория.

```bash
docker compose up -d --build
docker compose ps          # все контейнеры должны быть Up/healthy
```

Миграции и наполнение справочников выполняются автоматически при старте
контейнера `app`.

Проверка:

| Что | Адрес |
|-----|-------|
| Панель сотрудника | `http://<хост>:8081` |
| Личный кабинет клиента | `http://<хост>:8081/portal` |
| API | `http://<хост>:8080` |
| Документация API | `http://<хост>:8080/docs` |

Первый вход — `SEED_ADMIN_EMAIL` / `SEED_ADMIN_PASSWORD` из `.env`.
**Смените пароль сразу после входа** (Профиль → Смена пароля).

---

## 2. Секреты — самое важное при переносе в прод

В `.env.example` лежат рабочие значения по умолчанию, и они опубликованы в
репозитории. В production **все они должны быть заменены**.

```bash
# Секрет подписи токенов
python3 -c "import secrets; print(secrets.token_urlsafe(48))"

# Ключ шифрования секретов интеграций
python3 -c "import base64,os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())"
```

Заполнить в `.env`:

```ini
ENVIRONMENT=production
JWT_SECRET=<первая команда>
SETTINGS_ENCRYPTION_KEY=<вторая команда>
POSTGRES_PASSWORD=<произвольный длинный пароль>
SEED_ADMIN_PASSWORD=<временный, сменить после первого входа>
CORS_ORIGINS=["https://sd.example.com"]
FRONTEND_API_BASE_URL=https://api.sd.example.com
```

При `ENVIRONMENT=production` приложение и воркер при старте пишут в лог явное
предупреждение, если что-то из перечисленного осталось значением по умолчанию.
Проверить:

```bash
docker compose logs app | grep -i внимание
```

### ⚠ `SETTINGS_ENCRYPTION_KEY` нельзя менять на живой системе

Этим ключом зашифрованы токены ботов MAX и Telegram, пароли IMAP/SMTP и секреты
вебхуков. При смене ключа **ранее сохранённые секреты расшифровать невозможно** —
их придётся ввести заново через Настройки → Каналы. Поэтому ключ генерируется
один раз, **до** ввода учётных данных интеграций, и дальше хранится так же
бережно, как резервные копии: без него бэкап восстановит систему, но все каналы
придётся настраивать с нуля.

Если система уже поработала на dev-ключе и переезжает в прод:

1. сгенерировать новый ключ, прописать в `.env`;
2. `docker compose up -d --build app worker`;
3. зайти в Настройки → Каналы и **ввести заново** токены MAX, Telegram, пароли
   почты, секреты вебхуков телефонии и мониторинга.

---

## 3. TLS и домены

Система слушает HTTP; TLS терминируется внешним nginx или Caddy на той же ВМ.
По ТЗ (р. 7) портал клиента живёт на отдельном поддомене.

Пример nginx-фронта:

```nginx
server {
    listen 443 ssl;
    server_name sd.example.com;              # панель сотрудника
    ssl_certificate     /etc/letsencrypt/live/sd.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/sd.example.com/privkey.pem;
    location / { proxy_pass http://127.0.0.1:8081; }
}

server {
    listen 443 ssl;
    server_name lk.example.com;              # портал клиента
    ssl_certificate     /etc/letsencrypt/live/lk.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/lk.example.com/privkey.pem;
    # Портал отдаётся тем же бандлом по пути /portal
    location / { proxy_pass http://127.0.0.1:8081/portal; }
}

server {
    listen 443 ssl;
    server_name api.sd.example.com;          # API
    ssl_certificate     /etc/letsencrypt/live/api.sd.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/api.sd.example.com/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;

        # Обязательно для живых уведомлений (websocket)
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 3600s;
    }
}
```

После смены адреса API **пересобрать фронтенд** — `FRONTEND_API_BASE_URL`
вшивается в JS-бандл на этапе сборки, а не читается в рантайме:

```bash
docker compose up -d --build frontend
```

---

## 4. Резервное копирование

```bash
# разовый запуск
/srv/sd/scripts/backup.sh

# ежедневно в 03:00
crontab -e
0 3 * * * /srv/sd/scripts/backup.sh >> /var/log/sd-backup.log 2>&1
```

Копия включает дамп БД, вложения и `.env` (ради ключа шифрования). Скрипт
проверяет целостность дампа и держит копии `SD_BACKUP_RETENTION_DAYS` дней
(по умолчанию 14).

**Копии обязательно увозить с этой машины.** Бэкап рядом с базой не спасает ни
от отказа диска, ни от шифровальщика:

```bash
0 4 * * * rsync -az /var/backups/sd/ backup@nas:/backups/sd/
```

### Восстановление

```bash
/srv/sd/scripts/restore.sh /var/backups/sd/20260803-030000
```

Скрипт спрашивает подтверждение, снимает страховочный дамп текущего состояния
в `/tmp`, останавливает `app` и `worker`, разворачивает базу и вложения.

**Проверяйте восстановление раз в квартал на тестовой машине.** Непроверенная
резервная копия — это надежда, а не бэкап; сам скрипт проверен на полном цикле
(заявка, созданная после копии, после восстановления исчезает).

---

## 5. Обновление версии

```bash
cd /srv/sd
./scripts/backup.sh                  # всегда перед обновлением
git pull
docker compose up -d --build
docker compose logs -f app           # дождаться "Application startup complete"
```

Миграции применяются автоматически. Откат при неудаче:

```bash
git checkout <предыдущий-тег>
docker compose up -d --build
./scripts/restore.sh <копия перед обновлением>   # если миграция уже прошла
```

Миграции Alembic вниз не откатываются автоматически — при неудачном обновлении
после применённой миграции восстанавливайте из копии.

---

## 6. Настройка каналов

Все интеграции настраиваются **в интерфейсе**, не в `.env`:
Настройки → Каналы (роль руководитель или администратор).

| Канал | Что нужно | Куда указать адрес |
|-------|-----------|--------------------|
| Email | IMAP/SMTP ящика поддержки | — |
| MAX | токен бота | — (long polling) |
| Telegram | токен бота от `@BotFather` | — (long polling) |
| Телефония | секрет вебхука | в ЛК Plusofon: `https://api.sd.example.com/webhooks/telephony` |

Для MAX в образ backend встроен корневой сертификат Минцифры — без него
обращения к `platform-api2.max.ru` не проходят проверку TLS.

Телефония **не проверялась на боевом аккаунте** — только синтетическими
событиями. При первом подключении сверьте фактические имена полей вебхука
с формой настроек канала: маппинг настраивается там же, без правки кода.

### Мониторинг (Zabbix)

Настраивается в **Настройки → Мониторинг**: там же адрес вебхука, который
нужно указать в Zabbix, и таблица последних событий для проверки. Инструкция
по стороне Zabbix (media type, скрипт, макросы) — в [monitoring.md](monitoring.md).

---

## 7. Эксплуатация

### Логи

```bash
docker compose logs -f app       # API
docker compose logs -f worker    # SLA-эскалации, боты, расписания
docker compose logs --tail 200 worker | grep -i ошибка
```

### Что делает воркер

| Задача | Периодичность |
|--------|---------------|
| SLA-эскалации 75 % / 100 % | `WORKER_INTERVAL_SECONDS` (60 с) |
| Автозакрытие решённых заявок | тот же цикл |
| Плановые заявки по расписанию | тот же цикл |
| Опрос почты | интервал из настроек канала |
| MAX, Telegram | long polling, отдельные потоки |

Если перестали приходить сообщения из мессенджеров — почти всегда виноват
воркер, а не приложение:

```bash
docker compose restart worker
```

### Проверка состояния

```bash
curl -s http://localhost:8080/health          # {"status":"ok"}
docker compose ps                              # healthy у db и app
docker compose exec db psql -U sd -d sd -c "SELECT count(*) FROM tickets;"
```

### Место на диске

Растут вложения и логи Docker. Контроль:

```bash
docker system df
docker compose exec app du -sh /data/attachments
```

---

## 8. Производительность

Нагрузочная проверка (ТЗ р. 11) — скрипт `scripts/loadtest.py`:

```bash
docker compose exec app python /srv/scripts/loadtest.py --days 365
docker compose exec app python /srv/scripts/loadtest.py --cleanup   # обязательно после
```

Результаты и выводы — в `docs/decisions.md`, раздел про Этап 10.
**Не запускайте наполнение на боевой базе** — оно создаёт сотни тысяч
тестовых заявок; для проверки поднимайте отдельный стенд.

---

## 9. Типичные неполадки

| Симптом | Причина и что делать |
|---------|----------------------|
| 502 от nginx после пересборки | nginx закешировал старый IP контейнера. Уже исправлено (`resolver` в `nginx/nginx.conf`); если повторилось — `docker compose restart nginx` |
| Колокольчик не обновляется мгновенно | Не проходит websocket. Проверьте `Upgrade`-заголовки на внешнем nginx (р. 3). Уведомления при этом продолжают приходить с задержкой до 30 с — опрос работает как запасной путь |
| Каналы «отвалились» после переноса | Сменился `SETTINGS_ENCRYPTION_KEY` — ввести токены заново (р. 2) |
| MAX: ошибка TLS | Пересобрать образ backend, сертификат Минцифры ставится при сборке |
| Не приходят письма | Проверьте `docker compose logs worker \| grep -i почт` и доступность IMAP с ВМ |
| Заявки не создаются из Telegram | Бот добавлен в групповой чат? Обрабатываются только личные диалоги |

---

## 10. Что стоит сделать до ввода в эксплуатацию

- [ ] Заменены `JWT_SECRET`, `SETTINGS_ENCRYPTION_KEY`, пароли БД и админа
- [ ] `ENVIRONMENT=production`, `CORS_ORIGINS` сужен до реального домена
- [ ] TLS настроен, портал вынесен на отдельный поддомен
- [ ] Бэкап в cron, копии увозятся на другую машину
- [ ] Восстановление проверено на тестовом стенде
- [ ] Каналы настроены и проверены живым сообщением
- [ ] Вебхуки телефонии и мониторинга проверены реальными событиями
- [ ] Заведены учётные записи сотрудников, пароль администратора сменён
