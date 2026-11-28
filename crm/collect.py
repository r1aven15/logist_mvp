#!/usr/bin/env python3
"""Collect public business contacts from company websites.

Only public pages are read. robots.txt is respected. The script does not
guess addresses or bypass logins/captchas.
"""
from __future__ import annotations

import argparse
import csv
import html as html_lib
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from pathlib import Path

USER_AGENT = "AutoparkControlBot/1.0 (+contact: vsend15@mail.ru)"
EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.I)
PHONE_RE = re.compile(r"(?:\+7|8)[\s\-()]?\d{3}[\s\-()]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}")
BAD_EMAIL_PARTS = ("example.", "example@", "rating@", "test@", "noreply", "no-reply", "sentry", "wixpress", "domain.com")
BAD_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp", ".svg", ".gif", ".css", ".js")


def clean_text(value: str) -> str:
    return " ".join(html_lib.unescape(value).split())


def allowed(url: str) -> bool:
    parts = urllib.parse.urlsplit(url)
    robots_url = f"{parts.scheme}://{parts.netloc}/robots.txt"
    parser = urllib.robotparser.RobotFileParser()
    try:
        parser.set_url(robots_url)
        parser.read()
        return parser.can_fetch(USER_AGENT, url)
    except Exception:
        return True


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "ru,en;q=0.8"})
    with urllib.request.urlopen(req, timeout=15) as response:
        raw = response.read(2_500_000)
        charset = response.headers.get_content_charset() or "utf-8"
    return raw.decode(charset, "replace")


def extract(page: str, source: str) -> dict[str, str]:
    title_match = re.search(r"<title[^>]*>(.*?)</title>", page, re.S | re.I)
    title = clean_text(title_match.group(1)) if title_match else ""
    company = re.split(r"\s+[—–|·]\s+", title, maxsplit=1)[0].strip() or title
    if len(company) > 80:
        company = urllib.parse.urlsplit(source).netloc.removeprefix("www.")
    emails = []
    for match in re.finditer(r'href=["\']mailto:([^"\'?]+)', page, re.I):
        emails.append(urllib.parse.unquote(match.group(1)).strip())
    emails.extend(EMAIL_RE.findall(page))
    phones = []
    for match in re.finditer(r'href=["\']tel:([^"\']+)', page, re.I):
        phones.append(clean_text(urllib.parse.unquote(match.group(1))))
    phones.extend(PHONE_RE.findall(page))
    emails = sorted({e.strip(" .,;:") for e in emails if not any(x in e.lower() for x in BAD_EMAIL_PARTS) and not e.lower().endswith(BAD_EXTENSIONS)})
    phones = sorted({
        p.strip() for p in phones
        if len(re.sub(r"\D", "", p)) >= 10 and len(set(re.sub(r"\D", "", p))) > 3
    })
    return {"company": company, "emails": emails, "phones": phones, "title": title}


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect public business contacts from websites")
    parser.add_argument("--url", action="append", default=[], help="Website URL; can be repeated")
    parser.add_argument("--sources", default="crm/sources.txt", help="File with one URL per line")
    parser.add_argument("--out", default="crm/candidates.csv", help="Output CSV")
    args = parser.parse_args()

    urls = list(args.url)
    sources = Path(args.sources)
    if sources.exists():
        urls.extend(line.strip() for line in sources.read_text(encoding="utf-8").splitlines() if line.strip() and not line.startswith("#"))
    urls = list(dict.fromkeys(urls))
    if not urls:
        print("Нет URL. Добавьте сайты в crm/sources.txt или передайте --url.")
        return 1

    rows = []
    for url in urls:
        if not allowed(url):
            print(f"SKIP robots: {url}")
            continue
        try:
            page = fetch(url)
            data = extract(page, url)
            if not data["emails"] and not data["phones"]:
                print(f"OK, контактов не найдено: {url}")
                continue
            for email in data["emails"] or [""]:
                rows.append({
                    "company": data["company"],
                    "email": email,
                    "phone": "; ".join(data["phones"][:3]),
                    "source": url,
                    "title": data["title"],
                    "notes": "Проверить вручную; публичная страница",
                })
            print(f"OK: {url} -> {len(data['emails'])} email, {len(data['phones'])} phone")
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError) as exc:
            print(f"ERR: {url}: {exc}")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    fields = ["company", "email", "phone", "source", "title", "notes"]
    with out.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Сохранено: {out} ({len(rows)} строк). Проверьте перед импортом в CRM.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
