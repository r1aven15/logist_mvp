@echo off
chcp 65001 >nul
cd /d "%~dp0.."
python outreach\send_offer.py ^
  --recipients outreach\recipients.csv ^
  --template outreach\01-first-letter.txt
pause
