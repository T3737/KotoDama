from __future__ import annotations

import logging
import os
import tempfile
from collections.abc import Awaitable, Callable
from pathlib import Path
from time import perf_counter

from fastapi.concurrency import run_in_threadpool

from app.game.npc_profiles import NpcProfileError, load_npc_profile
from app.llm.ollama_client import OllamaClient, OllamaError
from app.orchestration.conversation_state import (
    ConversationState,
    ConversationStateMachine,
)
from app.orchestration.audio_turn import AudioTurnBuffer, AudioTurnError
from app.orchestration.npc_orchestrator import NpcOrchestrator, NpcTurn
from app.schemas.voice_events import (
    AudioStartEvent,
    AudioStopEvent,
    PlayerTextEvent,
    ServerEvent,
    SessionStartEvent,
    server_event,
)
from app.speech.stt_service import (
    STTError,
    STTUnavailableError,
    SpeechToTextService,
    create_stt_service,
)


logger = logging.getLogger(__name__)
EventSender = Callable[[ServerEvent], Awaitable[None]]
STTFactory = Callable[[], SpeechToTextService]

DEFAULT_MAX_AUDIO_SECONDS = 20.0
DEFAULT_MAX_AUDIO_BYTES = 4 * 1024 * 1024
DEFAULT_AUDIO_IDLE_SECONDS = 3.0
MIN_AUDIO_BYTES = 320


class SessionTurnBusy(RuntimeError):
    pass


class VoiceSessionOrchestrator:
    """Owns one transport session while delegating dialogue to NpcOrchestrator."""

    def __init__(
        self,
        npc_orchestrator: NpcOrchestrator,
        ollama_client: OllamaClient,
        send_event: EventSender,
        stt_factory: STTFactory = create_stt_service,
    ) -> None:
        self._npc_orchestrator = npc_orchestrator
        self._ollama_client = ollama_client
        self._send_event = send_event
        self._stt_factory = stt_factory
        self._state = ConversationStateMachine()
        self._start: SessionStartEvent | None = None
        self._turn_active = False
        self._audio_turn: AudioTurnBuffer | None = None
        self._auto_send_transcript = False
        self._max_audio_seconds = float(
            os.getenv("VOICE_MAX_TURN_SECONDS", str(DEFAULT_MAX_AUDIO_SECONDS))
        )
        self._max_audio_bytes = int(
            os.getenv("VOICE_MAX_AUDIO_BYTES", str(DEFAULT_MAX_AUDIO_BYTES))
        )
        self._audio_idle_seconds = float(
            os.getenv("VOICE_AUDIO_IDLE_SECONDS", str(DEFAULT_AUDIO_IDLE_SECONDS))
        )

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

    async def start_audio(self, event: AudioStartEvent) -> None:
        if self._start is None or self.state != ConversationState.READY:
            raise AudioTurnError(
                "invalid_event_order", "audio.start is accepted only while the session is READY."
            )
        if self._turn_active or self._audio_turn is not None:
            raise AudioTurnError("audio_turn_active", "An audio turn is already active.")
        self._audio_turn = AudioTurnBuffer(
            sample_rate=event.payload.sample_rate,
            channels=event.payload.channels,
            encoding=event.payload.encoding,
            max_duration_seconds=self._max_audio_seconds,
            max_bytes=self._max_audio_bytes,
        )
        self._auto_send_transcript = event.payload.auto_send_transcript
        self._turn_active = True
        await self._transition(ConversationState.LISTENING)
        await self._send_event(
            server_event(
                "audio.ready",
                self.session_id,
                sample_rate=event.payload.sample_rate,
                channels=event.payload.channels,
                encoding=event.payload.encoding,
                max_duration_ms=round(self._max_audio_seconds * 1000),
                max_bytes=self._max_audio_bytes,
                in_reply_to=event.event_id,
            )
        )

    async def receive_audio_frame(self, frame: bytes) -> None:
        if self.state != ConversationState.LISTENING or self._audio_turn is None:
            raise AudioTurnError(
                "binary_out_of_order", "Binary audio is accepted only after audio.start."
            )
        try:
            self._audio_turn.append(frame)
        except AudioTurnError:
            self._clear_audio_turn()
            await self._transition(ConversationState.READY)
            raise

    async def stop_audio(self, event: AudioStopEvent) -> None:
        if self.state != ConversationState.LISTENING or self._audio_turn is None:
            raise AudioTurnError(
                "invalid_event_order", "audio.stop is accepted only for an active audio turn."
            )

        audio_turn = self._audio_turn
        self._audio_turn = None
        await self._transition(ConversationState.TRANSCRIBING)
        await self._send_event(
            server_event(
                "audio.received",
                self.session_id,
                received_bytes=audio_turn.received_bytes,
                duration_ms=audio_turn.duration_ms,
                reason=event.payload.reason,
                in_reply_to=event.event_id,
            )
        )
        logger.info(
            "voice_audio_received session_id=%s bytes=%d duration_ms=%d sample_rate=%d",
            self.session_id,
            audio_turn.received_bytes,
            audio_turn.duration_ms,
            audio_turn.sample_rate,
        )

        if event.payload.reason == "cancelled":
            audio_turn.clear()
            self._clear_audio_turn()
            await self._transition(ConversationState.READY)
            return

        if audio_turn.received_bytes < MIN_AUDIO_BYTES:
            audio_turn.clear()
            await self._recover_audio_error(
                "audio_too_short",
                "No usable microphone audio was received.",
                event.event_id,
            )
            return

        temporary_path: Path | None = None
        transcription_started = perf_counter()
        try:
            with tempfile.NamedTemporaryFile(mode="wb", suffix=".wav", delete=False) as wav_file:
                temporary_path = Path(wav_file.name)
                wav_file.write(audio_turn.to_wav_bytes())

            transcript = (
                await run_in_threadpool(self._stt_factory().transcribe, temporary_path)
            ).strip()
            if not transcript:
                raise STTError("Speech transcription returned an empty transcript.")
            transcription_ms = round((perf_counter() - transcription_started) * 1000)
            await self._send_event(
                server_event(
                    "transcript.final",
                    self.session_id,
                    text=transcript,
                    language="en",
                    duration_ms=audio_turn.duration_ms,
                    received_bytes=audio_turn.received_bytes,
                    transcription_ms=transcription_ms,
                    auto_sent=self._auto_send_transcript,
                    in_reply_to=event.event_id,
                )
            )
            logger.info(
                "voice_transcription_completed session_id=%s bytes=%d transcription_ms=%d",
                self.session_id,
                audio_turn.received_bytes,
                transcription_ms,
            )
            audio_turn.clear()
            if self._auto_send_transcript:
                player_event = PlayerTextEvent(
                    type="player.text",
                    session_id=self.session_id,
                    event_id=event.event_id,
                    timestamp=event.timestamp,
                    payload={"text": transcript},
                )
                await self.process_player_text(player_event)
                self._auto_send_transcript = False
            else:
                self._turn_active = False
                await self._transition(ConversationState.READY)
        except STTUnavailableError:
            await self._recover_audio_error(
                "stt_unavailable", "Local speech model is not ready.", event.event_id
            )
        except STTError as exc:
            await self._recover_audio_error("transcription_failed", str(exc), event.event_id)
        except Exception:
            logger.exception("voice_transcription_error session_id=%s", self.session_id)
            await self._recover_audio_error(
                "transcription_failed", "Local speech transcription failed.", event.event_id
            )
        finally:
            audio_turn.clear()
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

    async def check_audio_idle(self) -> None:
        if self.state != ConversationState.LISTENING or self._audio_turn is None:
            return
        from time import monotonic

        if monotonic() - self._audio_turn.last_frame_at <= self._audio_idle_seconds:
            return
        self._clear_audio_turn()
        await self._transition(ConversationState.READY)
        raise AudioTurnError(
            "audio_idle_timeout", "No microphone audio arrived before the listening timeout."
        )

    async def close(self) -> None:
        self._clear_audio_turn()
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

    async def _recover_audio_error(self, code: str, message: str, in_reply_to: str) -> None:
        self._clear_audio_turn()
        await self._send_event(
            server_event(
                "error",
                self.session_id,
                code=code,
                message=message,
                fatal=False,
                in_reply_to=in_reply_to,
            )
        )
        if self.state in {ConversationState.LISTENING, ConversationState.TRANSCRIBING}:
            await self._transition(ConversationState.READY)

    def _clear_audio_turn(self) -> None:
        if self._audio_turn is not None:
            self._audio_turn.clear()
        self._audio_turn = None
        self._turn_active = False
        self._auto_send_transcript = False

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
