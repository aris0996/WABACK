import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "change-this-secret")
    DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///data/app.db")
    ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
    ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")
    WEBHOOK_TOKEN = os.getenv("WEBHOOK_TOKEN", "")
    WAHA_WEBHOOK_REQUIRE_TOKEN = os.getenv("WAHA_WEBHOOK_REQUIRE_TOKEN", "false").lower() == "true"
    GITHUB_WEBHOOK_SECRET = os.getenv("GITHUB_WEBHOOK_SECRET", "")
    AUTO_UPDATE_API_KEY = os.getenv("AUTO_UPDATE_API_KEY", "")
    AUTO_UPDATE_BRANCH = os.getenv("AUTO_UPDATE_BRANCH", "")
    AUTO_UPDATE_COMMAND = os.getenv("AUTO_UPDATE_COMMAND", "")
    AUTO_UPDATE_TIMEOUT = int(os.getenv("AUTO_UPDATE_TIMEOUT", "300"))
    AUTO_UPDATE_RESTART_WORKER = os.getenv("AUTO_UPDATE_RESTART_WORKER", "true").lower() == "true"
    LOG_RETENTION_DAYS = int(os.getenv("LOG_RETENTION_DAYS", "14"))
    APP_TIMEZONE = os.getenv("APP_TIMEZONE", "Asia/Makassar")
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    PERMANENT_SESSION_LIFETIME = 60 * 60 * 12


DEFAULT_SETTINGS = {
    "waha_base_url": os.getenv("DEFAULT_WAHA_BASE_URL", "http://localhost:3000"),
    "waha_session": os.getenv("DEFAULT_WAHA_SESSION", "default"),
    "waha_api_key": os.getenv("DEFAULT_WAHA_API_KEY", ""),
    "waha_enabled": "true",
    "ollama_base_url": os.getenv("DEFAULT_OLLAMA_BASE_URL", "http://host.docker.internal:11434"),
    "chatbot_model": os.getenv("DEFAULT_CHATBOT_MODEL", "wa-chatbot"),
    "chatbot_temperature": "0.3",
    "chatbot_num_predict": "180",
    "ollama_keep_alive": "30s",
    "ollama_request_timeout": "300",
    "ai_reply_prefix": "_Balasan otomatis AI:_\n",
    "waha_typing_enabled": "true",
    "global_auto_reply": os.getenv("DEFAULT_GLOBAL_AUTO_REPLY", "true"),
    "reply_delay_seconds": "0",
    "default_contact_auto_reply": "true",
    "group_trigger_keywords": "bot\nai",
    "history_context_limit": "5",
    "waha_history_sync_limit": "300",
    "waha_sync_page_size": "300",
    "waha_sync_max_contacts": "2000",
}
