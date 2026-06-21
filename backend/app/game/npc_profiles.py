import json
from functools import lru_cache
from pathlib import Path
from typing import Any


PROFILE_DIRECTORY = (
    Path(__file__).resolve().parents[3]
    / "pixel_farm_godot4"
    / "godot_skeleton"
    / "data"
    / "npcs"
)


class NpcProfileError(Exception):
    """Raised when an NPC profile is missing or invalid."""


@lru_cache(maxsize=32)
def load_npc_profile(npc_id: str) -> dict[str, Any]:
    profile_path = PROFILE_DIRECTORY / f"{npc_id}.json"
    if not profile_path.is_file():
        raise NpcProfileError(f"Unknown NPC ID: {npc_id}")

    try:
        data = json.loads(profile_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise NpcProfileError(f"Could not load NPC profile '{npc_id}'.") from exc

    if not isinstance(data, dict) or data.get("id") != npc_id:
        raise NpcProfileError(f"NPC profile '{npc_id}' is invalid.")
    return data
