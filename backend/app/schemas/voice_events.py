from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class EventModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SessionStartPayload(EventModel):
    npc_id: str = Field(min_length=1)
    scene_context: str | None = None
    level_id: str = "level_01"
    player_state: dict[str, Any] = Field(default_factory=dict)
    npc_state: dict[str, Any] = Field(default_factory=dict)
    visible_world_facts: list[dict[str, Any]] = Field(default_factory=list)


class PlayerTextPayload(EventModel):
    text: str = Field(min_length=1)


class EmptyPayload(EventModel):
    pass


class ClientEventBase(EventModel):
    session_id: str = Field(min_length=1)
    event_id: str = Field(min_length=1)
    timestamp: datetime


class SessionStartEvent(ClientEventBase):
    type: Literal["session.start"]
    payload: SessionStartPayload


class PlayerTextEvent(ClientEventBase):
    type: Literal["player.text"]
    payload: PlayerTextPayload


class SessionCloseEvent(ClientEventBase):
    type: Literal["session.close"]
    payload: EmptyPayload = Field(default_factory=EmptyPayload)


class PingEvent(ClientEventBase):
    type: Literal["ping"]
    payload: dict[str, Any] = Field(default_factory=dict)


ClientEvent = SessionStartEvent | PlayerTextEvent | SessionCloseEvent | PingEvent
CLIENT_EVENT_TYPES = {"session.start", "player.text", "session.close", "ping"}
_client_event_adapter = TypeAdapter(ClientEvent)


def parse_client_event(data: Any) -> ClientEvent:
    return _client_event_adapter.validate_python(data)


class ServerEvent(EventModel):
    type: Literal[
        "session.ready",
        "state.changed",
        "npc.text.delta",
        "npc.text.final",
        "error",
        "pong",
    ]
    session_id: str
    event_id: str = Field(default_factory=lambda: str(uuid4()))
    timestamp: datetime = Field(default_factory=utc_now)
    payload: dict[str, Any] = Field(default_factory=dict)


def server_event(event_type: str, session_id: str, **payload: Any) -> ServerEvent:
    return ServerEvent(type=event_type, session_id=session_id, payload=payload)
