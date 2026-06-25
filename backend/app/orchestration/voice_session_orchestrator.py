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
from app.orchestration.vad_turn import VADOutcome, VADTurnDetector
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
    STTMalformedAudioError,
    STTNoSpeechError,
    STTUnavailableError,
    SpeechToTextService,
    create_stt_service,
)
from app.speech.vad_service import (
    VADService,
    VADUnavailableError,
    create_vad_service,
)


logger = logging.getLogger(__name__)
EventSender = Callable[[ServerEvent], Awaitable[None]]
STTFactory = Callable[[], SpeechToTextService]
VADFactory = Callable[[], VADService]

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
        vad_factory: VADFactory = create_vad_service,
    ) -> None:
        self._npc_orchestrator = npc_orchestrator
        self._ollama_client = ollama_client
        self._send_event = send_event
        self._stt_factory = stt_factory
        self._vad_factory = vad_factory
        self._state = ConversationStateMachine()
        self._start: SessionStartEvent | None = None
        self._turn_active = False
        self._audio_turn: AudioTurnBuffer | None = None
        self._vad_detector: VADTurnDetector | None = None
        self._discard_late_audio = False
        self._late_frame_logged = False
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
        vad_service = self._vad_factory()
        vad_readiness = vad_service.readiness()
        vad_config = vad_service.config
        turn_seconds = min(self._max_audio_seconds, vad_config.max_turn_ms / 1000)
        format_max_bytes = int(
            event.payload.sample_rate
            * event.payload.channels
            * 2
            * turn_seconds
        )
        effective_max_bytes = min(self._max_audio_bytes, format_max_bytes)
        self._audio_turn = AudioTurnBuffer(
            sample_rate=event.payload.sample_rate,
            channels=event.payload.channels,
            encoding=event.payload.encoding,
            max_duration_seconds=turn_seconds,
            max_bytes=effective_max_bytes,
        )
        self._vad_detector = None
        if vad_config.enabled:
            try:
                self._vad_detector = VADTurnDetector(
                    vad_config,
                    vad_service.create_stream(),
                    event.payload.sample_rate,
                )
                vad_readiness = vad_service.readiness()
            except VADUnavailableError:
                vad_readiness = vad_service.readiness()
        self._discard_late_audio = False
        self._late_frame_logged = False
        self._turn_active = True
        await self._transition(ConversationState.LISTENING)
        await self._send_event(
            server_event(
                "audio.ready",
                self.session_id,
                sample_rate=event.payload.sample_rate,
                channels=event.payload.channels,
                encoding=event.payload.encoding,
                max_duration_ms=round(turn_seconds * 1000),
                max_bytes=effective_max_bytes,
                vad_enabled=self._vad_detector is not None,
                vad_state=vad_readiness.get("state", "error"),
                vad_backend=vad_readiness.get("backend", "unknown"),
                vad_warning=(
                    ""
                    if self._vad_detector is not None
                    else "vad_unavailable"
                ),
                in_reply_to=event.event_id,
            )
        )

    async def receive_audio_frame(self, frame: bytes) -> None:
        if self.state != ConversationState.LISTENING or self._audio_turn is None:
            if self._discard_late_audio:
                if not self._late_frame_logged:
                    logger.info("vad_late_audio_discarded session_id=%s", self.session_id)
                    self._late_frame_logged = True
                return
            raise AudioTurnError(
                "binary_out_of_order", "Binary audio is accepted only after audio.start."
            )
        try:
            self._audio_turn.append(frame)
        except AudioTurnError as exc:
            if exc.code == "audio_too_large" and self._vad_detector is not None:
                metrics = self._vad_detector.metrics
                outcome = VADOutcome(
                    "maximum_turn_duration",
                    self._vad_detector.speech_started,
                    self._vad_detector.speech_duration_ms,
                    int(metrics.get("silence_duration_ms") or 0),
                )
                if outcome.should_transcribe:
                    await self._send_event(
                        server_event(
                            "vad.speech_ended",
                            self.session_id,
                            speech_duration_ms=outcome.speech_duration_ms,
                            silence_duration_ms=outcome.silence_duration_ms,
                            reason=outcome.reason,
                        )
                    )
                await self._auto_finish_audio(outcome)
                return
            self._clear_audio_turn()
            await self._transition(ConversationState.READY)
            raise

        if self._vad_detector is None:
            return
        try:
            signals, outcome = self._vad_detector.process(frame)
        except VADUnavailableError as exc:
            self._vad_detector = None
            await self._send_event(
                server_event(
                    "error",
                    self.session_id,
                    code="vad_unavailable",
                    message=str(exc),
                    fatal=False,
                )
            )
            return
        for signal in signals:
            await self._send_event(
                server_event(signal.event_type, self.session_id, **signal.payload)
            )
        if outcome is not None:
            await self._auto_finish_audio(outcome)

    async def stop_audio(self, event: AudioStopEvent) -> None:
        if self.state != ConversationState.LISTENING or self._audio_turn is None:
            raise AudioTurnError(
                "invalid_event_order", "audio.stop is accepted only for an active audio turn."
            )

        outcome = self._vad_detector.manual_outcome() if self._vad_detector else None
        await self._finish_audio_turn(
            event.payload.reason,
            event.event_id,
            outcome=outcome,
            automatic=False,
        )

    async def _auto_finish_audio(self, outcome: VADOutcome) -> None:
        self._discard_late_audio = True
        await self._send_event(
            server_event(
                "audio.auto_stopped",
                self.session_id,
                reason=outcome.reason,
            )
        )
        if not outcome.should_transcribe:
            code = (
                "no_speech_timeout"
                if outcome.reason == "no_speech_timeout"
                else "maximum_turn_duration"
            )
            message = (
                "No speech was detected before the listening timeout."
                if code == "no_speech_timeout"
                else "Maximum recording length reached."
            )
            await self._recover_audio_error(code, message, "vad-auto-stop")
            return
        await self._finish_audio_turn(
            outcome.reason,
            "vad-auto-stop",
            outcome=outcome,
            automatic=True,
        )

    async def _finish_audio_turn(
        self,
        reason: str,
        in_reply_to: str,
        *,
        outcome: VADOutcome | None,
        automatic: bool,
    ) -> None:
        if self._audio_turn is None:
            return
        stop_received_at = perf_counter()
        audio_turn = self._audio_turn
        self._audio_turn = None
        detector = self._vad_detector
        self._vad_detector = None
        vad_metrics = detector.metrics if detector is not None else {}
        if detector is not None and outcome is not None and outcome.should_transcribe:
            retained = detector.retained_pcm(bytes(audio_turn.data))
            audio_turn.data = bytearray(retained)
        await self._transition(ConversationState.TRANSCRIBING)
        await self._send_event(
            server_event(
                "audio.received",
                self.session_id,
                received_bytes=audio_turn.received_bytes,
                duration_ms=audio_turn.duration_ms,
                reason=reason,
                automatic=automatic,
                in_reply_to=in_reply_to,
            )
        )
        logger.info(
            "voice_audio_received session_id=%s bytes=%d duration_ms=%d sample_rate=%d",
            self.session_id,
            audio_turn.received_bytes,
            audio_turn.duration_ms,
            audio_turn.sample_rate,
        )

        if reason == "cancelled":
            audio_turn.clear()
            self._clear_audio_turn()
            await self._transition(ConversationState.READY)
            return

        if outcome is not None and not outcome.should_transcribe:
            audio_turn.clear()
            await self._recover_audio_error(
                "no_speech_detected",
                "No speech was detected. Check your microphone or try again.",
                in_reply_to,
            )
            return

        if audio_turn.received_bytes < MIN_AUDIO_BYTES:
            audio_turn.clear()
            await self._recover_audio_error(
                "audio_too_short",
                "No usable microphone audio was received.",
                in_reply_to,
            )
            return

        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(mode="wb", suffix=".wav", delete=False) as wav_file:
                temporary_path = Path(wav_file.name)
                wav_file.write(audio_turn.to_wav_bytes())

            stt_service = self._stt_factory()
            result = await run_in_threadpool(
                stt_service.transcribe_detailed, temporary_path
            )
            await self._send_event(
                server_event(
                    "transcript.final",
                    self.session_id,
                    text=result.transcript,
                    language=result.language,
                    duration_ms=audio_turn.duration_ms,
                    received_bytes=audio_turn.received_bytes,
                    size_bytes=audio_turn.received_bytes,
                    transcription_ms=result.transcription_ms,
                    stt_mode=result.mode,
                    model=result.model,
                    speech_detected=result.speech_detected,
                    is_mock=result.mode == "mock",
                    metadata={
                        "model": result.model,
                        "audio_duration_ms": audio_turn.duration_ms,
                        "transcription_ms": result.transcription_ms,
                        "speech_detected": result.speech_detected,
                        "mode": result.mode,
                    },
                    auto_sent=False,
                    in_reply_to=in_reply_to,
                )
            )
            logger.info(
                "voice_turn session_id=%s sample_rate=%d speech_start_ms=%s "
                "speech_end_ms=%s speech_duration_ms=%s ending_silence_ms=%s "
                "vad_threshold=%s stop_reason=%s retained_bytes=%d "
                "transcription_ms=%d delivery_ms=%.1f model=%s",
                self.session_id,
                audio_turn.sample_rate,
                vad_metrics.get("speech_start_ms"),
                vad_metrics.get("speech_end_ms"),
                vad_metrics.get("speech_duration_ms"),
                vad_metrics.get("silence_duration_ms"),
                vad_metrics.get("threshold"),
                reason,
                audio_turn.received_bytes,
                result.transcription_ms,
                (perf_counter() - stop_received_at) * 1000,
                result.model,
            )
            audio_turn.clear()
            self._turn_active = False
            await self._transition(ConversationState.READY)
        except STTUnavailableError as exc:
            await self._recover_audio_error(
                exc.code, str(exc), in_reply_to
            )
        except STTNoSpeechError as exc:
            await self._recover_audio_error(exc.code, str(exc), in_reply_to)
        except STTMalformedAudioError as exc:
            await self._recover_audio_error(exc.code, str(exc), in_reply_to)
        except STTError as exc:
            await self._recover_audio_error(exc.code, str(exc), in_reply_to)
        except Exception:
            logger.exception("voice_transcription_error session_id=%s", self.session_id)
            await self._recover_audio_error(
                "transcription_failed", "Local speech transcription failed.", in_reply_to
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
        self._discard_late_audio = False
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
        self._vad_detector = None
        self._turn_active = False

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
