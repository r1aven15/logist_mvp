# Промпт для нового чата

Скопируй это сообщение в новый чат, если текущий завис или потерялся.

---

Прочитай `/workspace/project/RESTORE_CONTEXT.md`, `/workspace/project/AGENTS.md` и этот файл. Продолжай проект «Автопарк Контроль» без повторных объяснений.

## Что уже работает

- Проект: `/workspace/project`; ветка `openhands/restore-2026-11-25`; сайт: https://r1aven15.github.io/logist_mvp/
- Рабочее приложение: `index.html` и `app.html`; Firestore `gazelle_app/main_data`; Firebase project `gazzele-to`.
- GitHub Actions: job `glonass` в `MAX channel posts` настроен на каждые 5 минут; старый `GLONASS sync` — ручной. Если GitHub-расписание молчит, в workspace работает локальный цикл `crm/glonass_loop.sh` (каждые 5 минут).
- Проверить/запустить локальный цикл: `pgrep -af crm/glonass_loop.sh`; если нет — `nohup crm/glonass_loop.sh >/dev/null 2>&1 &`.
- Ручной запуск: `POST /repos/r1aven15/logist_mvp/actions/workflows/glonass-sync.yml/dispatches` с `{"ref":"main","inputs":{"mode":"sync"}}`.

Презентации (постоянные ссылки GitHub Pages, не workspace):
- Полная: https://r1aven15.github.io/logist_mvp/offer-krsk.html
- PDF: https://r1aven15.github.io/logist_mvp/offer-krsk.pdf
- Короткая: https://r1aven15.github.io/logist_mvp/max.html
- PDF короткой: https://r1aven15.github.io/logist_mvp/max-presentation.pdf
- Демо: https://r1aven15.github.io/logist_mvp/demo-krsk.html
- 750-я (`glonass_505725`): показывать **сырые данные ГЛОНАСС**, без поправки; режим карточки — **литры**. Последний синк: 34,05 л / 48,76%. Если датчик врёт — это калибровка на стороне ГЛОНАСС, не менять формулу приложения.
- ВК: сообщество `club243705360`, 44 запланированных поста (2 в день) до 19.12.2026; первый пост `https://vk.com/wall-243705360_2`. Не дублировать посты.
- Карточки товаров ВК **не делать** — Владимир сказал пока не заниматься.
- Google/Firebase Web API key в `firebaseConfig` — публичный по природе; доступ ограничен по доменам в Google Cloud. Не удалять `firebaseConfig` и `DOC_REF`: без них приложение сломается.

## Секреты и данные

Не публиковать и не коммитить:

- `.secrets/firebase-admin.json`
- `.secrets/glonass.env`
- `.secrets/vk.env`
- `.secrets/gh-admin.env`
- `secrets/CREDENTIALS.md`
- `outreach/.env`
- `data/firestore-main_data.json`
- `data/firestore-backups.json`
- `crm/.vk_channel_state.json`

Если Firestore недоступен — использовать `data/firestore-main_data.json` и `data/firestore-backups.json`.

## Первые действия

1. `cd /workspace/project`
2. `git status` и `git log --oneline -5`
3. Проверить, что на месте `index.html`, `app.html`, `crm/`, `data/`, `.secrets/`.
4. Проверить `firebaseConfig` и строку `const DOC_REF = doc(db, "gazelle_app", "main_data");`.
5. Проверить синтаксис модульного скрипта и открыть `app.html`.
6. Не удалять бэкапы, не публиковать секреты, не менять `firebaseConfig`/`DOC_REF` без причины.

## Если нужен полный restore

- Безопасный архив без секретов и реальных `data/`: `https://r1aven15.github.io/logist_mvp/restore/autopark-restore-2026-11-27.zip`
- Полный зашифрованный архив с секретами и `data/` лежит локально: `/workspace/project/backup/autopark-full-2026-11-27.tar.gz.enc`. Пароль — в `secrets/RESTORE_PACK_PASSWORD.txt` (не публиковать).
- В новом чате в том же workspace секреты и данные уже доступны по путям выше — отдельно передавать их не нужно.
