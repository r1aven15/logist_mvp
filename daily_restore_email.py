#!/usr/bin/env python3
"""Build and email a restore pack for Autopark Control.

Default is a light email and a dry run. Use --send to send, --full to attach the ZIP.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import smtplib
import ssl
import subprocess
import sys
import zipfile
from datetime import datetime
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
ENV_FILE = BASE_DIR / "outreach" / ".env"
BACKUP_DIR = BASE_DIR / "backup"
LOG_FILE = BASE_DIR / "crm" / "daily_restore.log"

sys.path.insert(0, str(BASE_DIR / "crm"))
try:
    from context_usage import latest_conversation, usage as context_usage
except Exception:
    latest_conversation = None
    context_usage = None

EXCLUDED_DIRS = {
    ".git", ".secrets", "secrets", "backup", "data", "dist", "node_modules",
    "__pycache__", ".gradle", ".agent_tmp", "outbox", "tmp",
}
EXCLUDED_PATH_PARTS = {
    ("android", "build"),
    ("android", "app", "build"),
}
EXCLUDED_FILES = {
    "crm/.env", "outreach/.env",
    "crm/leads.csv", "crm/companies-2gis.csv", "crm/telegram_leads.csv",
    "crm/candidates.csv", "crm/queue.csv", "crm/config.json",
    "crm/.max_marker", "crm/.max_channel_state.json", "crm/.telegram_offset",
    "crm/.max_bot.pid", "crm/.max_channel_scheduler.pid", "crm/.daily_restore_last", "crm/.vk_channel_state.json",
    "outreach/recipients.csv", "outreach/prospects-krsk.csv", "outreach/sent.log",
    "android/build/autopark.keystore",
}
EXCLUDED_SUFFIXES = {".log", ".pyc", ".pyo", ".keystore", ".jks", ".bundle", ".zip"}


def load_env(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def log(message: str) -> None:
    line = f"[{datetime.now().isoformat(timespec='seconds')}] {message}"
    print(line)
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_info() -> dict:
    def run(*args: str) -> str:
        try:
            result = subprocess.run(
                ["git", *args], cwd=BASE_DIR, capture_output=True, text=True, timeout=15
            )
            return result.stdout.strip()
        except Exception:
            return ""

    return {
        "remote": run("remote", "get-url", "origin"),
        "branch": run("branch", "--show-current"),
        "head": run("rev-parse", "--short", "HEAD"),
        "status_short": run("status", "--short")[:4000],
    }


def pid_running(pid_file: Path) -> tuple[int | None, bool]:
    try:
        pid = int(pid_file.read_text(encoding="utf-8").strip())
    except Exception:
        return None, False
    return pid, Path(f"/proc/{pid}").exists()


def context_snapshot() -> dict:
    if not latest_conversation or not context_usage:
        return {}
    try:
        conversation = latest_conversation()
        return context_usage(conversation) if conversation else {}
    except Exception:
        return {}


def build_checks() -> dict:
    index = (BASE_DIR / "index.html").read_text(encoding="utf-8", errors="replace")
    app = (BASE_DIR / "app.html").read_text(encoding="utf-8", errors="replace")
    demo_names = ["demo.html", "demo-krsk.html", "demo-standalone.html", "demo-krsk-standalone.html"]
    demos = {}
    for name in demo_names:
        text = (BASE_DIR / name).read_text(encoding="utf-8", errors="replace")
        demos[name] = {
            "offline_no_firebase_sdk": "gstatic.com/firebasejs" not in text,
            "forced_demo": "const DEMO = true" in text,
        }

    auth_line = next((line for line in index.splitlines() if 'id="authEmail"' in line), "")
    login_prefilled = bool(re.search(r'id="authEmail"[^>]*\bvalue="[^"]+@"', auth_line))

    real_orgs_in_demo = 0
    real_data = BASE_DIR / "data" / "firestore-main_data.json"
    if real_data.exists():
        try:
            payload = json.loads(real_data.read_text(encoding="utf-8"))
            for org in payload.get("organizations", []):
                name = org if isinstance(org, str) else org.get("name", "")
                if name and any(name in (BASE_DIR / d).read_text(encoding="utf-8", errors="replace") for d in demo_names):
                    real_orgs_in_demo += 1
        except Exception:
            real_orgs_in_demo = -1

    supervisor_pid, supervisor_running = pid_running(BASE_DIR / "crm" / ".max_bot.pid")
    preview_pid, preview_running = pid_running(Path("/tmp/autopark-preview.pid"))

    return {
        "firebase_config_present": "const firebaseConfig = {" in index,
        "doc_ref_exact": 'const DOC_REF = doc(db, "gazelle_app", "main_data");' in index
        and 'const DOC_REF = doc(db, "gazelle_app", "main_data");' in app,
        "login_email_prefilled": login_prefilled,
        "demo": demos,
        "real_orgs_in_demo": real_orgs_in_demo,
        "public_backup_exists": (BASE_DIR / "backup" / "ap-2026-11-23-7f3c9a2e.zip").exists(),
        "max_bot_supervisor_pid": supervisor_pid,
        "max_bot_supervisor_running": supervisor_running,
        "preview_pid": preview_pid,
        "preview_running": preview_running,
    }


def should_include(path: Path) -> bool:
    rel = path.relative_to(BASE_DIR)
    parts = rel.parts
    if any(part in EXCLUDED_DIRS for part in parts[:-1]):
        return False
    if any(tuple(parts[: len(excluded)]) == excluded for excluded in EXCLUDED_PATH_PARTS):
        return False
    rel_posix = rel.as_posix()
    if rel_posix in EXCLUDED_FILES:
        return False
    if path.suffix.lower() in EXCLUDED_SUFFIXES:
        return False
    if path.name.endswith(".apk") and path.name != "autopark-control-v1.9.apk":
        return False
    return path.is_file()


def build_manifest(zip_name: str | None, files: list[Path]) -> dict:
    key_files = [
        "index.html", "app.html", "download.html", "offer-krsk.html", "max.html",
        "RESTORE_CONTEXT.md", "README_RESTORE.md", "restore.py",
        "server/requirements.txt", "crm/max_bot.py", "crm/run_max_bot.sh",
        "crm/context_usage.py", "crm/vk_channel_publish.py", "crm/vk_second_stream.py",
        "crm/build_vk_queue.py", "crm/vk_content_plan.md", "crm/VK_CHANNEL.md",
        "crm/vk_market_cards.md", "crm/SECURITY.md",
        "sync_glonass.py", ".github/workflows/glonass-sync.yml", "crm/GLONASS_SYNC.md",
    ]
    key_info = {}
    for name in key_files:
        path = BASE_DIR / name
        if path.exists():
            key_info[name] = {"size": path.stat().st_size, "sha256": sha256(path)}
    manifest = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "project": "Автопарк Контроль",
        "root": str(BASE_DIR),
        "git": git_info(),
        "checks": build_checks(),
        "context_usage": context_snapshot(),
        "key_files": key_info,
        "zip": None,
        "links": {
            "site": "https://r1aven15.github.io/logist_mvp/",
            "github": "https://github.com/r1aven15/logist_mvp",
            "branch": "https://github.com/r1aven15/logist_mvp/tree/openhands/restore-2026-11-25",
            "preview_demo": "https://work-1-qmwmshdyxpybwoko.prod-runtime.all-hands.dev/demo-krsk.html",
            "preview_offer": "https://work-1-qmwmshdyxpybwoko.prod-runtime.all-hands.dev/offer-krsk.html",
            "preview_offer_pdf": "https://work-1-qmwmshdyxpybwoko.prod-runtime.all-hands.dev/offer-krsk.pdf",
            "preview_max": "https://work-1-qmwmshdyxpybwoko.prod-runtime.all-hands.dev/max.html",
            "preview_max_pdf": "https://work-1-qmwmshdyxpybwoko.prod-runtime.all-hands.dev/max-presentation.pdf",
        },
    }
    if zip_name:
        manifest["zip"] = {
            "name": zip_name,
            "files": len(files),
            "bytes_uncompressed": sum(p.stat().st_size for p in files),
        }
    return manifest


def build_zip(full: bool = True) -> tuple[Path | None, dict]:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    date_tag = datetime.now().strftime("%Y-%m-%d")
    zip_name = f"autopark-restore-{date_tag}.zip" if full else None
    files = [p for p in BASE_DIR.rglob("*") if should_include(p)] if full else []
    manifest = build_manifest(zip_name, files)
    manifest_path = BACKUP_DIR / "MANIFEST.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    zip_path = None
    if full:
        zip_path = BACKUP_DIR / zip_name
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in files:
                archive.write(path, path.relative_to(BASE_DIR).as_posix())
            archive.write(manifest_path, f"backup/{manifest_path.name}")
        log(f"ZIP готов: {zip_path} ({zip_path.stat().st_size} байт, файлов: {len(files)})")
    else:
        log("Лёгкий режим: ZIP не собирался.")
    return zip_path, manifest


def connect_smtp() -> smtplib.SMTP:
    host = os.getenv("SMTP_HOST", "").strip()
    port = int(os.getenv("SMTP_PORT", "465"))
    mode = os.getenv("SMTP_MODE", "ssl").strip().lower()
    user = os.getenv("SMTP_USER", "").strip()
    password = os.getenv("SMTP_PASSWORD", "")
    if not host or not user or not password:
        raise SystemExit("Set SMTP_HOST, SMTP_USER and SMTP_PASSWORD in outreach/.env")
    context = ssl.create_default_context()
    if mode == "starttls":
        server = smtplib.SMTP(host, port, timeout=30)
        server.starttls(context=context)
    else:
        server = smtplib.SMTP_SSL(host, port, timeout=30, context=context)
    server.login(user, password)
    return server


def send_email(zip_path: Path | None, manifest: dict, recipient: str, full: bool = True) -> None:
    sender = os.getenv("SMTP_FROM") or os.getenv("SMTP_USER") or ""
    if not sender:
        raise SystemExit("Set SMTP_FROM or SMTP_USER in outreach/.env")
    sender_name = os.getenv("SMTP_NAME", "").strip() or "Автопарк Контроль"
    date_human = datetime.now().strftime("%d.%m.%Y")
    links = manifest.get("links", {})
    ctx = manifest.get("context_usage") or {}
    if ctx:
        context_line = (
            f"{ctx.get('percent', '?')}% "
            f"({ctx.get('used_tokens', 0):,} / {ctx.get('context_window', 0):,} токенов)"
        )
    else:
        context_line = "нет данных"

    if full:
        title = "полный пакет восстановления"
        archive_line = f"- {zip_path.name} — исходники и публичные файлы без секретов."
    else:
        title = "лёгкий пакет восстановления"
        archive_line = "- ZIP не прикладываю: код и файлы лежат в GitHub, письмо лёгкое."

    body = f"""Владимир, это {title} «Автопарк Контроль» за {date_human}.

Что внутри:
- RESTORE_CONTEXT.md — кто ты, что делаем, где что лежит и как восстановить.
- MANIFEST.json — состояние проекта, проверки и контекст.
{archive_line}

Ссылки:
- Презентация: {links.get('preview_offer')}
- PDF презентации: {links.get('preview_offer_pdf')}
- Короткая версия: {links.get('preview_max')}
- PDF короткой версии: {links.get('preview_max_pdf')}
- GitHub-ветка: {links.get('branch')}

Контекст сейчас: {context_line}.

Что важно по проекту:
- GitHub Actions: GLONASS sync каждые 5 минут, секреты добавлены, последний run успешен.
- VK: сообщество club243705360, 44 поста (2 в день) до 19.12.2026; первый пост уже опубликован.
- 750: данные ГЛОНАСС без поправки; последний синк 34,21 л / 48,87%. Главное — регулярное обновление; при необходимости калибровать датчик на стороне ГЛОНАСС.

Как продолжить в новом чате:
«Прочитай /workspace/project/RESTORE_CONTEXT.md и продолжай».

Проверки:
- firebaseConfig на месте: {manifest['checks']['firebase_config_present']}
- строка DOC_REF на месте: {manifest['checks']['doc_ref_exact']}
- демо без Firebase SDK: {all(v['offline_no_firebase_sdk'] for v in manifest['checks']['demo'].values())}
- реальные организации в демо: {manifest['checks']['real_orgs_in_demo']}
- предзаполненный email на входе: {manifest['checks']['login_email_prefilled']}

Важно: секреты и реальные data/ в письмо не кладу. Они лежат отдельно.
"""
    message = EmailMessage()
    message["From"] = formataddr((sender_name, sender))
    message["To"] = recipient
    message["Reply-To"] = sender
    message["Date"] = formatdate(localtime=True)
    message["Message-ID"] = make_msgid()
    suffix = "полный пакет" if full else "контекст восстановления"
    message["Subject"] = f"Автопарк Контроль — {suffix} {date_human}"
    message.set_content(body)

    attachments = [BASE_DIR / "RESTORE_CONTEXT.md", BACKUP_DIR / "MANIFEST.json"]
    if zip_path:
        attachments.append(zip_path)
    for path in attachments:
        if not path.exists():
            continue
        if path.suffix == ".md":
            maintype, subtype = "text", "markdown"
        elif path.suffix == ".json":
            maintype, subtype = "application", "json"
        else:
            maintype, subtype = "application", "zip"
        message.add_attachment(
            path.read_bytes(), maintype=maintype, subtype=subtype, filename=path.name
        )

    server = connect_smtp()
    try:
        server.send_message(message)
    finally:
        try:
            server.quit()
        except Exception:
            pass
    log(f"Письмо отправлено на {recipient} ({'полный' if full else 'лёгкий'} режим)")


def main() -> int:
    parser = argparse.ArgumentParser(description="Restore email for Autopark Control")
    parser.add_argument("--send", action="store_true", help="Send email; default is build only")
    parser.add_argument("--full", action="store_true", help="Attach full ZIP; default is light")
    parser.add_argument("--to", default=os.getenv("RESTORE_EMAIL_TO", ""), help="Recipient email")
    args = parser.parse_args()

    load_env(ENV_FILE)
    zip_path, manifest = build_zip(full=args.full)
    recipient = args.to or os.getenv("SMTP_FROM") or os.getenv("SMTP_USER") or ""
    if not recipient:
        raise SystemExit("Set RESTORE_EMAIL_TO or SMTP_FROM/SMTP_USER")
    log(f"Получатель: {recipient}")
    if args.send:
        send_email(zip_path, manifest, recipient, full=args.full)
    else:
        log("Dry run: письмо не отправлено. Добавь --send.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
