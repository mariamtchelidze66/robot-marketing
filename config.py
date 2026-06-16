"""Configuration loader — reads secrets from .env (chmod 600)."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"


def _load_env():
    if not ENV_PATH.exists():
        return
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        os.environ.setdefault(key.strip(), val.strip())


_load_env()

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")

# Web dashboard
WEB_HOST = os.environ.get("WEB_HOST", "0.0.0.0")
WEB_PORT = int(os.environ.get("WEB_PORT", "8080"))
WEB_PASSWORD = os.environ.get("WEB_PASSWORD", "robot1234")  # ramz-e safhe web

DB_PATH = str(BASE_DIR / "robot-marketing.db")
XLSX_PATH = str(BASE_DIR / "robot-marketing.xlsx")

# Models
CLAUDE_MODEL = "claude-opus-4-8"
OPENAI_STT_MODEL = "gpt-4o-transcribe"

# Hداکثر تعداد کارمندِ مجاز (faqat 3 nafar)
MAX_EMPLOYEES = int(os.environ.get("MAX_EMPLOYEES", "3"))
