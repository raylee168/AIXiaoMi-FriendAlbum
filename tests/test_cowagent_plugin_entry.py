import importlib
import __main__
import sys
import types


def test_cowagent_plugin_entry_imports_with_stub_modules(monkeypatch):
    registered = {}

    plugins_mod = types.ModuleType("plugins")

    class Plugin:
        def __init__(self):
            self.handlers = {}

        def load_config(self):
            return {"scheduler_enabled": False}

    class Event:
        ON_HANDLE_CONTEXT = "ON_HANDLE_CONTEXT"

    class EventAction:
        BREAK_PASS = "BREAK_PASS"

    class EventContext:
        pass

    def register(**kwargs):
        def wrapper(cls):
            registered["kwargs"] = kwargs
            registered["class"] = cls
            return cls

        return wrapper

    plugins_mod.Plugin = Plugin
    plugins_mod.Event = Event
    plugins_mod.EventAction = EventAction
    plugins_mod.EventContext = EventContext
    plugins_mod.register = register
    monkeypatch.setitem(sys.modules, "plugins", plugins_mod)

    bridge_context = types.ModuleType("bridge.context")

    class Context:
        def __init__(self):
            self.kwargs = {}

        def __setitem__(self, key, value):
            self.kwargs[key] = value

    bridge_context.Context = Context
    monkeypatch.setitem(sys.modules, "bridge.context", bridge_context)

    bridge_reply = types.ModuleType("bridge.reply")

    class ReplyType:
        TEXT = "TEXT"
        IMAGE = "IMAGE"

    class Reply:
        def __init__(self, type=None, content=None):
            self.type = type
            self.content = content

    bridge_reply.Reply = Reply
    bridge_reply.ReplyType = ReplyType
    monkeypatch.setitem(sys.modules, "bridge.reply", bridge_reply)

    common_log = types.ModuleType("common.log")

    class Logger:
        def info(self, *args, **kwargs):
            pass

        def debug(self, *args, **kwargs):
            pass

        def warning(self, *args, **kwargs):
            pass

        def error(self, *args, **kwargs):
            pass

    common_log.logger = Logger()
    monkeypatch.setitem(sys.modules, "common.log", common_log)

    module = importlib.import_module("cowagent_plugin")
    plugin = module.MomentsAlbum()

    assert registered["kwargs"]["name"] == "moments_album"
    assert plugin.config["scheduler_enabled"] is False


def test_cowagent_plugin_reuses_main_channel(monkeypatch):
    sent = []

    class Channel:
        def send(self, reply, context):
            sent.append((reply.type, reply.content, context.kwargs["receiver"]))

    class Manager:
        channel = Channel()

        def get_channel(self, channel_type):
            return self.channel

    monkeypatch.setattr(__main__, "get_channel_manager", lambda: Manager(), raising=False)
    module = importlib.import_module("cowagent_plugin")
    plugin = module.MomentsAlbum()

    message_id = plugin._send_message(
        {
            "user_id": "user_1",
            "channel_type": "gewechat",
            "message": {"images": ["/tmp/a.jpg"], "text": "done"},
        }
    )

    assert message_id.startswith("cowagent_msg_")
    assert sent == [("IMAGE", "/tmp/a.jpg", "user_1"), ("TEXT", "done", "user_1")]


def test_cowagent_plugin_falls_back_to_primary_channel(monkeypatch):
    sent = []

    class Channel:
        def send(self, reply, context):
            sent.append((reply.type, reply.content, context.kwargs["receiver"]))

    class Manager:
        channel = Channel()

        def get_channel(self, channel_type):
            return None

    monkeypatch.setattr(__main__, "get_channel_manager", lambda: Manager(), raising=False)
    module = importlib.import_module("cowagent_plugin")
    plugin = module.MomentsAlbum()

    message_id = plugin._send_message(
        {
            "user_id": "user_2",
            "channel_type": "mock",
            "message": {"text": "fallback"},
        }
    )

    assert message_id.startswith("cowagent_msg_")
    assert sent == [("TEXT", "fallback", "user_2")]
