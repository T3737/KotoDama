from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from app.game.npc_profiles import NpcProfileError
from app.orchestration.voice_session_orchestrator import (
    SessionTurnBusy,
    VoiceSessionOrchestrator,
)
from app.orchestration.audio_turn import AudioTurnError
from app.schemas.voice_events import (
    AudioStartEvent,
    AudioStopEvent,
    CLIENT_EVENT_TYPES,
    PingEvent,
    PlayerTextEvent,
    ServerEvent,
    SessionCloseEvent,
    SessionStartEvent,
    parse_client_event,
    server_event,
)


logger = logging.getLogger(__name__)
router = APIRouter(tags=["voice-session"])


@router.websocket("/voice/session")
async def voice_session(websocket: WebSocket) -> None:
    await websocket.accept()
    logger.info("voice_websocket_opened client=%s", websocket.client)
    send_lock = asyncio.Lock()
    session: VoiceSessionOrchestrator | None = None
    turn_tasks: set[asyncio.Task[None]] = set()

    async def send(event: ServerEvent) -> None:
        async with send_lock:
            await websocket.send_json(event.model_dump(mode="json"))

    try:
        while True:
            try:
                message = await asyncio.wait_for(websocket.receive(), timeout=1.0)
            except asyncio.TimeoutError:
                if session is not None:
                    try:
                        await session.check_audio_idle()
                    except AudioTurnError as exc:
                        await send_error(send, session, exc.code, str(exc))
                continue

            if message["type"] == "websocket.disconnect":
                raise WebSocketDisconnect(message.get("code", 1000))
            binary_frame = message.get("bytes")
            if binary_frame is not None:
                if session is None:
                    await send_error(
                        send,
                        None,
                        "session_not_started",
                        "Send session.start and audio.start before binary audio.",
                    )
                    continue
                try:
                    await session.receive_audio_frame(binary_frame)
                except AudioTurnError as exc:
                    await send_error(send, session, exc.code, str(exc))
                continue

            raw_message = message.get("text")
            if raw_message is None:
                await send_error(send, session, "invalid_frame", "Unsupported WebSocket frame.")
                continue
            try:
                raw_event = json.loads(raw_message)
            except json.JSONDecodeError:
                await send_error(send, session, "malformed_json", "Message is not valid JSON.")
                continue

            raw_type = raw_event.get("type") if isinstance(raw_event, dict) else None
            if isinstance(raw_type, str) and raw_type not in CLIENT_EVENT_TYPES:
                await send_error(
                    send,
                    session,
                    "unsupported_event",
                    f"Unsupported event type: {raw_type}",
                    raw_event.get("event_id", "") if isinstance(raw_event, dict) else "",
                )
                continue
            try:
                event = parse_client_event(raw_event)
            except ValidationError as exc:
                await send_error(
                    send,
                    session,
                    "invalid_event",
                    "Event validation failed.",
                    details=exc.errors(include_url=False, include_context=False),
                )
                continue

            if isinstance(event, PingEvent):
                await send(server_event("pong", event.session_id, in_reply_to=event.event_id))
                continue

            if session is None:
                if not isinstance(event, SessionStartEvent):
                    await send_error(
                        send,
                        None,
                        "session_not_started",
                        "Send session.start before other session events.",
                        event.event_id,
                        session_id=event.session_id,
                    )
                    continue
                session = VoiceSessionOrchestrator(
                    websocket.app.state.npc_orchestrator,
                    websocket.app.state.ollama_client,
                    send,
                    websocket.app.state.stt_service_factory,
                )
                try:
                    await session.open(event)
                except NpcProfileError as exc:
                    await send_error(
                        send,
                        session,
                        "unknown_npc",
                        str(exc),
                        event.event_id,
                        fatal=True,
                    )
                    await websocket.close(code=1008)
                    return
                continue

            if event.session_id != session.session_id:
                await send_error(
                    send,
                    session,
                    "session_mismatch",
                    "Event session_id does not match the active session.",
                    event.event_id,
                )
            elif isinstance(event, SessionStartEvent):
                await send_error(
                    send, session, "session_already_started", "Session is already active.", event.event_id
                )
            elif isinstance(event, SessionCloseEvent):
                await session.close()
                await websocket.close(code=1000)
                return
            elif isinstance(event, PlayerTextEvent):
                try:
                    session.reserve_player_turn()
                except SessionTurnBusy as exc:
                    await send_error(send, session, "turn_in_progress", str(exc), event.event_id)
                    continue
                logger.info(
                    "player_turn_accepted session_id=%s npc_id=%s event_id=%s",
                    session.session_id,
                    session.npc_id,
                    event.event_id,
                )
                task = asyncio.create_task(session.process_player_text(event))
                turn_tasks.add(task)
                task.add_done_callback(turn_tasks.discard)
            elif isinstance(event, AudioStartEvent):
                try:
                    await session.start_audio(event)
                except AudioTurnError as exc:
                    await send_error(send, session, exc.code, str(exc), event.event_id)
            elif isinstance(event, AudioStopEvent):
                try:
                    await session.stop_audio(event)
                except AudioTurnError as exc:
                    await send_error(send, session, exc.code, str(exc), event.event_id)
    except WebSocketDisconnect:
        logger.info("voice_websocket_disconnected session_id=%s", session.session_id if session else "")
    finally:
        for task in turn_tasks:
            task.cancel()
        if turn_tasks:
            await asyncio.gather(*turn_tasks, return_exceptions=True)
        if session is not None:
            await session.close()


async def send_error(
    send,
    session: VoiceSessionOrchestrator | None,
    code: str,
    message: str,
    in_reply_to: str = "",
    *,
    fatal: bool = False,
    details=None,
    session_id: str = "",
) -> None:
    active_session_id = session.session_id if session is not None else session_id
    logger.warning("voice_protocol_error session_id=%s code=%s", active_session_id, code)
    payload = {
        "code": code,
        "message": message,
        "fatal": fatal,
        "in_reply_to": in_reply_to,
    }
    if details is not None:
        payload["details"] = details
    await send(server_event("error", active_session_id, **payload))
