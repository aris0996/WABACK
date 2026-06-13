from datetime import datetime
from .extensions import db


class AdminUser(db.Model):
    __tablename__ = "admin_users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class AppSetting(db.Model):
    __tablename__ = "app_settings"

    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(120), unique=True, nullable=False)
    value = db.Column(db.Text, nullable=True)


class Contact(db.Model):
    __tablename__ = "contacts"

    id = db.Column(db.Integer, primary_key=True)
    chat_id = db.Column(db.String(120), unique=True, nullable=False)
    name = db.Column(db.String(160), nullable=True)
    type = db.Column(db.String(20), default="private", nullable=False)
    permission = db.Column(db.String(20), default="default", nullable=False)
    reply_mode = db.Column(db.String(30), default="ai_draft", nullable=False)
    trigger_keyword = db.Column(db.String(160), nullable=True)
    active_start = db.Column(db.String(5), nullable=True)
    active_end = db.Column(db.String(5), nullable=True)
    ai_style_override = db.Column(db.Text, nullable=True)
    max_chars_override = db.Column(db.Integer, nullable=True)
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class Message(db.Model):
    __tablename__ = "messages"

    id = db.Column(db.Integer, primary_key=True)
    waha_message_id = db.Column(db.String(160), nullable=True, index=True)
    session = db.Column(db.String(120), nullable=True)
    chat_id = db.Column(db.String(120), nullable=False, index=True)
    sender_id = db.Column(db.String(120), nullable=True)
    sender_name = db.Column(db.String(160), nullable=True)
    body = db.Column(db.Text, nullable=True)
    from_me = db.Column(db.Boolean, default=False, nullable=False)
    is_group = db.Column(db.Boolean, default=False, nullable=False)
    status = db.Column(db.String(30), default="new", nullable=False)
    timestamp = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    drafts = db.relationship("AiDraft", backref="message", lazy=True, cascade="all, delete-orphan")


class AiDraft(db.Model):
    __tablename__ = "ai_drafts"

    id = db.Column(db.Integer, primary_key=True)
    message_id = db.Column(db.Integer, db.ForeignKey("messages.id"), nullable=False, index=True)
    prompt = db.Column(db.Text, nullable=False)
    response = db.Column(db.Text, nullable=True)
    edited_response = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(30), default="generated", nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class ScheduledMessage(db.Model):
    __tablename__ = "scheduled_messages"

    id = db.Column(db.Integer, primary_key=True)
    target_chat_id = db.Column(db.String(120), nullable=False, index=True)
    message = db.Column(db.Text, nullable=False)
    schedule_time = db.Column(db.DateTime, nullable=False, index=True)
    repeat = db.Column(db.String(20), default="none", nullable=False)
    enabled = db.Column(db.Boolean, default=True, nullable=False)
    last_sent_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class MessageLog(db.Model):
    __tablename__ = "message_logs"

    id = db.Column(db.Integer, primary_key=True)
    direction = db.Column(db.String(20), nullable=False)
    chat_id = db.Column(db.String(120), nullable=False, index=True)
    message = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(30), nullable=False)
    error = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
