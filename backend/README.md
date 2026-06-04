# KotoDama Backend AI Prototype

This is a small standalone FastAPI backend prototype for NPC dialogue. It is not connected to the Godot frontend yet.

The backend accepts player dialogue and scene context, sends it to a local Ollama model, and returns a short NPC response.

## Install Dependencies

From the repo root:

```powershell
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## Start Ollama

Install and start Ollama locally, then pull the default model:

```powershell
ollama pull llama3.2
```

Ollama should be available at:

```text
http://localhost:11434
```

## Run the Backend

```powershell
cd backend
.venv\Scripts\activate
uvicorn app.main:app --reload
```

The API will run at:

```text
http://127.0.0.1:8000
```

## Test Health

```powershell
curl http://127.0.0.1:8000/health
```

Expected response:

```json
{
  "status": "ok"
}
```

## Test NPC Chat

```powershell
curl -X POST http://127.0.0.1:8000/npc/chat `
  -H "Content-Type: application/json" `
  -d '{
    "session_id": "player_001",
    "player_text": "Hello, I want to buy bread.",
    "target_language": "Japanese",
    "npc_name": "Aiko",
    "scene_context": "The player is talking to a shopkeeper."
  }'
```

Expected response shape:

```json
{
  "npc_text": "..."
}
```

## Future Godot Integration

When the Godot frontend is ready, it can send an HTTP `POST` request to `/npc/chat` whenever the player speaks to an NPC. The request should include the current session ID, player text, target language, NPC name, and scene context.
