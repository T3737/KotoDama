from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from app.game.session_store import SessionStore
from app.llm.ollama_client import OllamaClient, OllamaError


PROMPT_PATH = Path(__file__).parent / "prompts" / "npc_tutor.md"

app = FastAPI(title="KotoDama NPC AI Backend")
session_store = SessionStore(max_messages=12)
ollama_client = OllamaClient()


class NpcChatRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    player_text: str = Field(..., min_length=1)
    target_language: str = Field(..., min_length=1)
    npc_name: str = Field(..., min_length=1)
    scene_context: str = Field(..., min_length=1)


class NpcChatResponse(BaseModel):
    npc_text: str


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/npc/chat", response_model=NpcChatResponse)
async def npc_chat(request: NpcChatRequest) -> NpcChatResponse:
    system_prompt = _build_system_prompt(request)
    history = session_store.get_history(request.session_id)
    current_message = {"role": "user", "content": request.player_text}

    messages = [
        {"role": "system", "content": system_prompt},
        *history,
        current_message,
    ]

    try:
        npc_text = await ollama_client.chat(messages)
    except OllamaError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    session_store.add_message(request.session_id, "user", request.player_text)
    session_store.add_message(request.session_id, "assistant", npc_text)

    return NpcChatResponse(npc_text=npc_text)


def _build_system_prompt(request: NpcChatRequest) -> str:
    base_prompt = PROMPT_PATH.read_text(encoding="utf-8").strip()
    return "\n\n".join(
        [
            base_prompt,
            f"NPC name: {request.npc_name}",
            f"Target language: {request.target_language}",
            f"Scene context: {request.scene_context}",
        ]
    )
