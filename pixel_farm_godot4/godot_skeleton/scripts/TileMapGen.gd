extends TileMap

# Tile source IDs — match the TileSet defined in World.tscn
const GRASS  := 0
const DIRT   := 1
const WATER  := 2
const PATH   := 3

# Map bounds (in tiles)
const MAP_W := 32
const MAP_H := 24

func _ready() -> void:
	_generate()

func _generate() -> void:
	# 1. Fill everything with grass
	for x in range(-MAP_W / 2, MAP_W / 2):
		for y in range(-MAP_H / 2, MAP_H / 2):
			set_cell(0, Vector2i(x, y), GRASS, Vector2i(0, 0))

	# 2. Dirt farm plot (centre-left)
	for x in range(-10, -2):
		for y in range(-4, 4):
			set_cell(0, Vector2i(x, y), DIRT, Vector2i(0, 0))

	# 3. Water strip (right edge)
	for y in range(-MAP_H / 2, MAP_H / 2):
		for x in range(12, 15):
			set_cell(0, Vector2i(x, y), WATER, Vector2i(0, 0))

	# 4. Dirt path from spawn down to farm plot
	for x in range(-2, 1):
		for y in range(-MAP_H / 2, MAP_H / 2):
			set_cell(0, Vector2i(x, y), PATH, Vector2i(0, 0))
