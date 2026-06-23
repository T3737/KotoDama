extends CanvasLayer

const TILE  := 64
const MINI_SCALE  := 2.0
const FULL_SCALE  := 5.0
const MARGIN      := 6.0

@export var player_path: NodePath

@onready var _canvas: Control = $MapCanvas

var _full_open := false
var _player: Node2D = null
var _map_w := 32
var _map_h := 24
var _tiles: Array = []
var _exits: Array = []

const C_GRASS := Color(0.25, 0.55, 0.2)
const C_DIRT  := Color(0.55, 0.35, 0.15)
const C_WATER := Color(0.15, 0.4,  0.75)
const C_PATH  := Color(0.72, 0.62, 0.42)
const C_PLAYER:= Color(1.0,  0.9,  0.1)
const C_BG    := Color(0.05, 0.05, 0.05, 0.82)
const C_NPC := Color(1.0, 0.4, 0.4)

const TILE_COLORS := {
	"grass": C_GRASS,
	"dirt":  C_DIRT,
	"water": C_WATER,
	"path":  C_PATH,
}

const C_EXIT := Color(0.68, 0.38, 0.16, 1)

func _ready() -> void:
	_player = get_node_or_null(player_path)
	_canvas.draw.connect(_on_draw)
	_canvas.set_process(true)
	# Connect to LevelLoader if present
	var loaders := get_tree().get_nodes_in_group("level_loader")
	if loaders.size() > 0:
		loaders[0].level_loaded.connect(_on_level_loaded)
		_sync_level_data(loaders[0])

func _on_level_loaded(_level_id: String) -> void:
	var loaders := get_tree().get_nodes_in_group("level_loader")
	if loaders.size() > 0:
		_sync_level_data(loaders[0])

func _sync_level_data(loader: Node) -> void:
	_tiles = loader.current_level_tiles
	_exits = loader.current_level_exits
	_canvas.queue_redraw()

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
	var map_px_w := _map_w * scale
	var map_px_h := _map_h * scale
	var vp := get_viewport().get_visible_rect().size

	var origin: Vector2
	if _full_open:
		origin = (vp - Vector2(map_px_w, map_px_h)) / 2.0
		_canvas.draw_rect(Rect2(Vector2.ZERO, vp), Color(0, 0, 0, 0.55))
	else:
		origin = Vector2(vp.x - map_px_w - MARGIN, vp.y - map_px_h - MARGIN)

	var half_w := _map_w / 2
	var half_h := _map_h / 2

	# Grass base
	_canvas.draw_rect(Rect2(origin, Vector2(map_px_w, map_px_h)), C_GRASS)

	# JSON-driven zones
	for zone in _tiles:
		if not zone is Dictionary:
			continue
		var color: Color = TILE_COLORS.get(zone.get("type", ""), C_GRASS)
		_draw_zone(origin, scale, half_w, half_h,
			zone.get("x", 0), zone.get("y", 0),
			zone.get("w", 1), zone.get("h", 1), color)

	# Exit markers
	for exit in _exits:
		if not exit is Dictionary:
			continue
		var tx := float(exit.get("x", 0)) / TILE
		var ty := float(exit.get("y", 0)) / TILE
		var px := origin + Vector2((tx + half_w) * scale, (ty + half_h) * scale)
		_canvas.draw_rect(Rect2(px - Vector2(scale, scale), Vector2(scale * 2, scale * 2)), C_EXIT)

	# NPC dots
	for npc in get_tree().get_nodes_in_group("ai_npc"):
		var ntx := float(npc.global_position.x) / TILE
		var nty := float(npc.global_position.y) / TILE
		var npx := origin + Vector2((ntx + half_w) * scale, (nty + half_h) * scale)
		var nr: float = max(1.5, scale * 0.35)
		_canvas.draw_circle(npx, nr, C_NPC)

	# Player dot
	if _player != null:
		var tx := _player.global_position.x / TILE
		var ty := _player.global_position.y / TILE
		var px := origin + Vector2((tx + half_w) * scale, (ty + half_h) * scale)
		var r: float = max(1.5, scale * 0.4)
		_canvas.draw_circle(px, r, C_PLAYER)

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