from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.game.npc_profiles import load_npc_profile
from app.game.session_store import SessionStore
from app.llm.ollama_client import OllamaClient


PROMPT_PATH = Path(__file__).parents[1] / "prompts" / "npc_tutor.md"


@dataclass(slots=True)
class NpcTurn:
    session_id: str
    npc_id: str
    player_message: str
    level_id: str = "level_01"
    player_state: dict[str, Any] = field(default_factory=dict)
    npc_state: dict[str, Any] = field(default_factory=dict)
    visible_world_facts: list[dict[str, Any]] = field(default_factory=list)
    scene_context: str | None = None


@dataclass(slots=True)
class NpcTurnResult:
    dialogue: str
    npc_id: str
    emotion: str
    memory_updates: list[dict[str, Any]] = field(default_factory=list)
    world_updates: list[dict[str, Any]] = field(default_factory=list)
    teaching_data: dict[str, list[Any]] = field(
        default_factory=lambda: {"new_words": [], "corrections": []}
    )


class NpcOrchestrator:
    """Canonical NPC turn layer shared by HTTP and session transports."""

    def __init__(self, session_store: SessionStore) -> None:
        self.session_store = session_store

    async def respond(self, turn: NpcTurn, client: OllamaClient) -> NpcTurnResult:
        profile = load_npc_profile(turn.npc_id)
        system_prompt = build_system_prompt(turn, profile)
        session_key = npc_session_key(turn.session_id, turn.npc_id)
        server_history = self.session_store.get_history(session_key)
        history = server_history or validated_private_history(turn.npc_state)
        messages = [
            {"role": "system", "content": system_prompt},
            *history,
            {"role": "user", "content": turn.player_message},
        ]
        dialogue = await client.chat(messages)
        self.session_store.add_message(session_key, "user", turn.player_message)
        self.session_store.add_message(session_key, "assistant", dialogue)
        return NpcTurnResult(
            dialogue=dialogue,
            npc_id=turn.npc_id,
            emotion=default_emotion(profile),
        )


def build_system_prompt(turn: NpcTurn, profile: dict[str, Any]) -> str:
    base_prompt = PROMPT_PATH.read_text(encoding="utf-8").strip()
    teaching = profile.get("teaching", {})
    private_state = {
        "relationship": turn.npc_state.get("relationship", 0),
        "conversation_summary": turn.npc_state.get("conversation_summary", ""),
        "known_player_facts": turn.npc_state.get("known_player_facts", []),
    }
    prompt_sections = [
        base_prompt,
        f"NPC ID: {profile['id']}",
        f"NPC name: {profile.get('display_name', profile['id'])}",
        f"Role: {profile.get('role', '')}",
        f"Current level: {turn.level_id}",
        f"Personality settings: {profile.get('personality', {})}",
        f"Speaking style: {profile.get('speaking_style', {})}",
        f"Teaching settings: {teaching}",
        f"Background context: {profile.get('background_context', [])}",
        f"Player state: {turn.player_state}",
        f"Private memory for this NPC only: {private_state}",
        f"Visible shared world facts: {turn.visible_world_facts}",
        "Never claim access to another NPC's private memories.",
    ]
    if turn.scene_context:
        prompt_sections.append(f"Scene context: {turn.scene_context}")
    return "\n\n".join(prompt_sections)


def validated_private_history(npc_state: dict[str, Any]) -> list[dict[str, str]]:
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


def npc_session_key(session_id: str, npc_id: str) -> str:
    suffix = f":{npc_id}"
    return session_id if session_id.endswith(suffix) else f"{session_id}{suffix}"


def default_emotion(profile: dict[str, Any]) -> str:
    role = str(profile.get("role", ""))
    if "shopkeeper" in role:
        return "focused"
    if "guide" in role:
        return "enthusiastic"
    return "friendly"
