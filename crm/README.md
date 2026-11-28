# CRM MVP — автоматизация первичных продаж

Это рабочий каркас, а не «робот, который всё делает сам». Он собирает лиды, готовит персональные черновики, ведёт очередь, отвечает на частые вопросы и показывает дашборд.

## Что уже работает

- `collect.py` — сбор публичных деловых контактов с сайтов; robots.txt соблюдается.
- `run_mvp.py` — скоринг, персональные `.eml`-черновики, очередь, дашборд.
- `send_queue.py` — утверждение и отправка с дневным лимитом; по умолчанию dry-run.
- `chat.html` + `knowledge.json` — бот для FAQ по ценам, 1С, серверу, налогам, телематике.
- `faq_bot.py` — тот же FAQ-бот для CLI и будущих адаптеров MAX/Telegram.
- `bot_server.py` — HTTP API `/ask` для подключения MAX/Telegram.
- `daily.sh` — ежедневный сбор и подготовка очереди; `cron.example` — пример расписания.
- `CHEATSHEET.md` — короткие ответы по серверу, 1С и 152-ФЗ.

## 2GIS: автосбор компаний

Ключ хранится в `crm/.env` (в git не попадает). Демо-ключ 2GIS отдаёт компании, адреса и рубрики, но не отдаёт `contact_groups` — email/телефоны. Это ограничение ключа, не скрипта.

```bash
python3 crm/collect_2gis.py --pages 3 --merge
```

Результат: `crm/companies-2gis.csv` и новые строки в `crm/leads.csv` со статусом `new` и `next_action=enrich`.

Чтобы получить email/телефоны автоматически, нужен ключ 2GIS с разрешением `items.contact_groups`. Без него контакты добавляются вручную: открыть карточку 2GIS, взять сайт/email, затем прогнать `collect.py` по сайту.

Публичные страницы 2GIS технически содержат контакты, но я не стал их парсить: это обход разрешений API и риск нарушения условий 2GIS.

## Ежедневная отправка (5 писем)

Планировщик запускает батч в 09:00 по Красноярску (02:00 UTC): обновляет черновики, утверждает очередь и отправляет не более 5 писем.

```bash
python3 crm/daily_scheduler.py
```

Ручной запуск батча:

```bash
python3 crm/daily_outreach.py --send
```

Без `--send` скрипт только обновляет черновики и ничего не отправляет. Контакты новых компаний пополняются в `leads.csv`; отправитель берёт только `status=new` с публичным email.

## Закрытая CRM

Веб-CRM: список лидов, поиск, фильтры, карточка заявки, статусы, заметки и готовый текст «Что написать».

```bash
python3 crm/crm_server.py --port 12001
```

Логин и пароль задаются в `crm/.env`:

```env
CRM_USER=admin
CRM_PASSWORD=...
CRM_URL=http://127.0.0.1:12001/
```

CRM закрыта HTTP Basic Auth. Не публикуй `crm/.env` и не добавляй ссылку в открытые страницы.

## Telegram-бот CargoHunt

Бот: `@CargoHuntbot`. Работает только с входящими сообщениями и не пишет незнакомым людям.

```bash
python3 crm/telegram_bot.py
```

Что умеет:

- `/start` — приветствие и кнопки;
- отвечает на вопросы по ценам, налогам, 1С/Excel и серверу;
- собирает заявку: имя, компания, парк, телефон;
- пишет заявку в `crm/leads.csv` и `crm/telegram_leads.csv`;
- уведомляет администратора, если задан `TELEGRAM_ADMIN_CHAT_ID`;
- дублирует заявку на почту `NOTIFY_EMAIL` через SMTP из `outreach/.env`.

Как включить уведомления:

1. Открой `@CargoHuntbot`, нажми «Start».
2. Отправь `/id` — бот покажет твой chat_id.
3. Добавь в `crm/.env`: `TELEGRAM_ADMIN_CHAT_ID=твой_id`.
4. Перезапусти бота.

Почта для дублей задаётся в `crm/.env`: `NOTIFY_EMAIL=...`. Если не задана, используется `SMTP_USER`.

Фоновый запуск:

```bash
nohup python3 crm/telegram_bot.py >> /tmp/cargo-hunt-bot.log 2>&1 &
```

Для автозапуска есть `crm/telegram-bot.service.example`.

## Быстрый старт

Из корня проекта:

```bash
python3 crm/collect.py --sources crm/sources.txt
python3 crm/run_mvp.py --import-candidates
python3 crm/send_queue.py --list
```

Открыть дашборд и бота:

```bash
python3 -m http.server 8080
```

- `http://localhost:8080/crm/dashboard.html`
- `http://localhost:8080/crm/chat.html`

Публичная версия бота (без лидов): `@CargoHuntbot` в Telegram.
Локальная веб-версия: `http://localhost:8080/crm/chat.html`

API для MAX/Telegram:

```bash
python3 crm/bot_server.py --port 8090
curl -X POST -H 'Content-Type: application/json' -d '{"text":"Сколько стоит?"}' http://127.0.0.1:8090/ask
```

## Ежедневный цикл

1. Добавить 5–10 сайтов в `crm/sources.txt`.
2. Запустить `python3 crm/collect.py`.
3. Проверить `crm/candidates.csv` вручную.
4. Запустить `python3 crm/run_mvp.py --import-candidates`.
5. Посмотреть очередь: `python3 crm/send_queue.py --list`.
6. Утвердить конкретные письма: `python3 crm/send_queue.py --approve ID`.
7. Отправить: `python3 crm/send_queue.py --send --confirm --limit 5`.
8. Через 3–5 дней `run_mvp.py` сам подготовит follow-up по датам.

## Статусы лидов

`new` → `contacted` → `replied` → `demo` → `proposal` → `won` / `lost`.

Меняйте статус в `crm/leads.csv` вручную после ответа или звонка.

## Правила безопасности

- Только публичные деловые адреса, без купленных баз.
- Не больше 5 писем в день.
- В каждом письме есть opt-out: «ответьте „нет“».
- Отправка только после `approved=yes`.
- Цену, скидку, договор и юридические гарантии обсуждает Владимир.
- Бот обозначен как бот; на сложный вопрос переводит на человека.

## Что пока не подключено

- MAX/Telegram API — нужен токен и вебхук; логика ответов уже есть в `faq_bot.py`.
- Календарь и запись на демо.
- Полноценная CRM (Bitrix24/amoCRM) — сейчас CSV и дашборд.
- Автоматическая отправка без подтверждения — сознательно не включена.

## Что нельзя публиковать

`leads.csv`, `queue.csv`, `outbox/`, `sent.log` и `dashboard.html` содержат контакты и переписку. Не выкладывайте их на публичный сервер и не коммитьте в открытый репозиторий. Публично можно отдать только `chat.html` и `knowledge.json`.

## Файлы

- `config.json` — отправитель, ссылки, цены, лимиты.
- `leads.csv` — лиды и статусы.
- `lead-template.csv` — шаблон для ручного добавления.
- `sources.txt` — сайты для сбора.
- `templates/` — тексты писем.
- `outbox/` — готовые `.eml`-черновики.
- `queue.csv` — очередь на утверждение/отправку.
- `sent.log` — журнал отправок.
