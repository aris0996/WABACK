from datetime import datetime
from flask import Blueprint, jsonify, request
from ..middleware.auth_required import auth_required
from ..models import MessageLog

logs_bp = Blueprint("logs", __name__)


@logs_bp.get("")
@auth_required
def logs():
    query = MessageLog.query
    if request.args.get("chat_id"):
        query = query.filter_by(chat_id=request.args["chat_id"])
    if request.args.get("direction"):
        query = query.filter_by(direction=request.args["direction"])
    if request.args.get("status"):
        query = query.filter_by(status=request.args["status"])
    if request.args.get("date_from"):
        query = query.filter(MessageLog.created_at >= datetime.fromisoformat(request.args["date_from"]))
    if request.args.get("date_to"):
        query = query.filter(MessageLog.created_at <= datetime.fromisoformat(request.args["date_to"]))
    items = query.order_by(MessageLog.created_at.desc()).limit(300).all()
    return jsonify([
        {
            "id": item.id,
            "direction": item.direction,
            "chat_id": item.chat_id,
            "message": item.message,
            "status": item.status,
            "error": item.error,
            "created_at": item.created_at.isoformat() if item.created_at else None,
        }
        for item in items
    ])
