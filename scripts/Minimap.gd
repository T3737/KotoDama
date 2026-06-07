extends CanvasLayer

# Minimap + full-screen map toggle (press M).
# Draws fixed terrain zones that match TileMapGen layout.
# No SubViewport — pure _draw() on a Control node.

const TILE  := 16          # world pixels per tile
const MAP_W := 32          # tiles wide (must match TileMapGen)
const MAP_H := 24          # tiles tall

const MINI_SCALE  := 2.0   # minimap pixels per tile
const FULL_SCALE  := 5.0   # full-map pixels per tile
const MARGIN      := 6.0   # screen-edge margin

@export var player_path: NodePath

@onready var _canvas: Control = $MapCanvas

var _full_open := false
var _player: Node2D = null

# Terrain zone colors
const C_GRASS := Color(0.25, 0.55, 0.2)
const C_DIRT  := Color(0.55, 0.35, 0.15)
const C_WATER := Color(0.15, 0.4,  0.75)
const C_PATH  := Color(0.72, 0.62, 0.42)
const C_HOUSE := Color(0.7,  0.4,  0.2)
const C_TREE  := Color(0.1,  0.4,  0.1)
const C_PLAYER:= Color(1.0,  0.9,  0.1)
const C_BG    := Color(0.05, 0.05, 0.05, 0.82)

func _ready() -> void:
	_player = get_node_or_null(player_path)
	if _player == null:
		# fallback: find player by group at runtime
		pass
	_canvas.draw.connect(_on_draw)
	_canvas.set_process(true)

func _process(_delta: float) -> void:
	if _player == null:
		var players := get_tree().get_nodes_in_group("player")
		if players.size() > 0:
			_player = players[0]
	_canvas.queue_redraw()

func _unhandled_input(event: InputEvent) -> void:
	if event.is_action_pressed("map_toggle"):
		_full_open = !_full_open
		_canvas.queue_redraw()
		get_viewport().set_input_as_handled()

func _on_draw() -> void:
	var scale := MINI_SCALE if not _full_open else FULL_SCALE
	var map_px_w := MAP_W * scale
	var map_px_h := MAP_H * scale
	var vp := get_viewport().get_visible_rect().size

	var origin: Vector2
	if _full_open:
		origin = (vp - Vector2(map_px_w, map_px_h)) / 2.0
		# dim background
		_canvas.draw_rect(Rect2(Vector2.ZERO, vp), Color(0, 0, 0, 0.55))
	else:
		# bottom-right corner
		origin = Vector2(vp.x - map_px_w - MARGIN, vp.y - map_px_h - MARGIN)

	# background
	_canvas.draw_rect(Rect2(origin, Vector2(map_px_w, map_px_h)), C_BG)

	# helper: world-tile to map-pixel
	var half_w := MAP_W / 2
	var half_h := MAP_H / 2

	# 1. grass base
	_canvas.draw_rect(Rect2(origin, Vector2(map_px_w, map_px_h)), C_GRASS)

	# 2. dirt farm plot  x:-10..-2  y:-4..4
	_draw_zone(origin, scale, half_w, half_h, -10, -4, 8, 8, C_DIRT)

	# 3. water strip     x:12..15
	_draw_zone(origin, scale, half_w, half_h, 12, -half_h, 3, MAP_H, C_WATER)

	# 4. path            x:-2..1
	_draw_zone(origin, scale, half_w, half_h, -2, -half_h, 3, MAP_H, C_PATH)

	# 5. house           world pos (-140, 60) → tile (-9, 4)
	_draw_zone(origin, scale, half_w, half_h, -9, 3, 3, 2, C_HOUSE)

	# 6. trees (approx tile positions)
	for tp in [Vector2i(5, -4), Vector2i(-8, -5), Vector2i(10, 3)]:
		_draw_zone(origin, scale, half_w, half_h, tp.x, tp.y, 1, 1, C_TREE)

	# 7. player dot
	if _player != null:
		var tx := _player.global_position.x / TILE
		var ty := _player.global_position.y / TILE
		var px := origin + Vector2((tx + half_w) * scale, (ty + half_h) * scale)
		var r: float = max(1.5, scale * 0.4)
		_canvas.draw_circle(px, r, C_PLAYER)

	# label when full map open
	if _full_open:
		_canvas.draw_string(
			ThemeDB.fallback_font,
			origin + Vector2(2, -2),
			"MAP  [M] close",
			HORIZONTAL_ALIGNMENT_LEFT, -1, 7,
			Color.WHITE
		)

func _draw_zone(origin: Vector2, scale: float,
		half_w: int, half_h: int,
		tx: int, ty: int, tw: int, th: int, color: Color) -> void:
	var r := Rect2(
		origin + Vector2((tx + half_w) * scale, (ty + half_h) * scale),
		Vector2(tw * scale, th * scale)
	)
	_canvas.draw_rect(r, color)
