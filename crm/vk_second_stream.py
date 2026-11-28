"""Second daily VK stream: product cards and short tips at 18:00 Krasnoyarsk."""

import hashlib
import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

ROOT = Path(__file__).resolve().parent.parent
API = "https://api.vk.com/method/"
STATE_PATH = ROOT / "crm/.vk_channel_state.json"
ASSETS = ROOT / "vk-assets"
TZ = ZoneInfo("Asia/Krasnoyarsk")

PRODUCTS = [
    {
        "slug": "start",
        "post_id": 25,
        "image": "card-start.png",
        "date": "2026-11-28T18:00:00+07:00",
        "text": """Автопарк Контроль — «Старт»

Для парка до 5 машин: все разделы программы, 1 пользователь, поддержка в чате.

2 490 ₽/мес. Облако, обновления и резервные копии включены.

Демо: https://r1aven15.github.io/logist_mvp/demo-krsk.html
Напишите «ПИЛОТ» в MAX: https://max.ru/se15129408_bot""",
    },
    {
        "slug": "park",
        "post_id": 26,
        "image": "card-park.png",
        "date": "2026-11-29T18:00:00+07:00",
        "text": """Автопарк Контроль — «Парк»

Для парка до 15 машин: все разделы программы, до 3 пользователей, помощь с переносом данных.

4 990 ₽/мес. Облако, обновления и резервные копии включены.

Демо: https://r1aven15.github.io/logist_mvp/demo-krsk.html
Напишите «ПИЛОТ» в MAX: https://max.ru/se15129408_bot""",
    },
    {
        "slug": "business",
        "post_id": 27,
        "image": "card-business.png",
        "date": "2026-11-30T18:00:00+07:00",
        "text": """Автопарк Контроль — «Бизнес»

Для парка до 30 машин: все разделы программы, до 5 пользователей, приоритетная поддержка.

8 990 ₽/мес. Облако, обновления и резервные копии включены.

Демо: https://r1aven15.github.io/logist_mvp/demo-krsk.html
Напишите «ПИЛОТ» в MAX: https://max.ru/se15129408_bot""",
    },
    {
        "slug": "implementation",
        "post_id": None,
        "image": "card-implementation.png",
        "date": "2026-12-01T18:00:00+07:00",
        "text": """Внедрение и перенос данных — 9 900 ₽ разово

Настроим программу под ваш парк, перенесём машины и водителей, обучим работе и поможем на старте.

Демо: https://r1aven15.github.io/logist_mvp/demo-krsk.html
Напишите «ПИЛОТ» в MAX: https://max.ru/se15129408_bot""",
    },
]

TIPS = [
    "Один час бухгалтера в день — это больше 20 часов в месяц. Сколько из них уходит на сбор данных по машинам?",
    "Три цифры, которые собственник автопарка должен видеть каждый день: выручка, расход топлива и прибыль по каждой машине.",
    "Заправка 50 л при баке 70 л — не повод считать остаток по чеку. Считайте общий объём топлива в баке.",
    "Путевой лист не должен жить в WhatsApp. Один раз занёс данные — отчёт собрался сам.",
    "Ремонт без истории — лотерея. История по каждой машине помогает планировать расходы.",
    "Сколько стоит простой машины? Считайте не только ремонт, но и потерянную выручку.",
    "Excel не враг. Враг — пять файлов, которые не сходятся между собой.",
    "Хороший отчёт отвечает на вопрос «где я теряю деньги», а не просто показывает пробег.",
    "Один продукт — не одна компания. Логика учёта одна, а процессы у всех разные.",
    "Автоматизация без разбора процесса — это дорогая кнопка «сделать красиво».",
    "Пилот на 5 машинах покажет больше, чем месяц презентаций.",
    "Если сотрудники сопротивляются, возможно, вы автоматизируете не их боль, а свою.",
    "Готовое решение дешевле, но не всегда подходит. Считайте стоимость адаптации.",
    "Данные должны забиваться один раз. Всё остальное — автоматически.",
    "Собственник должен видеть прибыль по машине, а не только общую выручку.",
    "Узкое место не всегда там, где кажется. Сначала разбор, потом софт.",
    "Считайте выгоду в деньгах: сколько времени освободилось и сколько вернулось.",
    "Не начинайте с программы. Начните с вопроса: что должно измениться?",
]
TIP_CTA = "\n\nРазберём ваш парк? Напишите «ПИЛОТ» в MAX: https://max.ru/se15129408_bot"


def load_env():
    values = {}
    for line in (ROOT / ".secrets/vk.env").read_text(encoding="utf-8").splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            values[key] = value
    return values


ENV = load_env()
TOKEN = ENV["VK_ACCESS_TOKEN"]
GROUP = ENV["VK_GROUP_ID"]


def call(method, params=None, retries=3):
    data = {"access_token": TOKEN, "v": "5.199"}
    if params:
        data.update(params)
    last = None
    for attempt in range(retries):
        try:
            response = requests.post(API + method, data=data, timeout=30)
            return response.json()
        except ValueError as exc:
            last = f"non-json response: {exc}"
            time.sleep(2 + attempt * 2)
        except requests.RequestException as exc:
            last = str(exc)
            time.sleep(2 + attempt * 2)
    return {"error": {"error_msg": last or "request failed"}}


def upload_image(path):
    response = call("photos.getMessagesUploadServer", {"group_id": GROUP})
    if "response" not in response:
        return None, response
    with path.open("rb") as handle:
        upload = requests.post(
            response["response"]["upload_url"],
            files={"photo": (path.name, handle, "image/png")},
            timeout=60,
        )
    try:
        payload = upload.json()
    except ValueError:
        return None, {"error": {"error_msg": f"upload non-json: {upload.text[:200]}"}}
    saved = call(
        "photos.saveMessagesPhoto",
        {
            "server": payload.get("server"),
            "photo": payload.get("photo"),
            "hash": payload.get("hash"),
        },
    )
    if "response" not in saved or not saved["response"]:
        return None, saved
    photo = saved["response"][0]
    return f"photo{photo['owner_id']}_{photo['id']}", photo


def schedule(text, when, slug, attachment=None):
    params = {
        "owner_id": f"-{GROUP}",
        "from_group": "1",
        "message": text,
        "guid": hashlib.sha1(f"{GROUP}:{slug}:{when.isoformat()}".encode()).hexdigest(),
        "publish_date": str(int(when.timestamp())),
    }
    if attachment:
        params["attachments"] = attachment
    return call("wall.post", params)


def main():
    state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    state.setdefault("scheduled", [])
    state.setdefault("scheduled_posts", {})
    state.setdefault("second_stream", [])
    state.setdefault("second_stream_slugs", {})

    for product in PRODUCTS:
        if product["post_id"]:
            pid = product["post_id"]
            if pid not in state["scheduled"]:
                state["scheduled"].append(pid)
            if pid not in state["second_stream"]:
                state["second_stream"].append(pid)
            state["scheduled_posts"][str(pid)] = {
                "post_id": pid,
                "publish_date": product["date"],
                "kind": "product",
                "slug": product["slug"],
            }
            state["second_stream_slugs"][product["slug"]] = pid

    for product in PRODUCTS:
        if product["slug"] in state["second_stream_slugs"]:
            continue
        when = datetime.fromisoformat(product["date"])
        attachment, info = upload_image(ASSETS / product["image"])
        if not attachment:
            print("image failed", product["slug"], info)
        result = schedule(product["text"], when, f"product-{product['slug']}", attachment)
        if "response" not in result:
            print("product failed", product["slug"], result)
            continue
        pid = result["response"]["post_id"]
        state["scheduled"].append(pid)
        state["second_stream"].append(pid)
        state["scheduled_posts"][str(pid)] = {
            "post_id": pid,
            "publish_date": product["date"],
            "kind": "product",
            "slug": product["slug"],
            "attachment": attachment,
        }
        state["second_stream_slugs"][product["slug"]] = pid
        print("product", product["slug"], "->", pid, product["date"])
        STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        time.sleep(1.5)

    tip_attachment = None
    if "tip" not in state["second_stream_slugs"]:
        tip_attachment, info = upload_image(ASSETS / "tip.png")
        if not tip_attachment:
            print("tip image failed", info)
        state["second_stream_slugs"]["tip"] = tip_attachment or "text-only"

    base = datetime(2026, 12, 2, 18, 0, tzinfo=TZ)
    for index, tip in enumerate(TIPS, 1):
        slug = f"tip-{index}"
        if slug in state["second_stream_slugs"]:
            continue
        when = base + timedelta(days=index - 1)
        result = schedule(tip + TIP_CTA, when, slug, tip_attachment)
        if "response" not in result:
            print("tip failed", index, result)
            continue
        pid = result["response"]["post_id"]
        state["scheduled"].append(pid)
        state["second_stream"].append(pid)
        state["scheduled_posts"][str(pid)] = {
            "post_id": pid,
            "publish_date": when.isoformat(),
            "kind": "tip",
            "slug": slug,
        }
        state["second_stream_slugs"][slug] = pid
        print("tip", index, "->", pid, when.isoformat())
        STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        time.sleep(1.5)

    state["updated_at"] = datetime.now().isoformat(timespec="seconds")
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    print("scheduled_total", len(state["scheduled"]), "second_stream", len(state["second_stream"]))


if __name__ == "__main__":
    main()
