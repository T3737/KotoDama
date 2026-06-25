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

## Offline Runtime Boundary

Gameplay uses loopback services only: Godot connects to FastAPI at
`127.0.0.1:8000`, FastAPI uses local STT, and NPC generation uses local
Ollama. There are no hosted fallbacks, telemetry, analytics, or CDN assets.
Bind Uvicorn to loopback:

```powershell
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

## WebSocket Voice Session

The canonical session transport is:

```text
ws://127.0.0.1:8000/voice/session
```

Text protocol events use an envelope with `type`, `session_id`, unique
`event_id`, ISO-8601 `timestamp`, and an object `payload`:

```json
{
  "type": "session.start",
  "session_id": "default_save:haru",
  "event_id": "client-generated-id",
  "timestamp": "2026-06-23T10:00:00Z",
  "payload": {"npc_id": "haru", "scene_context": "At the market."}
}
```

Client text events are `session.start`, `player.text`, `audio.start`,
`audio.stop`, `session.close`, and `ping`. Between `audio.start` and
`audio.stop`, binary WebSocket packets contain raw microphone PCM. Server
events include `audio.ready`, `audio.received`, and `transcript.final` in
addition to the existing session, NPC text, error, and pong events.

The transport audio is mono signed PCM16 little-endian (`pcm_s16le`) at the
exact sample rate declared by Godot, normally 48000 Hz. Godot averages stereo
capture frames to mono and clamps before conversion. FastAPI writes matching
WAV headers before calling the existing STT service; 48 kHz data is never
silently labelled as 16 kHz.

```json
{
  "type": "audio.start",
  "session_id": "default_save:haru",
  "event_id": "client-generated-id",
  "timestamp": "2026-06-23T10:00:00Z",
  "payload": {
    "sample_rate": 48000,
    "channels": 1,
    "encoding": "pcm_s16le",
    "auto_send_transcript": false
  }
}
```

`auto_send_transcript` defaults to false, so the transcript appears in the
editable text field. When enabled it routes the transcript through the same
NPC orchestrator as `player.text`. `audio.stop` accepts an optional `reason`.

The canonical state set is `DISCONNECTED`, `CONNECTING`, `READY`, `LISTENING`,
`TRANSCRIBING`, `GENERATING`, `SPEAKING`, and `ERROR`. Text turns use:

```text
CONNECTING -> READY -> GENERATING -> READY
```

Manual audio turns use:

```text
READY -> LISTENING -> TRANSCRIBING -> READY
READY -> LISTENING -> TRANSCRIBING -> GENERATING -> READY  (auto-send)
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

Each socket owns a bounded audio buffer. Defaults are a 20-second turn, 4 MiB
maximum PCM data, and a 3-second listening idle timeout. Configure these with
`VOICE_MAX_TURN_SECONDS`, `VOICE_MAX_AUDIO_BYTES`, and
`VOICE_AUDIO_IDLE_SECONDS`. Buffers and temporary WAVs are removed after
success, failure, cancellation, limit rejection, or disconnect.

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
CPU with `int8` compute and `local_files_only`, so ordinary gameplay never
downloads a model. Provision the configured model separately before play. If
the dependency or local model is unavailable, transcription returns a clear
readiness error while `/health` and `/npc/chat` remain available. No cloud
fallback is attempted.

## Tests

```powershell
cd backend
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

The tests cover existing HTTP and speech routes plus text/audio session round
trips, correct WAV construction, empty and out-of-order audio, overlap and size
limits, cleanup, mock/unavailable STT, transcript routing, ping/pong, readiness,
and clean close.

## Manual Streamed-Microphone Validation

1. Start Ollama locally.
2. Start FastAPI on `127.0.0.1:8000`.
3. Run the canonical Godot scene.
4. Open dialogue with an NPC and wait for `Ready`.
5. Select `Record`, speak for 2-3 seconds, then select `Stop / Transcribe`.
6. Confirm Godot reports non-zero transmitted bytes and FastAPI logs the
   received byte count.
7. Confirm `transcript.final` appears, can be edited, and can be sent.
8. Confirm the NPC responds with the internet disconnected.
9. Select an incorrect system input device and repeat. Confirm the UI says
   `No microphone audio detected. Check the selected system input device.`

## Current Fallbacks And Deferred Work

Typed `player.text`, `/npc/chat`, `/speech/transcribe`, and the existing
`AudioEffectRecord` WAV upload remain available alongside streaming. Automatic
VAD, continuous listening, partial/streaming STT, TTS, interruption/barge-in,
pronunciation scoring, model training, LoRA, and database persistence are not
implemented.
