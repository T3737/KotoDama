# KotoDama Two-Level Godot Demo

Godot 4.6 placeholder prototype with one persistent player, three data-driven
LLM NPCs, two levels, reusable doors, and JSON save data.

## Run

1. Start Ollama and the FastAPI backend as described in `backend/README.md`.
2. Open `pixel_farm_godot4/godot_skeleton/project.godot` in Godot 4.6.
3. Press F5, or open `scenes/AIDialogueDemo.tscn` and press F6.

Controls:

| Key | Action |
| --- | --- |
| WASD / Arrow keys | Move |
| E | Talk or use a door |
| Enter | Submit dialogue while the text box is focused |

## Voice Input Prototype

The isolated AI dialogue panel includes `Record` and `Stop / Transcribe`
buttons. Recording uses Godot's native `AudioStreamMicrophone`, routed through
the muted `Record` bus and its `AudioEffectRecord`. It writes a temporary
16-bit WAV to `user://voice_recording.wav` and sends it as multipart form field
`file` to:

```text
http://127.0.0.1:8000/speech/transcribe
```

The returned English transcript is shown in the voice status line and copied
into the existing text field for editing before it is sent to `/npc/chat`.

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

## Architecture

```text
Godot level
    |
    v
NPC interaction
    |
    v
AIDialogueDemo persistent controller
    |
    v
FastAPI /npc/chat
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

`AIDialogueDemo.tscn` keeps the player, dialogue UI, HTTP client, and
`LevelContainer` alive. Only the child level scene is replaced during a door
transition. `GameState` is an autoload, so its plain dictionaries survive level
changes.

## Levels And Doors

- `scenes/levels/level_01.tscn`: Aiko and the Level 2 door.
- `scenes/levels/level_02.tscn`: Haru, Emi, and the Level 1 return door.
- `scenes/objects/SceneDoor.tscn`: reusable interaction-based door.
- `scripts/SceneDoor.gd`: exports `destination_scene`,
  `destination_spawn_id`, and `interaction_required`.

To add a spawn, add a `Marker2D` with `SpawnPoint.gd`, assign a unique
`spawn_id`, then set the destination door's `destination_spawn_id` to that
value. Spawn markers should be placed outside the destination door's
interaction shape to avoid transition loops.

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

1. Start in Level 1 and move with WASD or arrows.
2. Talk to Aiko and submit a memorable statement.
3. Close dialogue and use the Level 2 door with E.
4. Confirm the player appears at the Level 2 entrance.
5. Talk to Haru about buying quantities.
6. Talk to Emi about directions.
7. Use the return door.
8. Talk to Aiko and confirm the earlier conversation remains in the panel.
9. Restart the game and confirm the saved current level and histories reload.

Haru should be formal and direct. Emi should be energetic and ask more
questions. Neither receives Aiko's private history.
