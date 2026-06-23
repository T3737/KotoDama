# KotoDama FastAPI Dialogue And Session Backend

The backend exposes one reusable local Ollama model as a dialogue engine for
multiple independently configured NPCs.

## Install And Run

From the repository root:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
ollama pull llama3.2
uvicorn app.main:app --reload
```

The service listens at `http://127.0.0.1:8000`. Ollama is expected at
`http://localhost:11434`.

Health check:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
Invoke-RestMethod http://127.0.0.1:8000/ready
```

`/health` reports process health and stays healthy when optional local services
are unavailable. `/ready` additionally reports current Ollama reachability,
`STT_MODE`, and WebSocket support.

## WebSocket Voice Session Foundation

The canonical session transport is:

```text
ws://127.0.0.1:8000/voice/session
```

Despite the route name, this milestone carries JSON text events only. Every
event uses an envelope with `type`, `session_id`, unique `event_id`, ISO-8601
`timestamp`, and an object `payload`:

```json
{
  "type": "session.start",
  "session_id": "default_save:haru",
  "event_id": "client-generated-id",
  "timestamp": "2026-06-23T10:00:00Z",
  "payload": {"npc_id": "haru", "scene_context": "At the market."}
}
```

Client events are `session.start`, `player.text`, `session.close`, and `ping`.
Server events are `session.ready`, `state.changed`, `npc.text.delta`,
`npc.text.final`, `error`, and `pong`. The current Ollama adapter is
non-streaming, so it sends one `npc.text.final`; it does not manufacture delta
events. Errors include stable `code`, human-readable `message`, and `fatal`.

The canonical state set is `DISCONNECTED`, `CONNECTING`, `READY`, `LISTENING`,
`TRANSCRIBING`, `GENERATING`, `SPEAKING`, and `ERROR`. Text turns use:

```text
CONNECTING -> READY -> GENERATING -> READY
```

Invalid transitions and overlapping player turns are rejected. A generation
failure emits a non-fatal error and returns the session to `READY`; `ERROR` is
reserved for unrecoverable session failures. Each WebSocket owns its lifecycle
and turn lock, while both WebSocket and `/npc/chat` delegate to the same NPC
orchestrator and NPC-namespaced memory store.

Manual WebSocket test (with any WebSocket client): connect to the URL above,
send `session.start`, wait for `session.ready`, then send the same envelope with
type `player.text` and payload `{"text":"Hello"}`. Expect `GENERATING`, one
`npc.text.final`, then `READY`. Send `session.close` to finish cleanly.

## Dialogue Request

`POST /npc/chat` accepts the new multi-NPC request shape:

```json
{
  "npc_id": "haru",
  "session_id": "default_save:haru",
  "player_message": "I would like two apples.",
  "level_id": "level_02",
  "player_state": {"language_level": 1},
  "npc_state": {
    "relationship": 0,
    "conversation_summary": "",
    "conversation_history": [],
    "known_player_facts": []
  },
  "visible_world_facts": []
}
```

The original `player_text`, `npc_name`, `target_language`, and `scene_context`
fields remain accepted for compatibility.

Response:

```json
{
  "dialogue": "...",
  "npc_text": "...",
  "npc_id": "haru",
  "emotion": "focused",
  "memory_updates": [],
  "world_updates": [],
  "teaching_data": {
    "new_words": [],
    "corrections": []
  }
}
```

`npc_text` remains present for older clients. The current Godot client displays
`dialogue` and falls back to `npc_text`.

## Profiles And Sessions

The backend loads canonical profiles from:

```text
pixel_farm_godot4/godot_skeleton/data/npcs/
```

Unknown `npc_id` values return HTTP 404. Profile traits, speaking style,
teaching focus, private NPC state, and visible world facts are assembled into
the system prompt. One Ollama process serves every NPC.

Session history is stored separately by NPC. Even if a caller supplies a
misnamed session, the backend appends the requested NPC ID to prevent private
history from entering another NPC's session.

The in-memory backend session store is intentionally small and non-durable.
Godot sends persisted NPC state/history after a backend restart.

## Speech Transcription Prototype

`POST /speech/transcribe` accepts an English audio upload in a multipart field
named `file`. Supported filename extensions are `.wav`, `.ogg`, and `.webm`.

Mock mode is the default and does not require a speech model:

```powershell
$env:STT_MODE = "mock"
uvicorn app.main:app --reload
```

Test it from PowerShell:

```powershell
Invoke-RestMethod `
  -Uri "http://127.0.0.1:8000/speech/transcribe" `
  -Method POST `
  -Form @{ file = Get-Item ".\test_audio.wav" }
```

Or with curl:

```bash
curl -X POST http://127.0.0.1:8000/speech/transcribe \
  -F "file=@test_audio.wav"
```

Mock response:

```json
{
  "transcript": "i would like to learn japanese",
  "language": "en",
  "status": "ok"
}
```

For optional local transcription with faster-whisper:

```powershell
pip install -r requirements-stt.txt
$env:STT_MODE = "local"
$env:STT_MODEL = "tiny.en"
uvicorn app.main:app --reload
```

`STT_MODEL` defaults to `tiny.en`. The local provider runs English-only on the
CPU with `int8` compute. Model files may be downloaded by faster-whisper on the
first request. If faster-whisper or the configured model is unavailable, only
the transcription request returns an error; backend startup, `/health`, and
`/npc/chat` remain available.

## Tests

```powershell
cd backend
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

The tests cover the existing HTTP and speech routes plus session start, text
round trips, state order, malformed/unsupported events, pre-start messages,
overlap rejection, ping/pong, invalid transitions, readiness, and clean close.

## Deferred Work

Microphone streaming, binary audio frames, VAD, streaming STT, TTS audio,
interruption/barge-in, training, LoRA, and database persistence are explicitly
outside this foundation. Recorded WAV transcription remains the existing HTTP
flow and its transcript can be submitted as ordinary session text.
