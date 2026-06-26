import logging
import os
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field, model_validator

from app.api.speech import router as speech_router
from app.api.tts import router as tts_router
from app.api.voice_session import router as voice_session_router
from app.game.npc_profiles import NpcProfileError, load_npc_profile
from app.game.session_store import SessionStore
from app.llm.ollama_client import OllamaClient, OllamaError
from app.orchestration.npc_orchestrator import (
    NpcOrchestrator,
    NpcTurn,
    build_system_prompt,
    default_emotion,
    npc_session_key,
    validated_private_history,
)
from app.speech.stt_service import create_stt_service, get_stt_mode, get_stt_readiness
from app.speech.tts_service import (
    TemporaryTTSAudioStore,
    TTSUnavailableError,
    create_tts_service,
    tts_debug_enabled,
    tts_startup_summary,
)
from app.speech.vad_service import VADUnavailableError, create_vad_service


logger = logging.getLogger(__name__)


app = FastAPI(title="KotoDama NPC AI Backend")
app.include_router(speech_router)
app.include_router(tts_router)
app.include_router(voice_session_router)
session_store = SessionStore(max_messages=12)
ollama_client = OllamaClient()
npc_orchestrator = NpcOrchestrator(session_store)
stt_service = create_stt_service()
vad_service = create_vad_service()
tts_service = create_tts_service()
tts_audio_store = TemporaryTTSAudioStore()
app.state.ollama_client = ollama_client
app.state.npc_orchestrator = npc_orchestrator
app.state.stt_service = stt_service
app.state.stt_service_factory = lambda: app.state.stt_service
app.state.vad_service = vad_service
app.state.vad_service_factory = lambda: app.state.vad_service
app.state.tts_service = tts_service
app.state.tts_service_factory = lambda: app.state.tts_service
app.state.tts_audio_store = tts_audio_store


@app.on_event("startup")
async def preload_stt_model() -> None:
    if os.getenv("STT_PRELOAD", "false").strip().lower() not in {"1", "true", "yes"}:
        return
    try:
        await run_in_threadpool(app.state.stt_service.prepare)
    except Exception as exc:
        # STT remains optional: readiness reports the error while health stays healthy.
        logger.error("stt_preload_failed error=%s", exc)


@app.on_event("startup")
async def preload_vad_model() -> None:
    if os.getenv("VAD_PRELOAD", "true").strip().lower() not in {"1", "true", "yes"}:
        return
    try:
        await run_in_threadpool(app.state.vad_service.prepare)
    except VADUnavailableError as exc:
        # Automatic stopping is optional; manual Stop remains available.
        logger.warning("vad_preload_unavailable error=%s", exc)


@app.on_event("startup")
async def preload_tts_model() -> None:
    if os.getenv("TTS_PRELOAD", "false").strip().lower() not in {"1", "true", "yes"}:
        return
    try:
        await run_in_threadpool(app.state.tts_service.prepare)
    except TTSUnavailableError as exc:
        # NPC voice remains optional; text-only dialogue continues.
        logger.warning("tts_preload_unavailable error=%s", exc)
    except Exception as exc:
        logger.error("tts_preload_failed error=%s", exc)


@app.on_event("startup")
async def log_tts_configuration() -> None:
    if not tts_debug_enabled():
        return
    summary = tts_startup_summary(app.state.tts_service)
    logger.info(
        "tts_startup mode=%s tts_model_path=%s tts_config_path=%s "
        "tts_model_exists=%s tts_config_exists=%s tts_state=%s",
        summary["mode"],
        summary["model_path"],
        summary["config_path"],
        summary["model_exists"],
        summary["config_exists"],
        summary["state"],
    )


@app.on_event("shutdown")
async def cleanup_tts_audio() -> None:
    app.state.tts_audio_store.clear()


class NpcChatRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    npc_id: str | None = None
    player_message: str | None = None
    level_id: str = "level_01"
    player_state: dict[str, Any] = Field(default_factory=dict)
    npc_state: dict[str, Any] = Field(default_factory=dict)
    visible_world_facts: list[dict[str, Any]] = Field(default_factory=list)

    # Legacy fields remain accepted for the original Godot client and curl examples.
    player_text: str | None = None
    target_language: str | None = None
    npc_name: str | None = None
    scene_context: str | None = None

    @model_validator(mode="after")
    def validate_message(self) -> "NpcChatRequest":
        message = self.player_message or self.player_text
        if not isinstance(message, str) or not message.strip():
            raise ValueError("player_message or player_text must not be empty")
        return self

    @property
    def message(self) -> str:
        return (self.player_message or self.player_text or "").strip()


class NpcChatResponse(BaseModel):
    dialogue: str
    npc_text: str
    npc_id: str
    emotion: str = "neutral"
    memory_updates: list[dict[str, Any]] = Field(default_factory=list)
    world_updates: list[dict[str, Any]] = Field(default_factory=list)
    teaching_data: dict[str, list[Any]] = Field(
        default_factory=lambda: {"new_words": [], "corrections": []}
    )


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready")
async def ready() -> dict[str, Any]:
    return {
        "status": "ok",
        "ollama": await app.state.ollama_client.is_available(),
        "stt_mode": get_stt_mode(),
        "stt": get_stt_readiness(),
        "vad": app.state.vad_service.readiness(),
        "tts": app.state.tts_service.readiness(),
        "voice_websocket": True,
    }


@app.post("/npc/chat", response_model=NpcChatResponse)
async def npc_chat(request: NpcChatRequest) -> NpcChatResponse:
    npc_id = request.npc_id or _legacy_npc_id(request.npc_name)
    try:
        result = await npc_orchestrator.respond(
            _to_npc_turn(request, npc_id),
            ollama_client,
        )
    except NpcProfileError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except OllamaError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return NpcChatResponse(
        dialogue=result.dialogue,
        npc_text=result.dialogue,
        npc_id=result.npc_id,
        emotion=result.emotion,
        memory_updates=result.memory_updates,
        world_updates=result.world_updates,
        teaching_data=result.teaching_data,
    )


def _build_system_prompt(
    request: NpcChatRequest, profile: dict[str, Any]
) -> str:
    return build_system_prompt(_to_npc_turn(request, profile["id"]), profile)


def _validated_private_history(
    npc_state: dict[str, Any],
) -> list[dict[str, str]]:
    return validated_private_history(npc_state)


def _legacy_npc_id(npc_name: str | None) -> str:
    if not npc_name:
        return "aiko"
    normalized = npc_name.strip().lower()
    return normalized if normalized in {"aiko", "haru", "emi"} else "aiko"


def _npc_session_key(session_id: str, npc_id: str) -> str:
    return npc_session_key(session_id, npc_id)


def _default_emotion(profile: dict[str, Any]) -> str:
    return default_emotion(profile)


def _to_npc_turn(request: NpcChatRequest, npc_id: str) -> NpcTurn:
    return NpcTurn(
        session_id=request.session_id,
        npc_id=npc_id,
        player_message=request.message,
        level_id=request.level_id,
        player_state=request.player_state,
        npc_state=request.npc_state,
        visible_world_facts=request.visible_world_facts,
        scene_context=request.scene_context,
    )
