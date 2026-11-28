@echo off
chcp 65001 >nul
cd /d "%~dp0.."
echo Отправка только адресатам с consent=yes. Максимум 20 писем.
python outreach\send_offer.py ^
  --recipients outreach\recipients.csv ^
  --template outreach\01-first-letter.txt ^
  --send --confirm-consent --limit 20 --delay 30
pause
