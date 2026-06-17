import json
from contextlib import asynccontextmanager
from unittest.mock import MagicMock

from aio_pika.abc import AbstractIncomingMessage

from app.events import ORDER_PAID


@asynccontextmanager
async def _noop_process(*args, **kwargs):
    yield


def make_incoming_message(payload: dict, routing_key: str) -> MagicMock:
    message = MagicMock(spec=AbstractIncomingMessage)
    message.body = json.dumps(payload).encode("utf-8")
    message.routing_key = routing_key
    message.process = MagicMock(side_effect=_noop_process)
    return message


def make_invalid_json_message(routing_key: str = ORDER_PAID) -> MagicMock:
    message = MagicMock(spec=AbstractIncomingMessage)
    message.body = b"{not-json"
    message.routing_key = routing_key
    message.process = MagicMock(side_effect=_noop_process)
    return message
