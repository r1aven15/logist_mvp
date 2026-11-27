# Autopark Control — память для агента

Сначала прочитай `RESTORE_CONTEXT.md` — там кто пользователь, что за проект, где что лежит и как восстановить.

Коротко:
- Пользователь: Владимир Анисимов, Красноярск. Бизнес по оптимизации бизнесов, основное приложение — «Автопарк Контроль». Работает в транспортной компании, тестирует приложение на реальных рейсах; опыт в разных сферах. Бухгалтер тоже тестирует.
- Требования: ссылки стабильные; демо отдельно; в демо нет реальных данных; рабочая база не затрагивается.
- Не удалять бэкапы без прямой команды.
- Не публиковать `secrets/`, `.secrets/`, `data/`, `crm/.env`, `outreach/.env`.
- Рабочее приложение: `index.html`, `app.html` (Firebase). Демо: `demo*.html` — офлайн-сборка без Firebase SDK.
- ВКонтакте: `crm/vk_content_plan.md` (23 поста), `crm/vk_channel_queue.json`, `crm/vk_channel_publish.py`, `crm/vk_second_stream.py`, `crm/build_vk_queue.py`, `crm/vk_market_cards.md`, `crm/VK_CHANNEL.md`. Сообщество `club243705360` (ID 243705360); обложка и описание обновлены; 44 поста (2/день) с 28.11 по 19.12.2026; товарные посты с картинками 28.11–01.12. Токен — только в `.secrets/vk.env`/GitHub Secrets.
- Машины: ОСАГО, СТС и КАСКО в карточке; данные в `car.sts`/`car.kasko`, чипы документов и просмотр; тест Playwright на демо.
- Топливо: `fuelSensorMode` (`liters`/`percent`), `fuelManual` (ручной ввод вместо ГЛОНАСС); 750-я — бак 70 л, норма 15,6, режим `percent`; ГЛОНАСС отдаёт литры, для 750 пишется `fuelPercent` (27.7 л → 39.57%), приложение берёт процент; `GLONASS_FUEL_TANKS=505725:70`.
- ГЛОНАСС workflow добавлен в `main`; секреты GitHub Actions не добавлены (403 токена), нужны `GLONASS_LOGIN`, `GLONASS_PASSWORD`, `FIREBASE_CREDENTIALS`. 26.11.2026 оба запуска упали с `GLONASS_LOGIN / GLONASS_PASSWORD are not set`; локальный синк 27.11 01:16 UTC обновил 6 машин.
- ГЛОНАСС: `sync_glonass.py` + `.github/workflows/glonass-sync.yml` каждые 5 минут; 6 ID; инструкция `crm/GLONASS_SYNC.md`; Render/UptimeRobot `/sync` для синка больше не нужны. Живой API проверен 26.11.2026: `getlastdata` принимает `vehiclesIds` (`vehicleIds` → 400), датчик `Топливо` отдаёт литры; для 750 пишется `fuelPercent`. Пароль ГЛОНАСС мог попасть в историю `инструкция.txt` — сменить.
- Еженедельный лёгкий пакет восстановления: `daily_restore_email.py`, воскресенье 23:30 по Красноярску на `vsend15@mail.ru`; полный ZIP — по команде `--full`. Заполнение контекста: `python3 crm/context_usage.py`.
- Незакрытое: бухгалтер просил проверить расчёт маршрута в последнем обновлении; ссылки `outreach-kit.zip` и старые `backup/...` в `download.html`; скиллы из другого чата.

- 27.11.2026: GitHub Actions secrets configured; GLONASS sync success (`46001862659`); auto sync every 5 min. VK secrets also set.
