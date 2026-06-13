import asyncio
import json
import logging
import threading
import time
import websockets
from .settings_service import get_settings

logger = logging.getLogger(__name__)


class RelayClient:
    def __init__(self):
        self.app = None
        self.loop = None
        self.ws = None
        self.thread = None
        self.running = False
        self.queue = None

    def configure_from_db(self, app):
        self.app = app

    def start(self):
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()

    def _run_loop(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.queue = asyncio.Queue()
        self.loop.run_until_complete(self._runner())

    async def _runner(self):
        while self.running:
            try:
                with self.app.app_context():
                    settings = get_settings()
                await self._connect(settings)
            except Exception as exc:
                logger.warning("Relay offline/reconnect later: %s", exc)
                await asyncio.sleep(5)

    async def _connect(self, settings):
        server_url = settings.get("relay_server_url")
        if not server_url:
            await asyncio.sleep(5)
            return
        async with websockets.connect(server_url, ping_interval=20, ping_timeout=20) as ws:
            self.ws = ws
            register = {
                "type": "register",
                "role": settings.get("relay_backend_role", "pc"),
                "device_id": settings.get("relay_backend_device_id", "backend-waha-ai"),
                "phone_id": settings.get("relay_flutter_target_device_id", "phone-aris"),
                "token": settings.get("relay_token", ""),
            }
            await ws.send(json.dumps(register))
            consumer = asyncio.create_task(self._consume(ws))
            producer = asyncio.create_task(self._produce(ws))
            done, pending = await asyncio.wait([consumer, producer], return_when=asyncio.FIRST_EXCEPTION)
            for task in pending:
                task.cancel()
            for task in done:
                task.result()

    async def _consume(self, ws):
        async for message in ws:
            logger.info("Relay message: %s", message)

    async def _produce(self, ws):
        while True:
            item = await self.queue.get()
            await ws.send(json.dumps(item))

    def send_event(self, target_device_id, event, data):
        if not self.running or not self.loop or not self.queue:
            return False
        with self.app.app_context():
            settings = get_settings()
        message = {
            "type": "status",
            "target": target_device_id or settings.get("relay_flutter_target_device_id", "phone-aris"),
            "token": settings.get("relay_token", ""),
            "event": event,
            "data": data,
        }
        try:
            asyncio.run_coroutine_threadsafe(self.queue.put(message), self.loop)
            return True
        except Exception as exc:
            logger.warning("Failed queue relay event: %s", exc)
            return False


relay_client = RelayClient()
