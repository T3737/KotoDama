# Godot Project Cleanup Report

Date: 2026-06-10

## Canonical Project

The canonical Godot 4 project is:

`pixel_farm_godot4/godot_skeleton/`

Open `pixel_farm_godot4/godot_skeleton/project.godot` in Godot 4.6 going
forward. Its main scene remains `scenes/AIDialogueDemo.tscn`.

## Project Roots Found

- Repository root (`project.godot`)
- `pixel_farm_godot4/godot_skeleton/project.godot`

The nested project was selected because it contains the working AI dialogue
demo, current AI scripts, data-driven NPC profiles, two-level demo, persistent
game state, and the most complete current frontend structure.

## Moved Into The Canonical Project

- Root `assets/` to `pixel_farm_godot4/godot_skeleton/assets/`
- Root `levels/farm.json` to
  `pixel_farm_godot4/godot_skeleton/levels/farm.json`
- Inventory, item, minimap, stamina, and level-loader scripts and their
  valid `.gd.uid` files to the canonical `scripts/` directory
- Inventory, item, minimap, and stamina scenes to the canonical `scenes/`
  directory

The farm `Player.gd`, `World.gd`, `Player.tscn`, and `World.tscn` at the
repository root contained committed merge-conflict markers. Valid versions
were recovered from Git revision `815e1b4`, cleaned, and installed in the
canonical project. The previously empty `StaminaBar.tscn` was completed so the
recovered farm scene has valid node references.

The canonical `project.godot` was changed only to retain the AI demo as the
main scene while adding the farm systems' `interact`, `map_toggle`,
`inventory_toggle`, and `sprint` input actions.

## Archived

- Raw conflicted root farm files:
  `_archive/duplicate_godot_sources/root_conflicted_sources/`
- Original nested placeholder farm variant:
  `_archive/duplicate_godot_sources/nested_legacy_farm/`
- Root project configuration and README:
  `_archive/duplicate_godot_sources/root_project_files/`
- Git installer:
  `_archive/non_project_files/Git-2.54.0-64-bit.exe`

The archived root project file was renamed to `project.godot.root-copy` so it
is preserved without being detected as another active Godot project.

## Removed

- Identical root copies of `icon.svg`, `icon.svg.import`, shared scripts,
  shared `.gd.uid` files, and `Interactable.tscn`
- The zero-byte `LevelLoader.gd.uid`; it contained no UID and no scene
  referenced `LevelLoader.gd` by UID
- Tracked `pixel_farm_godot4/godot_skeleton/.godot/` editor/import/shader
  cache
- Tracked backend `__pycache__/` directories and `.pyc` files

No backend source code or endpoint behavior was changed.

## Ignore Rules

The root `.gitignore` now ignores:

- `.godot/`
- `**/.godot/`
- `backend/.venv/`
- `**/__pycache__/`
- `*.pyc`

## AI Demo Preservation

The following remain in the canonical project:

- `scenes/AIDialogueDemo.tscn`
- `scripts/AIBackendClient.gd`
- `scripts/AIDemoPlayer.gd`
- `scripts/AIDialogueDemo.gd`
- `scripts/AIDialogueUI.gd`
- `scripts/AITestNPC.gd`

The backend endpoint remains:

`http://127.0.0.1:8000/npc/chat`

The demo scene still contains its persistent player, dialogue UI, backend
client, and level container. Level 1 still contains Aiko.

## Validation

- Exactly one active `project.godot` remains.
- No merge-conflict markers remain in the canonical project.
- Canonical `res://` script, scene, data, icon, and asset references resolve.
- Every retained canonical `.gd.uid` is non-empty, well formed, and has its
  corresponding `.gd` script.
- Required AI demo and major farm-system files are present.
- Godot command-line validation was not available on this machine.

## Manual Review

Open `pixel_farm_godot4/godot_skeleton/project.godot` in Godot 4.6 and let it
rebuild `.godot/` and imported textures. Run the AI demo with F5. The recovered
optional farm scene at `scenes/World.tscn` should also be opened once to verify
the inventory, minimap, stamina, level loader, and placeholder textures in the
editor.

The archived variants remain available if visual or interaction details from
the old placeholder farm need to be restored later.
