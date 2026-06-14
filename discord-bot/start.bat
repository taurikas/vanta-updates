@echo off
cd /d "%~dp0"
if not exist .env (
  echo Copy .env.example to .env and set DISCORD_TOKEN
  exit /b 1
)
python bot.py
