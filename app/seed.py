import os
from werkzeug.security import generate_password_hash
from .extensions import db
from .models import AdminUser, AppSetting, Contact


DEFAULT_SETTINGS = {
    "waha_base_url": os.getenv("WAHA_BASE_URL", "http://127.0.0.1:3000"),
    "waha_api_key": os.getenv("WAHA_API_KEY", "arisdev09"),
    "waha_session": os.getenv("WAHA_SESSION", "default"),
    "ollama_base_url": os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
    "ollama_model": os.getenv("OLLAMA_MODEL", "llama3.1"),
    "ollama_temperature": os.getenv("OLLAMA_TEMPERATURE", "0.7"),
    "ollama_max_chars": os.getenv("OLLAMA_MAX_CHARS", "800"),
    "ai_style": "ramah, singkat, natural, dan membantu",
    "system_prompt": "Kamu adalah asisten WhatsApp yang membantu admin menjawab pesan pelanggan.",
    "stream_enabled": "true",
    "relay_server_url": os.getenv("RELAY_SERVER_URL", "ws://streamdeck.arisdev.my.id/ws"),
    "relay_token": os.getenv("RELAY_TOKEN", "@arisdev09"),
    "relay_backend_device_id": os.getenv("RELAY_BACKEND_DEVICE_ID", "backend-waha-ai"),
    "relay_backend_role": os.getenv("RELAY_BACKEND_ROLE", "pc"),
    "relay_flutter_target_device_id": os.getenv("RELAY_FLUTTER_TARGET_DEVICE_ID", "phone-aris"),
    "default_reply_mode": os.getenv("DEFAULT_REPLY_MODE", "disabled"),
}


def ensure_schema_updates():
    inspector = db.inspect(db.engine)
    if "contacts" not in inspector.get_table_names():
        return

    columns = {column["name"] for column in inspector.get_columns("contacts")}
    additions = {
        "priority_level": "ALTER TABLE contacts ADD COLUMN priority_level VARCHAR(20) NOT NULL DEFAULT 'normal'",
        "daily_auto_reply_limit": "ALTER TABLE contacts ADD COLUMN daily_auto_reply_limit INTEGER",
        "cooldown_seconds": "ALTER TABLE contacts ADD COLUMN cooldown_seconds INTEGER NOT NULL DEFAULT 0",
        "fallback_to_draft_on_error": "ALTER TABLE contacts ADD COLUMN fallback_to_draft_on_error BOOLEAN NOT NULL DEFAULT 1",
        "keyword_match_mode": "ALTER TABLE contacts ADD COLUMN keyword_match_mode VARCHAR(20) NOT NULL DEFAULT 'contains'",
        "last_auto_replied_at": "ALTER TABLE contacts ADD COLUMN last_auto_replied_at DATETIME",
        "last_inbound_at": "ALTER TABLE contacts ADD COLUMN last_inbound_at DATETIME",
    }
    for name, sql in additions.items():
        if name not in columns:
            db.session.execute(db.text(sql))
    db.session.commit()


def seed_defaults():
    if not AdminUser.query.filter_by(username="admin").first():
        db.session.add(AdminUser(username="admin", password_hash=generate_password_hash("admin123")))

    sync_env = os.getenv("SYNC_ENV_SETTINGS_ON_BOOT", "false").lower() in ("1", "true", "yes", "on")
    for key, value in DEFAULT_SETTINGS.items():
        setting = AppSetting.query.filter_by(key=key).first()
        if not setting:
            db.session.add(AppSetting(key=key, value=value))
        elif key == "waha_base_url" and setting.value == "http://103.210.121.29:3000":
            setting.value = "http://127.0.0.1:3000"
        elif key == "default_reply_mode" and setting.value == "ai_draft":
            setting.value = "disabled"
        elif sync_env:
            setting.value = value

    Contact.query.filter_by(permission="default").update({
        "permission": "blocked",
        "reply_mode": "disabled",
    })
    Contact.query.filter((Contact.priority_level.is_(None)) | (Contact.priority_level == "")).update({
        "priority_level": "normal",
    })
    Contact.query.filter(Contact.keyword_match_mode.is_(None)).update({
        "keyword_match_mode": "contains",
    })
    Contact.query.filter(Contact.cooldown_seconds.is_(None)).update({
        "cooldown_seconds": 0,
    })
    Contact.query.filter(Contact.fallback_to_draft_on_error.is_(None)).update({
        "fallback_to_draft_on_error": True,
    })

    db.session.commit()
