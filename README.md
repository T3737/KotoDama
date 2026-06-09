# PixelFarm – Godot 4 Skeleton

Stardew-style 2D top-down skeleton. Placeholder colored rectangles stand in for sprites.

## Setup

1. Open **Godot 4.2+** → Import Project → select this folder
2. Let the editor import assets (a few seconds)
3. Press **F5** to run — World.tscn is the main scene
4. **Alt+F4** (Win/Linux) or **Cmd+Q** (Mac) to close the game window

## Controls

| Key | Action |
|-----|--------|
| WASD / Arrow keys | Move player |

## Structure

```
project.godot             320×180 viewport, pixel-perfect stretch
scenes/
  World.tscn              Main scene: TileMap terrain + props + player
  Player.tscn             CharacterBody2D + ColorRect sprite + AnimationPlayer
scripts/
  World.gd                Entry point
  Player.gd               4-directional movement, anim state machine
  Camera.gd               Smooth-follow, zoom ×3
  TileMapGen.gd           Fills TileMap on _ready() with a basic farm layout
```

## Terrain layout (TileMapGen.gd)

| Tile | Color placeholder | Area |
|------|-------------------|------|
| Grass | green | everywhere by default |
| Dirt | brown | farm plot, centre-left |
| Water | blue | right edge strip |
| Path | tan | vertical strip through centre |

## Replacing placeholders

- Open the `TileSet` resource on the `TerrainMap` node
- Add a real spritesheet texture to each `TileSetAtlasSource`
- Swap `ColorRect` → `Sprite2D` on trees/house with pixel art

## Next steps

- [ ] AnimationPlayer walk/idle cycles on Player
- [ ] Interactable system (house door, objects)
- [ ] Inventory / farming layer

# physical_keycode 77 = M key



# google docs file link https://docs.google.com/document/d/1-Ybr-x5MpH9judzUkSj7vjGYehk7RrHmpbAa9yTn4U4/edit?usp=sharing
