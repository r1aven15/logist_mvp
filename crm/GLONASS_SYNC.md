# ГЛОНАСС — синхронизация без Render и UptimeRobot

## Что случилось

Старая схема: Render-сервис с `/sync` + UptimeRobot раз в 5 минут. UptimeRobot «пинал» Render, чтобы тот не засыпал и забирал данные из ГЛОНАСС.

По факту:

- последняя запись `glonass_sync/status.lastRun` — **24.11.2026 02:39 UTC**;
- на 25.11.2026 синка не было больше суток;
- приложение показывало старое топливо (у 750-й машины — завышенное), а на приборке было актуальное «88 км».

## Новая схема

GitHub Actions запускает `sync_glonass.py` каждые 5 минут. Render и UptimeRobot для синка больше не нужны.

- Workflow: `.github/workflows/glonass-sync.yml`
- Скрипт: `sync_glonass.py`
- Что обновляет: `glonass_vehicles/*` и `glonass_sync/status`; `gazelle_app/main_data` не трогает.
- Какие машины: 6 настроенных ID — `505725,542782,550744,577075,621945,655079`.
- Время: `GLONASS_TIMEZONE=7` (Красноярск).
- Топливо: API отдаёт **литры**. Для 750-й (`505725`, бак 70 л) скрипт дополнительно пишет `fuelPercent`; в `GLONASS_FUEL_TANKS` указано `505725:70`.

## Особенности API, проверено 26.11.2026

- Документация: https://glonasssoft.ru/wiki/metody-api-dlya-raboty-s-glonasssoft
- Хост API: https://hosting.glonasssoft.ru
- `POST /api/v3/vehicles/getlastdata` принимает ключ **`vehiclesIds`**. Ключ `vehicleIds` из письма поддержки возвращает HTTP 400; в скрипте оставлен fallback на него.
- Датчик топлива называется `Топливо`; `rawValue` — литры (`27.698...`), `displayValue` — `27.7 л`.
- `POST /api/v3/vehicles/mileageAndMotohours` принимает `vehicleIds`; время возвращается в UTC, параметр `timezone` игнорируется.
- `POST /api/v3/fuelcards/transactions` — история топливных транзакций, пока не используется.

## Секреты GitHub

Settings → Secrets and variables → Actions → New repository secret:

- `GLONASS_LOGIN` — логин ГЛОНАСС;
- `GLONASS_PASSWORD` — пароль ГЛОНАСС;
- `FIREBASE_CREDENTIALS` — **весь JSON** сервисного аккаунта Firebase (можно вставить как есть);
- `HEALTHCHECK_URL` — необязательно, ping-URL из Healthchecks.io.

Секреты не коммитить. Если пароль ГЛОНАСС лежал в `инструкция.txt`, его нужно сменить: старый мог попасть в историю GitHub.

## Проверка

1. Actions → **GLONASS sync** → Run workflow.
2. `mode = probe` — только чтение, без записи.
3. `mode = sync` — запись в Firestore.
4. В приложении открой «ГЛОНАСС» — статус должен стать зелёным, топливо обновится.

## Расписание

- `cron: "*/5 * * * *"` — каждые 5 минут.
- GitHub может задержать запуск на несколько минут; это нормально.
- Расписание работает с **default branch** (`main`). Workflow добавлен в `main`; после добавления секретов расписание включится автоматически.
- Для публичного репозитория минуты GitHub Actions бесплатны.

## Мониторинг

UptimeRobot можно оставить только для сайта, но не для синка. Для синка лучше **Healthchecks.io**:

1. Создай check с периодом 5 минут и grace 10 минут.
2. Скопируй ping-URL в секрет `HEALTHCHECK_URL`.
3. Workflow пингует URL после успешного синка.
4. Если синка не было 10–15 минут — Healthchecks пришлёт письмо/Telegram.

## Инцидент 27.11.2026

- Два запуска workflow (`workflow_dispatch` 26.11 14:50 UTC и `schedule` 26.11 23:23 UTC) упали за 10–16 секунд.
- Лог: `ERROR Sync failed: GLONASS_LOGIN / GLONASS_PASSWORD are not set`.
- Причина не в ГЛОНАСС: repository secrets не добавлены, переменные в job пустые. `FIREBASE_CREDENTIALS` тоже пустой.
- Локальный синк 27.11 01:16 UTC обновил 6 машин, `glonass_sync/status` — `ok=true`, `errors=[]`.
- До добавления секретов автоматического обновления каждые 5 минут нет; локальный запуск — разовый.

## Если ошибка

- `741947: no fuel sensor` или `851155: no mileage` — это новые машины без настроенных датчиков. В workflow указаны только 6 рабочих ID; если добавляешь новую — добавь её ID в `GLONASS_VEHICLE_IDS`.
- `FIREBASE_CREDENTIALS` — вставь полный JSON, начиная с `{` и заканчивая `}`.
- `401` от ГЛОНАСС — пароль сменился; обнови `GLONASS_PASSWORD`.
- Долго нет запусков — проверь, что workflow в default branch и Actions не отключены.

## Текущее состояние после ручного синка

- 750-я машина (`505725`): датчик отдаёт **27.7 л**, это **39.57%** при баке 70 л. В `glonass_vehicles` хранятся `fuelLevel=27.7`, `fuelUnit=л`, `fuelPercent=39.57`; приложение в процентном режиме берёт `fuelPercent`.
- Раньше в документе лежало `39.29` с единицей `л` — это была уже пересчитанная величина, а не сырые литры; теперь единицы согласованы.
- `glonass_sync/status`: `ok = true`, `errors = []`, `vehicles = 6`.
- Приложение получает обновление через Firestore onSnapshot; если открыто — обновится само, иначе перезагрузи страницу.
