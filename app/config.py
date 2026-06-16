import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "change-this-secret")
    DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///data/app.db")
    ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
    ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")
    WEBHOOK_TOKEN = os.getenv("WEBHOOK_TOKEN", "change-this-webhook-token")
    GITHUB_WEBHOOK_SECRET = os.getenv("GITHUB_WEBHOOK_SECRET", "")
    AUTO_UPDATE_API_KEY = os.getenv("AUTO_UPDATE_API_KEY", "")
    AUTO_UPDATE_BRANCH = os.getenv("AUTO_UPDATE_BRANCH", "")
    AUTO_UPDATE_COMMAND = os.getenv("AUTO_UPDATE_COMMAND", "")
    AUTO_UPDATE_TIMEOUT = int(os.getenv("AUTO_UPDATE_TIMEOUT", "300"))
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
    "extractor_model": os.getenv("DEFAULT_EXTRACTOR_MODEL", "wa-memory-extractor"),
    "merger_model": os.getenv("DEFAULT_MERGER_MODEL", "wa-memory-merger"),
    "chatbot_temperature": "0.3",
    "extractor_temperature": "0.1",
    "merger_temperature": "0.1",
    "global_auto_reply": os.getenv("DEFAULT_GLOBAL_AUTO_REPLY", "true"),
    "reply_delay_seconds": "0",
    "default_contact_auto_reply": "true",
    "allowlist_mode": "false",
    "blocklist_numbers": "",
    "allowlist_numbers": "",
    "memory_auto_generate": os.getenv("DEFAULT_MEMORY_AUTO_GENERATE", "true"),
    "memory_generate_interval": os.getenv("DEFAULT_MEMORY_GENERATE_INTERVAL", "20"),
    "memory_generate_mode": "manual_auto",
    "prompt_chatbot_without_memory": "Jawab pesan WhatsApp berikut secara singkat dan natural.",
    "prompt_chatbot_with_memory": "Gunakan memory sebagai konteks internal. Jangan menyebut memory kepada user.",
    "prompt_memory_extractor": "Ekstrak memory dari chat berikut dan keluarkan JSON valid saja.",
    "prompt_memory_merger": "Gabungkan memory lama dan baru. Keluarkan JSON valid saja.",
}
