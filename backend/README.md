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
STT readiness, and WebSocket support. Existing `stt_mode` consumers remain
supported; the detailed `stt` object reports `not_loaded`, `loading`, `ready`,
or `error`:

```json
{
  "status": "ok",
  "ollama": true,
  "stt_mode": "local",
  "stt": {
    "mode": "local",
    "model": "base.en",
    "state": "ready",
    "load_ms": 734.2,
    "error": null
  },
  "voice_websocket": true
}
```

Set `STT_PRELOAD=true` to load the configured model during backend startup;
otherwise it loads lazily on the first transcription. A process-wide cache and
load lock ensure concurrent requests reuse one model instance. `/health` stays
healthy if optional STT is unavailable.

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

`auto_send_transcript` is accepted for forward protocol compatibility but is
currently ignored. Every transcript returns to the editable text field for
player confirmation. `audio.stop` accepts an optional `reason`.

The canonical state set is `DISCONNECTED`, `CONNECTING`, `READY`, `LISTENING`,
`TRANSCRIBING`, `GENERATING`, `SPEAKING`, and `ERROR`. Text turns use:

```text
CONNECTING -> READY -> GENERATING -> READY
```

Manual audio turns use:

```text
READY -> LISTENING -> TRANSCRIBING -> READY
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

Each socket owns a bounded audio buffer. Defaults are a 20-second turn, a 4 MiB
hard ceiling further restricted by sample rate and duration, and a 3-second
listening idle timeout. Configure these with
`VOICE_MAX_TURN_SECONDS`, `VOICE_MAX_AUDIO_BYTES`, and
`VOICE_AUDIO_IDLE_SECONDS`. Buffers and temporary WAVs are removed after
success, failure, cancellation, limit rejection, or disconnect.

## Local Voice Activity Detection

Automatic end-of-speech uses a process-wide local Silero ONNX session. The
native-rate PCM stream remains untouched for STT; a separate stateful PyAV/
FFmpeg resampler produces mono 16 kHz PCM solely for VAD decisions. There are
no network calls or runtime model downloads.

Install the local runtime dependencies:

```powershell
pip install -r requirements-vad.txt
```

Place a compatible Silero VAD ONNX model at:

```text
backend/models/silero_vad.onnx
```

Or set `VAD_MODEL_PATH` to an absolute local file. ONNX files under
`backend/models/` are ignored by Git because the final packaged application
must provision the model explicitly. `onnxruntime` input layouts using either
`input/state/sr` or the older `input/h/c/sr` form are supported. Loading uses
only the supplied file and `CPUExecutionProvider`.

Initial tuning values are configurable:

```text
VAD_ENABLED=true
VAD_THRESHOLD=0.50
VAD_MIN_SPEECH_MS=250
VAD_END_SILENCE_MS=700
VAD_NO_SPEECH_TIMEOUT_MS=5000
VAD_MAX_TURN_MS=20000
VAD_PRE_ROLL_MS=250
VAD_POST_ROLL_MS=150
VAD_PRELOAD=true
VAD_VERBOSE=false
```

These are starting values, not universal recommendations. `VAD_VERBOSE=true`
enables per-window probability logs for development only. Normal logging emits
one summary per turn with speech timing, ending silence, stop reason, retained
bytes, and transcription latency.

`/ready` reports VAD as `disabled`, `not_loaded`, `loading`, `ready`, or
`error`, including the backend and 16 kHz decision rate. If the model or runtime
is unavailable, `audio.ready` advertises `vad_unavailable`; Godot continues
streaming and displays `Automatic stopping unavailable - use Stop`. Manual Stop
and the WAV/HTTP fallback remain functional.

The server emits `vad.speech_started`, `vad.speech_ended`, and
`audio.auto_stopped`. After automatic completion, queued late binary frames are
discarded until the next `audio.start`, preventing cross-turn contamination.
The transcript still returns to the editable text field and is never sent to
the NPC automatically.

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
$env:STT_PRELOAD = "true"
uvicorn app.main:app --reload
```

`STT_MODEL` defaults to `tiny.en`; `base.en` and `small.en` are also supported.
The local provider runs English-only on the CPU with `int8` compute and
`local_files_only`, so gameplay and benchmarks never download a model.

Provision models before offline play. During an explicitly connected setup
step, for example:

```powershell
python -c "from huggingface_hub import snapshot_download; snapshot_download('Systran/faster-whisper-tiny.en')"
python -c "from huggingface_hub import snapshot_download; snapshot_download('Systran/faster-whisper-base.en')"
python -c "from huggingface_hub import snapshot_download; snapshot_download('Systran/faster-whisper-small.en')"
```

Copy the resulting Hugging Face cache to an offline target if necessary. Never
run provisioning during gameplay. A missing dependency or model produces
`stt_unavailable` and an `error` readiness state; `/health` and `/npc/chat`
remain available.

Successful transcription responses retain the existing fields and add
optional metadata:

```json
{
  "transcript": "hello how are you",
  "language": "en",
  "status": "ok",
  "metadata": {
    "model": "base.en",
    "audio_duration_ms": 2100,
    "transcription_ms": 480,
    "speech_detected": true,
    "mode": "local"
  }
}
```

Errors use structured codes: `no_audio`, `audio_too_short`,
`no_speech_detected`, `malformed_audio`, `stt_unavailable`, and
`transcription_failed`. Godot diagnoses missing microphone frames before an STT
request; valid but silent local WAVs return `no_speech_detected`.
`STT_MIN_AUDIO_MS` defaults to `100`, and `STT_SILENCE_THRESHOLD` defaults to
`0.001` normalized peak amplitude for local WAV validation.

## Local STT Benchmark

The development benchmark uses the same local service and never uploads audio
or downloads models:

```powershell
cd backend
..\.venv\Scripts\python.exe tools\benchmark_stt.py --model tiny.en samples\test_hello.wav
..\.venv\Scripts\python.exe tools\benchmark_stt.py --models tiny.en base.en small.en samples\*.wav
```

It reports model load time, audio duration, transcription time, real-time
factor, and transcript. An optional manifest adds normalized exact match, word
differences, and word error rate:

```json
{
  "samples": [
    {"file": "samples/hello.wav", "expected": "hello how are you"}
  ]
}
```

Run it with `--manifest benchmark_manifest.json`. Personal samples and
benchmark audio directories are ignored by Git. Model quality must be measured
on the target hardware and recordings; no model is assumed to be best.

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
9. Select an incorrect Windows input device and repeat. Confirm the UI says
   `No microphone audio detected. Check the selected Windows input device.`

### Automatic End-Of-Speech Test

1. Start the currently working local STT configuration.
2. Start FastAPI on `127.0.0.1:8000`.
3. Confirm `/ready` reports VAD `ready`.
4. Run the unified world.
5. Enter the AI area.
6. Open NPC dialogue.
7. Press Record.
8. Wait silently for one second.
9. Speak a normal sentence.
10. Pause briefly in the middle of the sentence.
11. Continue speaking.
12. Stop speaking completely.
13. Confirm recording ends automatically after sustained silence.
14. Confirm the transcript appears.
15. Confirm the short mid-sentence pause did not stop recording.
16. Edit or send the transcript.
17. Confirm the NPC responds.
18. Repeat using manual Stop.
19. Start recording and say nothing.
20. Confirm a clear no-speech timeout.
21. Close dialogue during recording.
22. Confirm capture and VAD state are cleaned up.
23. Confirm movement resumes.

## Current Fallbacks And Deferred Work

Typed `player.text`, `/npc/chat`, `/speech/transcribe`, and the existing
`AudioEffectRecord` WAV upload remain available alongside streaming. Automatic
VAD, continuous listening, partial/streaming STT, TTS, interruption/barge-in,
pronunciation scoring, model training, LoRA, and database persistence are not
implemented.
