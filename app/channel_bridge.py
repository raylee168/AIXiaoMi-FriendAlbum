from collections.abc import Callable

ChannelSender = Callable[[dict], str]

_channel_sender: ChannelSender | None = None


def set_channel_sender(sender: ChannelSender | None) -> None:
    global _channel_sender
    _channel_sender = sender


def get_channel_sender() -> ChannelSender | None:
    return _channel_sender
