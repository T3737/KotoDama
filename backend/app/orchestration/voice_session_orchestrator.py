from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from time import perf_counter

from app.game.npc_profiles import NpcProfileError, load_npc_profile
from app.llm.ollama_client import OllamaClient, OllamaError
from app.orchestration.conversation_state import (
    ConversationState,
    ConversationStateMachine,
)
from app.orchestration.npc_orchestrator import NpcOrchestrator, NpcTurn
from app.schemas.voice_events import PlayerTextEvent, ServerEvent, SessionStartEvent, server_event


logger = logging.getLogger(__name__)
EventSender = Callable[[ServerEvent], Awaitable[None]]


class SessionTurnBusy(RuntimeError):
    pass


class VoiceSessionOrchestrator:
    """Owns one transport session while delegating dialogue to NpcOrchestrator."""

    def __init__(
        self,
        npc_orchestrator: NpcOrchestrator,
        ollama_client: OllamaClient,
        send_event: EventSender,
    ) -> None:
        self._npc_orchestrator = npc_orchestrator
        self._ollama_client = ollama_client
        self._send_event = send_event
        self._state = ConversationStateMachine()
        self._start: SessionStartEvent | None = None
        self._turn_active = False

    @property
    def session_id(self) -> str:
        return self._start.session_id if self._start else ""

    @property
    def npc_id(self) -> str:
        return self._start.payload.npc_id if self._start else ""

    @property
    def state(self) -> ConversationState:
        return self._state.state

    async def open(self, event: SessionStartEvent) -> None:
        # Validate the profile before committing the connection to a session.
        self._start = event
        load_npc_profile(event.payload.npc_id)
        self._state.transition(ConversationState.CONNECTING)
        self._state.transition(ConversationState.READY)
        logger.info(
            "voice_session_created session_id=%s npc_id=%s",
            self.session_id,
            self.npc_id,
        )
        await self._send_event(
            server_event(
                "session.ready",
                self.session_id,
                npc_id=self.npc_id,
                state=self.state.value,
            )
        )
        await self._send_state_changed(ConversationState.CONNECTING, ConversationState.READY)

    def reserve_player_turn(self) -> None:
        if self._start is None or self.state != ConversationState.READY:
            raise SessionTurnBusy("The session is not ready for player text.")
        if self._turn_active:
            raise SessionTurnBusy("A player turn is already being generated.")
        self._turn_active = True

    async def process_player_text(self, event: PlayerTextEvent) -> None:
        received_at = perf_counter()
        try:
            await self._transition(ConversationState.GENERATING)
            generation_started = perf_counter()
            logger.info(
                "npc_generation_started session_id=%s npc_id=%s event_id=%s",
                self.session_id,
                self.npc_id,
                event.event_id,
            )
            start = self._start
            assert start is not None
            result = await self._npc_orchestrator.respond(
                NpcTurn(
                    session_id=self.session_id,
                    npc_id=self.npc_id,
                    player_message=event.payload.text.strip(),
                    level_id=start.payload.level_id,
                    player_state=start.payload.player_state,
                    npc_state=start.payload.npc_state,
                    visible_world_facts=start.payload.visible_world_facts,
                    scene_context=start.payload.scene_context,
                ),
                self._ollama_client,
            )
            generation_ms = (perf_counter() - generation_started) * 1000
            await self._send_event(
                server_event(
                    "npc.text.final",
                    self.session_id,
                    text=result.dialogue,
                    npc_id=result.npc_id,
                    emotion=result.emotion,
                    memory_updates=result.memory_updates,
                    world_updates=result.world_updates,
                    teaching_data=result.teaching_data,
                    in_reply_to=event.event_id,
                )
            )
            logger.info(
                "npc_generation_completed session_id=%s npc_id=%s generation_ms=%.1f total_ms=%.1f",
                self.session_id,
                self.npc_id,
                generation_ms,
                (perf_counter() - received_at) * 1000,
            )
        except (NpcProfileError, OllamaError) as exc:
            logger.warning(
                "voice_turn_error session_id=%s code=generation_failed error=%s",
                self.session_id,
                exc,
            )
            await self._send_event(
                server_event(
                    "error",
                    self.session_id,
                    code="generation_failed",
                    message=str(exc),
                    fatal=False,
                    in_reply_to=event.event_id,
                )
            )
        except Exception:
            logger.exception(
                "voice_turn_error session_id=%s code=internal_error", self.session_id
            )
            await self._send_event(
                server_event(
                    "error",
                    self.session_id,
                    code="internal_error",
                    message="The NPC turn failed unexpectedly.",
                    fatal=False,
                    in_reply_to=event.event_id,
                )
            )
        finally:
            self._turn_active = False
            if self.state == ConversationState.GENERATING:
                await self._transition(ConversationState.READY)

    async def close(self) -> None:
        if self.state != ConversationState.DISCONNECTED:
            previous, current = self._state.transition(ConversationState.DISCONNECTED)
            logger.info(
                "voice_session_disconnected session_id=%s npc_id=%s",
                self.session_id,
                self.npc_id,
            )
            # A closed socket cannot always receive this, but explicit session.close can.
            try:
                await self._send_state_changed(previous, current)
            except RuntimeError:
                pass

    async def _transition(self, state: ConversationState) -> None:
        previous, current = self._state.transition(state)
        logger.info(
            "voice_state_transition session_id=%s from_state=%s to_state=%s",
            self.session_id,
            previous.value,
            current.value,
        )
        await self._send_state_changed(previous, current)

    async def _send_state_changed(
        self, previous: ConversationState, current: ConversationState
    ) -> None:
        await self._send_event(
            server_event(
                "state.changed",
                self.session_id,
                previous=previous.value,
                state=current.value,
            )
        )
