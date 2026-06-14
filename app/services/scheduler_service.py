from datetime import datetime, timedelta
import logging
import time
from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy.exc import OperationalError
from ..extensions import db
from ..models import MessageLog, ScheduledMessage
from .settings_service import get_settings
from .relay_client import relay_client
from .waha_service import waha_service

logger = logging.getLogger(__name__)


class SchedulerService:
    def __init__(self):
        self.scheduler = BackgroundScheduler()
        self.started = False
        self.app = None

    def start(self, app):
        if self.started:
            return
        self.app = app
        self.scheduler.add_job(
            self.tick,
            "interval",
            seconds=30,
            id="scheduled_messages_tick",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        self.scheduler.start()
        self.started = True

    def _commit_with_retry(self, max_attempts=5, delay=0.25):
        last_error = None
        for attempt in range(1, max_attempts + 1):
            try:
                db.session.commit()
                return
            except OperationalError as exc:
                db.session.rollback()
                last_error = exc
                if "database is locked" not in str(exc).lower() or attempt == max_attempts:
                    raise
                sleep_for = delay * attempt
                logger.warning("SQLite busy/locked in scheduler commit, retrying attempt=%s sleep=%.2fs", attempt, sleep_for)
                time.sleep(sleep_for)
        if last_error:
            raise last_error

    def tick(self):
        with self.app.app_context():
            now = datetime.utcnow()
            try:
                due = ScheduledMessage.query.filter(
                    ScheduledMessage.enabled.is_(True),
                    ScheduledMessage.schedule_time <= now,
                ).all()
            except OperationalError as exc:
                if "database is locked" in str(exc).lower():
                    db.session.rollback()
                    logger.warning("Scheduler skipped one tick because SQLite is locked")
                    return
                raise
            for item in due:
                try:
                    waha_service.send_text(item.target_chat_id, item.message)
                    item.last_sent_at = now
                    item.last_status = "scheduled_sent"
                    item.last_error = None
                    db.session.add(MessageLog(direction="out", chat_id=item.target_chat_id, message=item.message, status="scheduled_sent"))
                    self._advance(item)
                    self._commit_with_retry()
                    relay_client.send_event(
                        get_settings()["relay_flutter_target_device_id"],
                        "scheduled_message_sent",
                        {"scheduled_id": item.id, "chat_id": item.target_chat_id},
                    )
                except Exception as exc:
                    db.session.rollback()
                    item = ScheduledMessage.query.get(item.id)
                    if item:
                        item.last_status = "scheduled_error"
                        item.last_error = str(exc)
                        db.session.add(item)
                    db.session.add(MessageLog(direction="out", chat_id=item.target_chat_id, message=item.message, status="scheduled_error", error=str(exc)))
                    self._commit_with_retry()

    def _advance(self, item):
        if item.repeat == "daily":
            item.schedule_time = item.schedule_time + timedelta(days=1)
            item.last_status = "pending"
        elif item.repeat == "weekly":
            item.schedule_time = item.schedule_time + timedelta(weeks=1)
            item.last_status = "pending"
        elif item.repeat == "monthly":
            item.schedule_time = item.schedule_time + timedelta(days=30)
            item.last_status = "pending"
        else:
            item.enabled = False


scheduler_service = SchedulerService()
