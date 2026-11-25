#!/usr/bin/env python3
"""Build and email a daily restore pack for Autopark Control.

Default is a dry run. Use --send to actually send the email.
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
    "crm/.max_bot.pid", "crm/.max_channel_scheduler.pid", "crm/.daily_restore_last",
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


def build_manifest(zip_name: str, files: list[Path]) -> dict:
    key_files = [
        "index.html", "app.html", "download.html", "offer-krsk.html", "max.html",
        "RESTORE_CONTEXT.md", "README_RESTORE.md", "restore.py",
        "server/requirements.txt", "crm/max_bot.py", "crm/run_max_bot.sh",
    ]
    key_info = {}
    for name in key_files:
        path = BASE_DIR / name
        if path.exists():
            key_info[name] = {"size": path.stat().st_size, "sha256": sha256(path)}
    return {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "project": "Автопарк Контроль",
        "root": str(BASE_DIR),
        "git": git_info(),
        "checks": build_checks(),
        "key_files": key_info,
        "zip": {
            "name": zip_name,
            "files": len(files),
            "bytes_uncompressed": sum(p.stat().st_size for p in files),
        },
        "links": {
            "site": "https://r1aven15.github.io/logist_mvp/",
            "github": "https://github.com/r1aven15/logist_mvp",
            "preview_demo": "https://work-1-qmwmshdyxpybwoko.prod-runtime.all-hands.dev/demo-krsk.html",
        },
    }


def build_zip() -> tuple[Path, dict]:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    date_tag = datetime.now().strftime("%Y-%m-%d")
    zip_name = f"autopark-restore-{date_tag}.zip"
    zip_path = BACKUP_DIR / zip_name
    files = [p for p in BASE_DIR.rglob("*") if should_include(p)]
    manifest = build_manifest(zip_name, files)
    manifest_path = BACKUP_DIR / "MANIFEST.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, path.relative_to(BASE_DIR).as_posix())
        if manifest_path.exists():
            archive.write(manifest_path, f"backup/{manifest_path.name}")
    log(f"ZIP готов: {zip_path} ({zip_path.stat().st_size} байт, файлов: {len(files)})")
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


def send_email(zip_path: Path, manifest: dict, recipient: str) -> None:
    sender = os.getenv("SMTP_FROM") or os.getenv("SMTP_USER") or ""
    if not sender:
        raise SystemExit("Set SMTP_FROM or SMTP_USER in outreach/.env")
    sender_name = os.getenv("SMTP_NAME", "").strip() or "Автопарк Контроль"
    date_human = datetime.now().strftime("%d.%m.%Y")

    body = f"""Владимир, это ежедневный пакет восстановления «Автопарк Контроль» за {date_human}.

Внутри:
- RESTORE_CONTEXT.md — кто ты, что делаем, где что лежит и как восстановить.
- MANIFEST.json — состояние проекта, проверки и список файлов.
- {zip_path.name} — исходники и публичные файлы без секретов.

Как продолжить в новом чате:
«Прочитай /workspace/project/RESTORE_CONTEXT.md и продолжай».

Проверки на момент отправки:
- firebaseConfig на месте: {manifest['checks']['firebase_config_present']}
- строка DOC_REF на месте: {manifest['checks']['doc_ref_exact']}
- демо без Firebase SDK: {all(v['offline_no_firebase_sdk'] for v in manifest['checks']['demo'].values())}
- реальные организации в демо: {manifest['checks']['real_orgs_in_demo']}
- предзаполненный email на входе: {manifest['checks']['login_email_prefilled']}

Важно: в архиве нет secrets/, .secrets/ и реальных data/. Секреты лежат отдельно. Не пересылай это письмо.
"""
    message = EmailMessage()
    message["From"] = formataddr((sender_name, sender))
    message["To"] = recipient
    message["Reply-To"] = sender
    message["Date"] = formatdate(localtime=True)
    message["Message-ID"] = make_msgid()
    message["Subject"] = f"Автопарк Контроль — пакет восстановления {date_human}"
    message.set_content(body)

    for path in [BASE_DIR / "RESTORE_CONTEXT.md", BACKUP_DIR / "MANIFEST.json", zip_path]:
        if not path.exists():
            continue
        maintype = "text" if path.suffix == ".md" else "application"
        subtype = "markdown" if path.suffix == ".md" else ("json" if path.suffix == ".json" else "zip")
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
    log(f"Письмо отправлено на {recipient}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Daily restore pack for Autopark Control")
    parser.add_argument("--send", action="store_true", help="Send email; default is build only")
    parser.add_argument("--to", default=os.getenv("RESTORE_EMAIL_TO", ""), help="Recipient email")
    args = parser.parse_args()

    load_env(ENV_FILE)
    zip_path, manifest = build_zip()
    recipient = args.to or os.getenv("SMTP_FROM") or os.getenv("SMTP_USER") or ""
    if not recipient:
        raise SystemExit("Set RESTORE_EMAIL_TO or SMTP_FROM/SMTP_USER")
    log(f"Получатель: {recipient}")
    if args.send:
        send_email(zip_path, manifest, recipient)
    else:
        log("Dry run: письмо не отправлено. Добавь --send.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
