from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from ..extensions import db
from ..models import MessageLog, ScheduledMessage
from .settings_service import get_settings
from .relay_client import relay_client
from .waha_service import waha_service


class SchedulerService:
    def __init__(self):
        self.scheduler = BackgroundScheduler()
        self.started = False
        self.app = None

    def start(self, app):
        if self.started:
            return
        self.app = app
        self.scheduler.add_job(self.tick, "interval", seconds=30, id="scheduled_messages_tick", replace_existing=True)
        self.scheduler.start()
        self.started = True

    def tick(self):
        with self.app.app_context():
            now = datetime.utcnow()
            due = ScheduledMessage.query.filter(
                ScheduledMessage.enabled.is_(True),
                ScheduledMessage.schedule_time <= now,
            ).all()
            for item in due:
                try:
                    waha_service.send_text(item.target_chat_id, item.message)
                    item.last_sent_at = now
                    db.session.add(MessageLog(direction="out", chat_id=item.target_chat_id, message=item.message, status="scheduled_sent"))
                    self._advance(item)
                    db.session.commit()
                    relay_client.send_event(
                        get_settings()["relay_flutter_target_device_id"],
                        "scheduled_message_sent",
                        {"scheduled_id": item.id, "chat_id": item.target_chat_id},
                    )
                except Exception as exc:
                    db.session.rollback()
                    db.session.add(MessageLog(direction="out", chat_id=item.target_chat_id, message=item.message, status="error", error=str(exc)))
                    db.session.commit()

    def _advance(self, item):
        if item.repeat == "daily":
            item.schedule_time = item.schedule_time + timedelta(days=1)
        elif item.repeat == "weekly":
            item.schedule_time = item.schedule_time + timedelta(weeks=1)
        elif item.repeat == "monthly":
            item.schedule_time = item.schedule_time + timedelta(days=30)
        else:
            item.enabled = False


scheduler_service = SchedulerService()
