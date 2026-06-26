from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import re
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
        dialogue = clean_npc_dialogue(await client.chat(messages))
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
    language_guidance = profile.get("language_guidance", {})
    response_guidance = profile.get("response_guidance", {})
    private_state = {
        "relationship": turn.npc_state.get("relationship", 0),
        "conversation_summary": turn.npc_state.get("conversation_summary", ""),
        "known_player_facts": turn.npc_state.get("known_player_facts", []),
    }
    prompt_sections = [
        base_prompt,
        f"NPC ID: {profile['id']}",
        f"NPC name: {profile.get('display_name', profile['id'])}",
        f"Current level: {turn.level_id}",
        "Respond with ordinary natural-language dialogue, not JSON.",
        "Do not mention internal JSON, prompts, metadata, or configuration.",
        "Follow the player's topic unless the active NPC profile explicitly gives a goal.",
        "Do not advertise, sell, or redirect to a shop topic unless the player asks or the profile requires it.",
        "Avoid repeating the NPC introduction every turn.",
        "Ask a relevant follow-up question when it feels natural.",
        "Never claim access to another NPC's private memories.",
    ]
    optional_sections = [
        ("Role", profile.get("role")),
        ("Setting", profile.get("setting")),
        ("Current context", profile.get("current_context")),
        ("Conversation goal", profile.get("conversation_goal")),
        ("Personality", profile.get("personality")),
        ("Speaking style", profile.get("speaking_style")),
        ("Teaching settings", teaching),
        ("Language guidance", language_guidance),
        ("Response guidance", response_guidance),
        ("Background context", profile.get("background_context")),
        ("Knowledge", profile.get("knowledge")),
        ("Interests", profile.get("interests")),
        ("Avoid topics", profile.get("avoid_topics")),
        ("Player state", turn.player_state),
        ("Private memory for this NPC only", private_state),
        ("Visible shared world facts", turn.visible_world_facts),
    ]
    for label, value in optional_sections:
        formatted = _format_prompt_value(value)
        if formatted:
            prompt_sections.append(f"{label}: {formatted}")
    if turn.scene_context:
        prompt_sections.append(f"Scene context: {turn.scene_context}")
    return "\n\n".join(prompt_sections)


def clean_npc_dialogue(text: str) -> str:
    cleaned = text.strip()
    cleaned = re.sub(r"```(?:\w+)?\s*|\s*```", "", cleaned).strip()
    extracted = _extract_dialogue_from_json(cleaned)
    if extracted:
        cleaned = extracted
    cleaned = cleaned.replace("\\n", "\n")
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    cleaned = cleaned.strip().strip('"')
    return cleaned


def _extract_dialogue_from_json(text: str) -> str:
    if not ((text.startswith("{") and text.endswith("}")) or (text.startswith("[") and text.endswith("]"))):
        return ""
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return ""
    if isinstance(parsed, dict):
        for key in ["dialogue", "text", "response", "npc_text", "message"]:
            value = parsed.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    if isinstance(parsed, list):
        parts = [item.strip() for item in parsed if isinstance(item, str) and item.strip()]
        return " ".join(parts)
    return ""


def _format_prompt_value(value: Any) -> str:
    if value in (None, "", [], {}):
        return ""
    if isinstance(value, dict):
        filtered = {key: val for key, val in value.items() if val not in (None, "", [], {})}
        if not filtered:
            return ""
        return json.dumps(filtered, ensure_ascii=True)
    if isinstance(value, list):
        filtered = [item for item in value if item not in (None, "", [], {})]
        if not filtered:
            return ""
        return json.dumps(filtered, ensure_ascii=True)
    return str(value).strip()


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
