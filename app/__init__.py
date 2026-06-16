from flask import Flask

from .auth import auth_bp
from .config import Config
from .db import init_db
from .routes.api_routes import api_bp
from .routes.dashboard_routes import dashboard_bp
from .routes.update_routes import update_bp
from .routes.webhook_routes import webhook_bp


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    init_db(app)

    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(webhook_bp)
    app.register_blueprint(update_bp)

    @app.errorhandler(404)
    def not_found(_error):
        return {"ok": False, "error": "Not found"}, 404

    @app.errorhandler(500)
    def server_error(_error):
        return {"ok": False, "error": "Internal server error"}, 500

    return app
