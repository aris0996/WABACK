from flask import Blueprint, jsonify, request
from flask_jwt_extended import create_access_token
from werkzeug.security import check_password_hash
from ..models import AdminUser

auth_bp = Blueprint("auth", __name__)


@auth_bp.post("/login")
def login():
    payload = request.get_json(silent=True) or {}
    user = AdminUser.query.filter_by(username=payload.get("username")).first()
    if not user or not check_password_hash(user.password_hash, payload.get("password", "")):
        return jsonify({"error": "invalid_credentials", "message": "Username atau password salah"}), 401
    return jsonify({"access_token": create_access_token(identity=str(user.id)), "user": {"id": user.id, "username": user.username}})
