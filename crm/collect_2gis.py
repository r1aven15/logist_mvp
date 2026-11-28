#!/usr/bin/env python3
"""Discover Krasnoyarsk transport companies via 2GIS Places API.

The demo key may return company names/addresses but not contact_groups.
If contact_groups is unavailable, the script still saves companies for
manual enrichment and says so.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import time
import urllib.parse
import urllib.request
from pathlib import Path

BASE = Path(__file__).resolve().parent
ROOT = BASE.parent
REGION_ID = "7"  # Красноярск
API = "https://catalog.api.2gis.com/3.0/items"
DEFAULT_QUERIES = [
    "грузоперевозки",
    "транспортная компания",
    "логистика",
    "автовозы",
    "рефрижераторные перевозки",
    "грузовой транспорт",
    "экспедирование грузов",
]
FIELDS = ["company", "email", "phone", "website", "address", "segment", "source", "source_id", "notes"]
EXCLUDE_RUBRICS = ("Продажа грузовых автомобилей", "Запчасти для грузовых авто")


def load_key() -> str:
    key = os.getenv("DGIS_API_KEY", "")
    env = BASE / ".env"
    if not key and env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.startswith("DGIS_API_KEY="):
                key = line.split("=", 1)[1].strip()
                break
    if not key:
        raise SystemExit("DGIS_API_KEY не задан. Добавьте его в crm/.env или окружение.")
    return key


def fetch(query: str, page: int, page_size: int, key: str) -> dict:
    params = {
        "q": query,
        "region_id": REGION_ID,
        "page": page,
        "page_size": page_size,
        "locale": "ru_RU",
        "fields": "items.address,items.rubrics,items.org,items.contact_groups,items.external_content",
        "key": key,
    }
    url = API + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "AutoparkControlCRM/1.0"})
    with urllib.request.urlopen(req, timeout=25) as response:
        return json.loads(response.read().decode("utf-8"))


def contacts(item: dict) -> tuple[list[str], list[str], list[str]]:
    emails, phones, sites = [], [], []
    for group in item.get("contact_groups", []) or []:
        for contact in group.get("contacts", []) or []:
            kind = contact.get("type", "")
            value = str(contact.get("value", "")).strip()
            if not value:
                continue
            if kind == "email":
                emails.append(value)
            elif kind == "phone":
                phones.append(value)
            elif kind == "website":
                sites.append(value)
    return sorted(set(emails)), sorted(set(phones)), sorted(set(sites))


def main() -> int:
    parser = argparse.ArgumentParser(description="2GIS company discovery for Krasnoyarsk")
    parser.add_argument("--query", action="append", default=[], help="Search query; repeatable")
    parser.add_argument("--pages", type=int, default=5)
    parser.add_argument("--page-size", type=int, default=10)
    parser.add_argument("--out", default="crm/companies-2gis.csv")
    parser.add_argument("--merge", action="store_true", help="Append found companies to crm/leads.csv")
    parser.add_argument("--delay", type=float, default=0.4)
    args = parser.parse_args()

    key = load_key()
    queries = args.query or DEFAULT_QUERIES
    found: dict[str, dict] = {}
    contact_permission = False
    for query in queries:
        for page in range(1, args.pages + 1):
            try:
                data = fetch(query, page, args.page_size, key)
            except Exception as exc:
                print(f"ERR {query!r} page {page}: {type(exc).__name__}")
                break
            items = (data.get("result") or {}).get("items") or []
            if not items:
                break
            for item in items:
                item_id = str(item.get("id", ""))
                if not item_id or item_id in found:
                    continue
                emails, phones, sites = contacts(item)
                if emails or phones or sites:
                    contact_permission = True
                rubrics = ", ".join(r.get("name", "") for r in item.get("rubrics", [])[:3])
                if any(ex in rubrics for ex in EXCLUDE_RUBRICS):
                    continue
                found[item_id] = {
                    "company": item.get("name", ""),
                    "email": "; ".join(emails),
                    "phone": "; ".join(phones),
                    "website": "; ".join(sites),
                    "address": item.get("address_name", ""),
                    "segment": rubrics,
                    "source": f"https://2gis.ru/krasnoyarsk/firm/{item_id}",
                    "source_id": f"2gis:{item_id}",
                    "notes": "2GIS; проверить перед контактом" + ("; контакты получены" if emails or phones or sites else "; нужен email/сайт"),
                }
            if len(items) < args.page_size:
                break
            time.sleep(max(0, args.delay))
        print(f"{query}: всего найдено {len(found)}")

    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(found.values())
    print(f"Сохранено: {out} ({len(found)} компаний)")
    if not contact_permission:
        print("ВНИМАНИЕ: ключ не отдаёт contact_groups. Собраны компании без email/телефонов.")
        print("Для контактов нужен ключ 2GIS с разрешением items.contact_groups.")

    if args.merge:
        leads_path = BASE / "leads.csv"
        fields = ["id", "company", "segment", "city", "website", "email", "phone", "contact", "role", "source", "basis", "status", "score", "last_contact", "next_action", "next_date", "notes", "source_id"]
        existing = []
        if leads_path.exists():
            with leads_path.open(encoding="utf-8", newline="") as fh:
                existing = list(csv.DictReader(fh))
        known = {x.get("source_id", "") for x in existing if x.get("source_id")}
        added = 0
        for row in found.values():
            if row["source_id"] in known:
                continue
            existing.append({
                "id": "2gis-" + row["source_id"].split(":", 1)[-1],
                "company": row["company"], "segment": row["segment"], "city": "Красноярск",
                "website": row["website"], "email": row["email"], "phone": row["phone"],
                "contact": "", "role": "", "source": "2GIS", "basis": "public_business",
                "status": "new", "score": "", "last_contact": "", "next_action": "enrich",
                "next_date": time.strftime("%Y-%m-%d"), "notes": row["notes"] + f"; {row['address']}",
                "source_id": row["source_id"],
            })
            added += 1
        with leads_path.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(existing)
        print(f"Добавлено в CRM: {added}. Без email черновики не создаются.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
