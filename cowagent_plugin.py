import json
import os
import sys
import threading
import time
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent
PLUGIN_DIR_TEXT = str(PLUGIN_DIR)
LOCAL_APP_DIR = PLUGIN_DIR / "app"
if PLUGIN_DIR_TEXT not in sys.path:
    sys.path.insert(0, PLUGIN_DIR_TEXT)

existing_app = sys.modules.get("app")
if existing_app is not None:
    existing_file = Path(getattr(existing_app, "__file__", "") or "")
    is_local_app = str(existing_file.resolve()).startswith(str(LOCAL_APP_DIR.resolve())) if existing_file else False
    if not is_local_app:
        sys.modules.setdefault("_cowagent_root_app", existing_app)
        sys.modules.pop("app", None)

import plugins
from bridge.context import Context
from bridge.reply import Reply, ReplyType
from common.log import logger
from plugins import Event, EventAction, EventContext, Plugin

from app.channel_bridge import set_channel_sender
from app.db.session import SessionLocal
from app.services import cleanup_files, generate_albums, make_decisions, preprocess_photos, push_results, scan_events


@plugins.register(
    name="moments_album",
    desire_priority=10,
    enabled=False,
    desc="朋友圈智能相册插件",
    version="0.2.0",
    author="AIXiaoMi",
)
class MomentsAlbum(Plugin):
    def __init__(self):
        super().__init__()
        self.config = super().load_config() or self._load_config_template()
        self._stop = threading.Event()
        self.handlers[Event.ON_HANDLE_CONTEXT] = self.on_handle_context
        set_channel_sender(self._send_message)
        if self.config.get("scheduler_enabled", True):
            thread = threading.Thread(target=self._scheduler_loop, name="moments_album_scheduler", daemon=True)
            thread.start()
        logger.info("[moments_album] plugin initialized")

    def on_handle_context(self, e_context: EventContext):
        context = e_context["context"]
        if getattr(context, "content", "") not in {"$album status", "#album status"}:
            return
        e_context["reply"] = Reply(ReplyType.TEXT, "朋友圈智能相册插件运行中。")
        e_context.action = EventAction.BREAK_PASS

    def _scheduler_loop(self):
        jobs = [
            ("events", int(self.config.get("scan_events_seconds", 10)), scan_events),
            ("preprocess", int(self.config.get("preprocess_seconds", 10)), preprocess_photos),
            ("decision", int(self.config.get("decision_seconds", 60)), make_decisions),
            ("generation", int(self.config.get("generation_seconds", 10)), generate_albums),
            ("push", int(self.config.get("push_seconds", 10)), push_results),
            ("cleanup", int(self.config.get("cleanup_seconds", 600)), cleanup_files),
        ]
        next_run = {name: 0.0 for name, _, _ in jobs}
        while not self._stop.is_set():
            now = time.monotonic()
            for name, seconds, func in jobs:
                if next_run[name] > now:
                    continue
                self._run_job(name, func)
                next_run[name] = now + seconds
            self._stop.wait(1)

    def _run_job(self, name, func):
        db = SessionLocal()
        try:
            result = func(db)
            logger.debug(f"[moments_album] job {name} result: {result}")
        except Exception as exc:
            logger.error(f"[moments_album] job {name} failed: {exc}")
        finally:
            db.close()

    def _send_message(self, payload: dict) -> str:
        channel = self._get_channel(payload.get("channel_type"))
        if not channel:
            return self._fallback_log(payload)
        receiver = payload.get("receiver") or payload.get("user_id")
        context = Context()
        context["receiver"] = receiver
        context["isgroup"] = False
        message = payload.get("message") or {}
        image_paths = message.get("images") or []
        text = message.get("text") or ""
        for image_path in image_paths:
            channel.send(Reply(ReplyType.IMAGE, image_path), context)
        if text:
            channel.send(Reply(ReplyType.TEXT, text), context)
        return f"cowagent_msg_{int(time.time() * 1000)}"

    def _get_channel(self, channel_type: str | None):
        try:
            get_channel_manager = self._get_channel_manager()
            if not get_channel_manager:
                return None
            manager = get_channel_manager()
            if not manager:
                return None
            if channel_type:
                return manager.get_channel(channel_type)
            return manager.channel
        except Exception as exc:
            logger.warning(f"[moments_album] CowAgent channel unavailable: {exc}")
            return None

    def _get_channel_manager(self):
        import __main__

        get_channel_manager = getattr(__main__, "get_channel_manager", None)
        if get_channel_manager:
            return get_channel_manager
        root_app = sys.modules.get("_cowagent_root_app")
        return getattr(root_app, "get_channel_manager", None)

    def _fallback_log(self, payload: dict) -> str:
        log_path = Path(self.config.get("fallback_channel_log_path", "/data/smart-album/logs/moments_album_channel.jsonl"))
        log_path.parent.mkdir(parents=True, exist_ok=True)
        message_id = f"mock_msg_{int(time.time() * 1000)}"
        row = {"message_id": message_id, "payload": payload}
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        return message_id

    def _load_config_template(self):
        config_path = Path(os.path.dirname(__file__)) / "config.json.template"
        if config_path.exists():
            return json.loads(config_path.read_text(encoding="utf-8"))
        return {}

    def get_help_text(self, **kwargs):
        return "$album status - 查看朋友圈智能相册插件状态"
