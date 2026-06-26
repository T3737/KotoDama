# KotoDama Unified Sandbox

Godot 4.6 sandbox with one persistent player, shared local-AI dialogue systems,
data-driven levels, and JSON save data.

## Run

1. Start Ollama and the FastAPI backend as described in `backend/README.md`.
2. Open `pixel_farm_godot4/godot_skeleton/project.godot` in Godot 4.6.
3. Press F5. The canonical main scene is `scenes/World.tscn`.

The former `AIDialogueDemo` and temporary demo player are archived under
`_archive/superseded_demo` for reference only; normal gameplay does not use them.

Controls:

| Key | Action |
| --- | --- |
| WASD / Arrow keys | Move |
| E | Talk or use a door |
| Enter | Submit dialogue while the text box is focused |

## Voice Input

The dialogue panel includes `Record`, `Stop / Transcribe`, and `Stop Voice`
while NPC speech is playing. The preferred path uses `AIVoiceCapture.gd`,
`AudioStreamMicrophone`, and a muted
`VoiceCapture` bus with `AudioEffectCapture`. It periodically converts frames
to mono signed PCM16 little-endian at the actual mix rate and sends binary
packets over:

```text
ws://127.0.0.1:8000/voice/session
```

The backend returns `transcript.final`, displays it visibly, and copies it into
the text field for confirmation or editing. By default it waits for manual
confirmation. `DialogueUI.voice_transcript_mode` can be set to `auto_send` to
start a short local countdown after a final transcript; the countdown emits the
same `message_submitted` signal as the Send button, so the text still travels
through WebSocket `player.text` or the existing HTTP fallback.

Transcript submission settings live on the canonical `DialogueUI` node:

```text
voice_transcript_mode = confirm | auto_send
voice_auto_send_delay_ms = 1200
```

`confirm` is the safe default. In `auto_send`, the transcript remains editable
and Send stays available. Editing the text or pressing Escape cancels automatic
submission for that turn and leaves the edited text ready for manual Send.
Pressing Send during the countdown submits immediately. Pressing Record during
a countdown cancels the pending transcript before starting a new turn. Closing
dialogue or losing the voice session also cancels any pending countdown.

`World.voice_transport` selects `websocket_stream` (the default) or `wav_http`.
If the preferred WebSocket session is unavailable, the existing WAV/HTTP path
remains available without creating another dialogue UI or NPC client.

The older `AIVoiceRecorder` remains as a connection fallback. It uses the
muted `Record` bus and `AudioEffectRecord`, writes a temporary 16-bit WAV, and
sends multipart field `file` to:

```text
http://127.0.0.1:8000/speech/transcribe
```

Both paths preserve typed input and use local loopback services only.

Start the backend in mock STT mode for the simplest test:

```powershell
cd backend
$env:STT_MODE = "mock"
uvicorn app.main:app --reload
```

Open dialogue with Aiko, select `Record`, speak briefly, then select
`Stop / Transcribe`. Windows, macOS, Linux, Android, and iOS may require
microphone permission in operating-system privacy settings. Exported mobile
builds also require the platform's microphone permission configuration.
On Windows, check `Settings > Privacy & security > Microphone` and allow
microphone access for desktop applications/Godot if the saved file is empty.
Godot logs the active input driver/device, capture bus/effect readiness,
available frames, and transmitted bytes. If no frames arrive, the UI points to
the selected system input device instead of showing a generic backend error.
Backend `no_speech_detected`, `malformed_audio`, `stt_unavailable`, and
`transcription_failed` codes are shown in the voice-status line rather than as
generic dialogue failures. Successful metadata is optional; older/local
backends that only return transcript text remain compatible.

Manual streaming follows `READY -> LISTENING -> TRANSCRIBING -> READY`.
Auto-send mode adds a UI-local `TRANSCRIPT_PENDING` step before the existing
`GENERATING` state. TTS playback uses `GENERATING -> SPEAKING -> READY`.
Audio input is mono signed PCM16 little-endian at the actual Godot mix rate.
The backend limits each utterance to 20 seconds and a format-derived byte
ceiling. Partial transcription, streaming TTS, continuous open microphone,
automatic microphone restart, and interruption remain deferred.

When the separately configured local Silero ONNX VAD is ready, Record changes
to `Listening...`, speech start/end events update the shared voice status, and
the backend sends `audio.auto_stopped` after sustained silence. Godot then
stops its microphone player without sending a duplicate `audio.stop` and waits
for the editable transcript. Manual Stop remains available. If VAD is disabled
or unavailable, the UI says `Automatic stopping unavailable - use Stop` and
the existing manual streaming flow continues unchanged.

When backend TTS is enabled, NPC text appears first as subtitles. The backend
then emits `npc.audio.ready`, and Godot fetches the generated WAV from:

```text
http://127.0.0.1:8000/tts/audio/{audio_id}
```

`World.gd` loads the PCM WAV bytes into the shared `NPCVoicePlayer`, plays the
response, shows `NPC is speaking...`, and sends `npc.audio.finished` when
playback ends or Stop Voice is pressed. Closing dialogue during playback stops
the audio, notifies the session, and keeps movement recovery on the existing
dialogue-close path.

## Architecture

```text
Godot level
    |
    v
NPC interaction
    |
    v
World persistent controller
    |
    +--> AIVoiceCapture --> AIVoiceSessionClient --> /voice/session (PCM + text)
    |                                           |
    |                                           +--> /tts/audio/{audio_id} (NPC WAV)
    |
    +--> AIBackendClient --> /npc/chat (connection fallback)
    |
    +--> AIBackendClient --> /speech/transcribe (recorded WAV)
    |
    +--> NPC profile JSON
    |
    +--> NPC private state and session
    |
    +--> Shared world facts
    |
    v
Reusable local Ollama model
```

Opening dialogue creates a fresh `default_save:<npc_id>` WebSocket session.
`AIVoiceSessionClient.gd` polls `WebSocketPeer`, validates JSON envelopes,
handles ping/pong, JSON events, and ordered binary audio without NPC UI
behavior. Typed Send uses `player.text`; `transcript.final` and
`npc.text.final` feed the existing UI/save flow. Closing dialogue stops capture
and sends `session.close`. If the socket fails, `/npc/chat` and recorded-WAV
transcription remain non-destructive fallbacks.

`World.tscn` keeps the canonical player, camera, dialogue UI, HTTP client,
WebSocket client, and microphone components alive. `LevelLoader.gd` replaces
only the JSON-driven terrain and props during a door transition. `GameState` is
an autoload, so its plain dictionaries survive level changes.

## Levels And Doors

- `levels/farm.json`: original farm and the entrance to the AI clearing.
- `levels/level_01.json`: Aiko's clearing, farm return, and market entrance.
- `levels/level_02.json`: Haru, Emi, and the return to Aiko's clearing.
- `levels/house_interior.json`: farmhouse interior and farm return.
- `scripts/LevelLoader.gd`: the canonical JSON level, exit, and spawn loader.

To add a spawn, add an entry to a level's `spawns` array and reference its ID
from an exit's `destination_spawn_id`. Keep spawns outside exit interaction
shapes to avoid immediate transition loops.

## NPC Profiles

All NPCs instantiate `scenes/characters/NPC.tscn` and select behavior through
the exported `npc_id`. Profiles are stored in:

```text
data/npcs/aiko.json
data/npcs/haru.json
data/npcs/emi.json
```

To add an NPC:

1. Add `<npc_id>.json` with a matching `"id"`.
2. Instance `NPC.tscn` in a level.
3. Set its exported `npc_id`.
4. The backend reads the same canonical profile directory.

Each frontend request uses `default_save:<npc_id>`. The backend also forces
session keys into an NPC namespace, preventing accidental cross-NPC history.

## State And Memory

`GameState.gd` separates:

- `player_state`: shared player progression.
- `npc_states[npc_id]`: relationship, summary, history, and private facts.
- `world_state.shared_facts`: facts visible to eligible NPCs.

Private history is sent only for the selected NPC. Shared facts support
`world` visibility now and include a path for `selected_npcs` visibility.
Backend updates are accepted only for the explicit `remember_fact` and
`shared_fact` types.

The game autosaves after successful dialogue and level transitions to:

```text
user://koto_dama_demo_save.json
```

On Windows this resolves under Godot's application data directory. Missing or
malformed saves fall back to defaults.

## Manual Test

1. Start on the farm and move with WASD or arrows.
2. Use the east door to enter Aiko's clearing and confirm the matching spawn.
3. Talk to Aiko and submit a memorable statement.
4. Close dialogue and use the market door with E.
5. Talk to Haru about buying quantities.
6. Talk to Emi about directions.
7. Use the return door.
8. Talk to Aiko and confirm the earlier conversation remains in the panel.
9. Restart the game and confirm the saved current level and histories reload.
10. With the backend running, confirm the panel changes from `Connecting...` to
    `Ready`, and typed dialogue arrives through the WebSocket.
11. Stop/restart the backend or point the session URL at an unused port; confirm
    the status shows `HTTP fallback` and `/npc/chat` still handles typed text.
12. Close and reopen dialogue and confirm a new clean session becomes ready.
13. Leave `DialogueUI.voice_transcript_mode` as `confirm`, speak a sentence,
    and confirm the transcript waits for manual Send.
14. Set `DialogueUI.voice_transcript_mode` to `auto_send`, speak a sentence,
    and confirm `Sending automatically in 1.2 seconds...` appears.
15. Let the countdown finish and confirm the transcript is sent once and the
    NPC replies.
16. Speak again, edit the transcript during the countdown, and confirm automatic
    send is cancelled with the edited text left in the input.
17. Press Send manually and confirm the edited text is sent once.
18. Close dialogue during a countdown and confirm no delayed message is sent and
    movement resumes.
19. Enable backend TTS (`TTS_MODE=mock` for smoke testing or `TTS_MODE=local`
    with a Piper voice), speak a full turn, and confirm subtitles appear before
    NPC audio starts.
20. Confirm the WAV is fetched locally from `/tts/audio/{audio_id}`, NPC speech
    plays, and the UI returns to `Voice: Ready`.
21. Repeat the spoken turn five times without reopening dialogue.
22. Press Stop Voice during playback and confirm recording is available again
    after the session returns to Ready.
23. Close dialogue during playback and confirm playback stops and movement
    resumes.

Haru should be formal and direct. Emi should be energetic and ask more
questions. Neither receives Aiko's private history.
