from flask import Flask, jsonify
from .config import Config
from .extensions import cors, db, jwt
from .seed import ensure_schema_updates, seed_defaults
from .services.relay_client import relay_client
from .services.scheduler_service import scheduler_service


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

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

    @app.errorhandler(404)
    def not_found(_):
        return jsonify({"error": "not_found", "message": "Endpoint tidak ditemukan"}), 404

    @app.errorhandler(Exception)
    def handle_error(error):
        app.logger.exception(error)
        return jsonify({"error": "server_error", "message": str(error)}), 500

    with app.app_context():
        db.create_all()
        ensure_schema_updates()
        seed_defaults()
        relay_client.configure_from_db(app)
        relay_client.start()
        scheduler_service.start(app)

    return app
