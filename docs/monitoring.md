# Интеграция с Zabbix

Мониторинг присылает событие вебхуком, SD заводит по нему заявку в общую
очередь. Восстановление (recovery) переводит заявку в «Решена».

---

## 1. Включение на стороне SD

**Настройки → Мониторинг** (роль руководитель или администратор).

| Поле формы | Что делает |
|------------|------------|
| Интеграция включена | Снятая галочка выключает приём событий целиком — вебхук начнёт отвечать 503 |
| Адрес вебхука | Скопировать в настройки Zabbix (раздел 2). Поле только для чтения |
| Секрет вебхука | Общий секрет, приходит в заголовке `X-Webhook-Secret`. **Только латиница, цифры и знаки препинания** — секрет едет HTTP-заголовком, где кириллица не проходит, и такой секрет форма не примет. Пустое поле при сохранении означает «не менять»; снять секрет — кнопкой «Снять» |
| Переводить заявку в «Решена» при восстановлении | Выключите, если заявку по восстановившемуся алерту должен закрывать человек |
| Контакт по умолчанию | На него вешаются алерты, для которых не удалось определить организацию. Не задан — такие заявки уходят в очередь «Неизвестные» на служебный контакт «Система мониторинга» |
| Имена полей в событии | Меняются, только если ваш шаблон присылает поля под другими именами (раздел 3) |

Ниже формы — таблица последних событий со ссылками на созданные заявки:
удобно проверять, что вебхук доходит.

Значение секрета через API не возвращается никогда — только признак, что он
задан. Хранятся настройки в конфиге канала «Портал» под ключом `monitoring`
(мониторинг — не клиентский канал, и отдельная запись означала бы миграцию
и лишнюю карточку в списке каналов), но для работы это неважно.

<details>
<summary>То же самое через API, если форма недоступна</summary>

```bash
TOKEN=$(curl -s -X POST https://api.sd.example.com/auth/login \
        -d 'username=admin@o-horizons.com&password=ВАШ_ПАРОЛЬ' \
        | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')

curl -X PUT https://api.sd.example.com/settings/monitoring \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"is_enabled": true, "auto_resolve": true,
       "webhook_secret": "придумайте-длинную-строку"}'
```

Ключ `webhook_secret` работает так же, как поле формы: не передан — секрет не
меняется, `null` — снят, строка — записан.

</details>

---

## 2. Настройка на стороне Zabbix

**Alerts → Media types → Create media type**, тип **Webhook**.

Параметры:

| Имя | Значение |
|-----|----------|
| `url` | `https://api.sd.example.com/webhooks/monitoring` |
| `secret` | ваш секрет из раздела 1 |
| `event_id` | `{EVENT.ID}` |
| `subject` | `{EVENT.NAME}` |
| `message` | `{EVENT.OPDATA}` |
| `severity` | `{EVENT.SEVERITY}` |
| `host` | `{HOST.NAME}` |
| `organization` | `{$SD_ORGANIZATION}` — макрос с названием организации, заведите его на группе узлов |
| `status` | `{EVENT.VALUE}` — `1` проблема, `0` восстановление |

Скрипт:

```javascript
var p = JSON.parse(value);
var req = new HttpRequest();
req.addHeader('Content-Type: application/json');
req.addHeader('X-Webhook-Secret: ' + p.secret);

var body = {
    event_id: p.event_id,
    subject: p.subject,
    message: p.message,
    severity: p.severity,
    host: p.host,
    organization: p.organization,
    status: p.status
};

var resp = req.post(p.url, JSON.stringify(body));
if (req.getStatus() !== 202) {
    throw 'SD вернул ' + req.getStatus() + ': ' + resp;
}
return 'ok';
```

Дальше — **Alerts → Actions → Trigger actions**: действие с операцией
«Send message» через этот media type, и **обязательно** галочка recovery
operations, иначе заявки будут открываться и никогда не закрываться.

Если ваш Zabbix не умеет ставить заголовок, секрет можно передать в адресе:
`https://api.sd.example.com/webhooks/monitoring?secret=ВАШ_СЕКРЕТ`. Тогда он
попадёт в логи прокси — выбирайте заголовок, если есть возможность.

---

## 3. Если поля называются иначе

Ожидаемые имена полей задаются в `field_map`. Слева — что нужно SD, справа —
как поле называется в вашем JSON. Указывать нужно только отличия:

```json
"field_map": {
  "external_id": "eventid",
  "subject": "trigger_name",
  "severity": "trigger_severity"
}
```

Значения по умолчанию: `event_id`, `subject`, `message`, `severity`, `host`,
`organization`, `status`.

---

## 4. Как SD трактует событие

**Важность → приоритет заявки:**

| Zabbix | Приоритет |
|--------|-----------|
| disaster, critical | P1 |
| high | P2 |
| average, warning | P3 |
| information | P4 |
| не указана или незнакомая | P3 |

**Восстановлением** считаются значения `OK`, `resolved`, `recovery`,
`recovered`, `closed`, `0`. Всё остальное — проблема. Асимметрия намеренная:
пропущенное восстановление оставит заявку открытой, и её закроет человек, а
ошибочное восстановление молча закрыло бы живой инцидент.

**Одна авария — одна заявка.** Повторный PROBLEM с тем же `event_id`
обновляет существующий алерт и не плодит заявки, поэтому флаппинг триггера
не забивает очередь.

**Организация** ищется по точному совпадению названия. Не нашлась — берётся
`default_contact_id`, а если и его нет, заявка уходит в очередь
«Неизвестные» на служебный контакт «Система мониторинга». Алерт не
теряется никогда, даже если приписать его некому.

**Тема заявки** — `[имя-узла] текст события`, чтобы очередь читалась с одного
взгляда.

---

## 5. Проверка

```bash
SECRET='ваш-секрет'
API=https://api.sd.example.com

# проблема — должна появиться заявка
curl -X POST $API/webhooks/monitoring \
  -H 'Content-Type: application/json' -H "X-Webhook-Secret: $SECRET" \
  -d '{"event_id":"test-1","subject":"Мало места на диске /var",
       "message":"Свободно 4%","severity":"high","host":"srv-1c",
       "organization":"ООО Ромашка","status":"PROBLEM"}'
# {"accepted":true,"alert_id":112,"ticket_id":219354}

# восстановление — заявка перейдёт в «Решена»
curl -X POST $API/webhooks/monitoring \
  -H 'Content-Type: application/json' -H "X-Webhook-Secret: $SECRET" \
  -d '{"event_id":"test-1","status":"OK"}'

# список алертов
curl -s "$API/monitoring/alerts?limit=10" -H "Authorization: Bearer $TOKEN"
```

Проверьте, что неверный секрет даёт `401`:

```bash
curl -o /dev/null -w '%{http_code}\n' -X POST $API/webhooks/monitoring \
  -H 'X-Webhook-Secret: wrong' -H 'Content-Type: application/json' -d '{"event_id":"x"}'
```

---

## 6. Что делать, если не работает

| Ответ | Причина |
|-------|---------|
| `503 Интеграция с мониторингом не настроена` | Канал «Портал» выключен — `is_enabled: true` в разделе 1 |
| `401 Неверный секрет вебхука` | Секрет не совпал или не передан ни заголовком, ни в `?secret=` |
| `202 {"accepted":false,"reason":"invalid_json"}` | Тело не JSON. 202, а не 4xx, намеренно: отправитель с ретраями иначе долбил бы эндпоинт вечно |
| `202`, но заявки нет | В событии нет идентификатора — проверьте `event_id` и `field_map`. Причина будет в `docker compose logs app \| grep -i мониторинг` |
| Заявки открываются, но не закрываются | В действии Zabbix не включены recovery operations, либо `auto_resolve: false` |

---

## 7. Ограничение

Интеграция **не проверялась на боевом Zabbix** — только синтетическими
событиями (полный цикл: проблема → повтор → восстановление, включая проверку
секрета). При первом подключении сверьте фактические имена полей вашего
шаблона с разделом 3.
