from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, model_validator

from app.api.speech import router as speech_router
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
from app.speech.stt_service import get_stt_mode


app = FastAPI(title="KotoDama NPC AI Backend")
app.include_router(speech_router)
app.include_router(voice_session_router)
session_store = SessionStore(max_messages=12)
ollama_client = OllamaClient()
npc_orchestrator = NpcOrchestrator(session_store)
app.state.ollama_client = ollama_client
app.state.npc_orchestrator = npc_orchestrator


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
async def ready() -> dict[str, str | bool]:
    return {
        "status": "ok",
        "ollama": await app.state.ollama_client.is_available(),
        "stt_mode": get_stt_mode(),
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
