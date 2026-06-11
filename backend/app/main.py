from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, model_validator

from app.api.speech import router as speech_router
from app.game.npc_profiles import NpcProfileError, load_npc_profile
from app.game.session_store import SessionStore
from app.llm.ollama_client import OllamaClient, OllamaError


PROMPT_PATH = Path(__file__).parent / "prompts" / "npc_tutor.md"

app = FastAPI(title="KotoDama NPC AI Backend")
app.include_router(speech_router)
session_store = SessionStore(max_messages=12)
ollama_client = OllamaClient()


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


@app.post("/npc/chat", response_model=NpcChatResponse)
async def npc_chat(request: NpcChatRequest) -> NpcChatResponse:
    npc_id = request.npc_id or _legacy_npc_id(request.npc_name)
    try:
        profile = load_npc_profile(npc_id)
    except NpcProfileError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    system_prompt = _build_system_prompt(request, profile)
    session_key = _npc_session_key(request.session_id, npc_id)
    server_history = session_store.get_history(session_key)
    history = server_history or _validated_private_history(request.npc_state)
    current_message = {"role": "user", "content": request.message}
    messages = [
        {"role": "system", "content": system_prompt},
        *history,
        current_message,
    ]

    try:
        dialogue = await ollama_client.chat(messages)
    except OllamaError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    session_store.add_message(session_key, "user", request.message)
    session_store.add_message(session_key, "assistant", dialogue)

    return NpcChatResponse(
        dialogue=dialogue,
        npc_text=dialogue,
        npc_id=npc_id,
        emotion=_default_emotion(profile),
    )


def _build_system_prompt(
    request: NpcChatRequest, profile: dict[str, Any]
) -> str:
    base_prompt = PROMPT_PATH.read_text(encoding="utf-8").strip()
    teaching = profile.get("teaching", {})
    private_state = {
        "relationship": request.npc_state.get("relationship", 0),
        "conversation_summary": request.npc_state.get("conversation_summary", ""),
        "known_player_facts": request.npc_state.get("known_player_facts", []),
    }
    prompt_sections = [
        base_prompt,
        f"NPC ID: {profile['id']}",
        f"NPC name: {profile.get('display_name', profile['id'])}",
        f"Role: {profile.get('role', '')}",
        f"Current level: {request.level_id}",
        f"Personality settings: {profile.get('personality', {})}",
        f"Speaking style: {profile.get('speaking_style', {})}",
        f"Teaching settings: {teaching}",
        f"Background context: {profile.get('background_context', [])}",
        f"Player state: {request.player_state}",
        f"Private memory for this NPC only: {private_state}",
        f"Visible shared world facts: {request.visible_world_facts}",
        "Never claim access to another NPC's private memories.",
    ]
    if request.scene_context:
        prompt_sections.append(f"Scene context: {request.scene_context}")
    return "\n\n".join(prompt_sections)


def _validated_private_history(
    npc_state: dict[str, Any],
) -> list[dict[str, str]]:
    raw_history = npc_state.get("conversation_history", [])
    if not isinstance(raw_history, list):
        return []
    history: list[dict[str, str]] = []
    for item in raw_history[-8:]:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        content = item.get("content")
        if role in {"user", "assistant"} and isinstance(content, str):
            history.append({"role": role, "content": content})
    return history


def _legacy_npc_id(npc_name: str | None) -> str:
    if not npc_name:
        return "aiko"
    normalized = npc_name.strip().lower()
    return normalized if normalized in {"aiko", "haru", "emi"} else "aiko"


def _npc_session_key(session_id: str, npc_id: str) -> str:
    suffix = f":{npc_id}"
    return session_id if session_id.endswith(suffix) else f"{session_id}{suffix}"


def _default_emotion(profile: dict[str, Any]) -> str:
    role = str(profile.get("role", ""))
    if "shopkeeper" in role:
        return "focused"
    if "guide" in role:
        return "enthusiastic"
    return "friendly"
