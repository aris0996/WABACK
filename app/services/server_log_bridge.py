import logging
import threading
from datetime import datetime

from ..extensions import db
from ..models import MessageLog


class ServerLogBridge(logging.Handler):
    def __init__(self, app):
        super().__init__(level=logging.WARNING)
        self.app = app
        self._local = threading.local()

    def emit(self, record):
        if getattr(self._local, "busy", False):
            return
        if record.name.startswith("werkzeug"):
            return
        try:
            self._local.busy = True
            message = record.getMessage()
            status = {
                logging.WARNING: "server_warning",
                logging.ERROR: "server_error",
                logging.CRITICAL: "server_critical",
            }.get(record.levelno, "server_log")
            with self.app.app_context():
                db.session.add(
                    MessageLog(
                        direction="out",
                        chat_id="system:server",
                        message=f"{record.name}: {message}"[:4000],
                        status=status,
                        error=(self.format(record)[:4000] if record.levelno >= logging.ERROR else None),
                        created_at=datetime.utcnow(),
                    )
                )
                db.session.commit()
        except Exception:
            try:
                db.session.rollback()
            except Exception:
                pass
        finally:
            self._local.busy = False

