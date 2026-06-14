import logging
from flask import Flask, jsonify
from sqlalchemy import event
from .config import Config
from .extensions import cors, db, jwt
from .seed import ensure_schema_updates, seed_defaults
from .services.relay_client import relay_client
from .services.scheduler_service import scheduler_service
from .services.server_log_bridge import ServerLogBridge
from .services.settings_service import get_settings
from .services.waha_service import waha_service
from .services.ollama_service import ollama_service


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    bridge = ServerLogBridge(app)
    bridge.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root_logger = logging.getLogger()
    if not any(isinstance(handler, ServerLogBridge) for handler in root_logger.handlers):
        root_logger.addHandler(bridge)

    db.init_app(app)
    jwt.init_app(app)
    cors.init_app(app)

    from .routes.auth import auth_bp
    from .routes.settings import settings_bp
    from .routes.contacts import contacts_bp
    from .routes.messages import messages_bp
    from .routes.scheduled import scheduled_bp
    from .routes.logs import logs_bp
    from .routes.webhook import webhook_bp

    app.register_blueprint(auth_bp, url_prefix="/api/auth")
    app.register_blueprint(settings_bp, url_prefix="/api/settings")
    app.register_blueprint(contacts_bp, url_prefix="/api/contacts")
    app.register_blueprint(messages_bp, url_prefix="/api/messages")
    app.register_blueprint(scheduled_bp, url_prefix="/api/scheduled")
    app.register_blueprint(logs_bp, url_prefix="/api/logs")
    app.register_blueprint(webhook_bp, url_prefix="/api/webhook")

    @app.get("/api/health")
    def health():
        return jsonify({"ok": True})

    @app.get("/api/health/relay")
    def health_relay():
        return jsonify({"ok": True, "relay": relay_client.health()})

    @app.get("/api/health/waha")
    def health_waha():
        try:
            status = waha_service.get_status()
            return jsonify({"ok": True, "status": status})
        except Exception as exc:
            return jsonify({"ok": False, "message": str(exc)}), 502

    @app.get("/api/health/ollama")
    def health_ollama():
        settings = get_settings()
        try:
            response = ollama_service.generate(
                "Balas hanya dengan: OK",
                settings["ollama_model"],
                settings["ollama_temperature"],
                False,
                settings["ollama_base_url"],
            )
            return jsonify({"ok": True, "response": response})
        except Exception as exc:
            return jsonify({"ok": False, "message": str(exc)}), 502

    @app.errorhandler(404)
    def not_found(_):
        return jsonify({"error": "not_found", "message": "Endpoint tidak ditemukan"}), 404

    @app.errorhandler(Exception)
    def handle_error(error):
        app.logger.exception(error)
        return jsonify({"error": "server_error", "message": str(error)}), 500

    with app.app_context():
        if str(app.config.get("SQLALCHEMY_DATABASE_URI", "")).startswith("sqlite"):
            @event.listens_for(db.engine, "connect")
            def _set_sqlite_pragma(dbapi_connection, _connection_record):
                cursor = dbapi_connection.cursor()
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA synchronous=NORMAL")
                cursor.execute("PRAGMA busy_timeout=30000")
                cursor.close()

        db.create_all()
        ensure_schema_updates()
        seed_defaults()
        relay_client.configure_from_db(app)
        relay_client.start()
        scheduler_service.start(app)

    return app
