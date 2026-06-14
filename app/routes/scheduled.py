from datetime import datetime, timezone
from flask import Blueprint, jsonify, request
from ..extensions import db
from ..middleware.auth_required import auth_required
from ..models import ScheduledMessage

scheduled_bp = Blueprint("scheduled", __name__)


def parse_dt(value):
    if isinstance(value, str) and value.endswith("Z"):
        value = value[:-1] + "+00:00"
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed
    return parsed.astimezone(timezone.utc).replace(tzinfo=None)


def serialize(item):
    now = datetime.utcnow()
    remaining_seconds = None
    if item.schedule_time:
        remaining_seconds = int((item.schedule_time - now).total_seconds())
    status = item.last_status or "pending"
    if not item.enabled and item.last_sent_at and item.repeat == "none":
        status = "sent"
    elif item.enabled and remaining_seconds is not None and remaining_seconds > 0:
        status = "pending"
    elif item.enabled and remaining_seconds is not None and remaining_seconds <= 0 and status not in ("sent", "scheduled_sent"):
        status = "due"
    return {
        "id": item.id,
        "target_chat_id": item.target_chat_id,
        "message": item.message,
        "schedule_time": f"{item.schedule_time.isoformat()}Z" if item.schedule_time else None,
        "repeat": item.repeat,
        "enabled": item.enabled,
        "last_sent_at": f"{item.last_sent_at.isoformat()}Z" if item.last_sent_at else None,
        "last_status": status,
        "last_error": item.last_error,
        "countdown_seconds": remaining_seconds,
        "created_at": f"{item.created_at.isoformat()}Z" if item.created_at else None,
        "updated_at": f"{item.updated_at.isoformat()}Z" if item.updated_at else None,
    }


def apply(item, payload):
    for key in ["target_chat_id", "message", "repeat", "enabled"]:
        if key in payload:
            setattr(item, key, payload[key])
    if "schedule_time" in payload:
        item.schedule_time = parse_dt(payload["schedule_time"]).replace(tzinfo=None)
        item.last_status = "pending"
        item.last_error = None


@scheduled_bp.get("")
@auth_required
def list_scheduled():
    items = ScheduledMessage.query.order_by(ScheduledMessage.schedule_time.asc()).all()
    return jsonify([serialize(item) for item in items])


@scheduled_bp.post("")
@auth_required
def create_scheduled():
    payload = request.get_json(silent=True) or {}
    for field in ["target_chat_id", "message", "schedule_time"]:
        if not payload.get(field):
            return jsonify({"error": "validation_error", "message": f"{field} wajib diisi"}), 400
    item = ScheduledMessage(target_chat_id=payload["target_chat_id"], message=payload["message"], schedule_time=parse_dt(payload["schedule_time"]).replace(tzinfo=None))
    apply(item, payload)
    item.last_status = "pending"
    db.session.add(item)
    db.session.commit()
    return jsonify(serialize(item)), 201


@scheduled_bp.get("/<int:item_id>")
@auth_required
def get_scheduled(item_id):
    return jsonify(serialize(ScheduledMessage.query.get_or_404(item_id)))


@scheduled_bp.put("/<int:item_id>")
@auth_required
def update_scheduled(item_id):
    item = ScheduledMessage.query.get_or_404(item_id)
    apply(item, request.get_json(silent=True) or {})
    db.session.commit()
    return jsonify(serialize(item))


@scheduled_bp.delete("/<int:item_id>")
@auth_required
def delete_scheduled(item_id):
    item = ScheduledMessage.query.get_or_404(item_id)
    db.session.delete(item)
    db.session.commit()
    return jsonify({"ok": True})
