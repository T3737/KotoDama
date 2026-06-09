extends Node

# Emitted when a level finishes loading.
signal level_loaded(level_id: String)

const TILE_COLORS := {
	"grass": Color(0.25, 0.55, 0.2),
	"dirt":  Color(0.55, 0.35, 0.15),
	"water": Color(0.15, 0.4,  0.75),
	"path":  Color(0.72, 0.62, 0.42),
}

# Source IDs in the TileSet — devs add atlas sources to match.
const TILE_SOURCE_IDS := {
	"grass": 0,
	"dirt":  1,
	"water": 2,
	"path":  3,
}

@export var tilemap_path:   NodePath
@export var props_path:     NodePath
@export var player_path:    NodePath
@export var music_player_path: NodePath

@onready var _tilemap:      TileMap      = get_node(tilemap_path)
@onready var _props:        Node2D       = get_node(props_path)
@onready var _player:       CharacterBody2D = get_node(player_path)
@onready var _music:        AudioStreamPlayer = get_node_or_null(music_player_path)

var _current_level_id := ""

func _ready() -> void:
	add_to_group("level_loader")

func load_level(path: String) -> void:
	var file := FileAccess.open(path, FileAccess.READ)
	if file == null:
		push_error("LevelLoader: cannot open " + path)
		return

	var json   := JSON.new()
	var result := json.parse(file.get_as_text())
	file.close()

	if result != OK:
		push_error("LevelLoader: JSON parse error in " + path)
		return

	var data: Dictionary = json.get_data()
	_current_level_id = data.get("id", "unknown")

	_clear()
	_build_tiles(data)
	_place_props(data)
	_set_spawn(data)
	_play_music(data)

	level_loaded.emit(_current_level_id)

# ── private ────────────────────────────────────────────────

func _clear() -> void:
	_tilemap.clear()
	for child in _props.get_children():
		child.queue_free()

func _build_tiles(data: Dictionary) -> void:
	var map: Dictionary = data.get("map", {})
	var w: int = map.get("width",  32)
	var h: int = map.get("height", 24)
	var hw := w / 2
	var hh := h / 2

	# grass base
	for x in range(-hw, hw):
		for y in range(-hh, hh):
			_tilemap.set_cell(0, Vector2i(x, y), TILE_SOURCE_IDS["grass"], Vector2i(0, 0))

	# overlay zones
	for zone in map.get("tiles", []):
		var src_id: int = TILE_SOURCE_IDS.get(zone["type"], 0)
		for x in range(zone["x"], zone["x"] + zone["w"]):
			for y in range(zone["y"], zone["y"] + zone["h"]):
				_tilemap.set_cell(0, Vector2i(x, y), src_id, Vector2i(0, 0))

func _place_props(data: Dictionary) -> void:
	for prop in data.get("props", []):
		match prop.get("type", ""):
			"house":  _make_interactable(prop)
			"sign":   _make_interactable(prop)
			"item":   _make_item(prop)
			"tree":   _make_colorect(prop)
			"npc":    _make_npc(prop)
			_:
				push_warning("LevelLoader: unknown prop type '%s'" % prop.get("type"))

func _make_interactable(prop: Dictionary) -> void:
	var area := Area2D.new()
	area.position = Vector2(prop["x"], prop["y"])
	area.collision_layer = 0
	area.collision_mask  = 1

	# sprite
	if prop.get("texture"):
		var sprite := Sprite2D.new()
		sprite.texture = load(prop["texture"])
		area.add_child(sprite)
	elif prop.get("color"):
		var cr := ColorRect.new()
		var c: Array = prop["color"]
		cr.color = Color(c[0], c[1], c[2])
		cr.offset_left   = -4.0; cr.offset_right  = 4.0
		cr.offset_top    = -10.0; cr.offset_bottom = 2.0
		area.add_child(cr)

	# collision
	var col := CollisionShape2D.new()
	var shape := RectangleShape2D.new()
	var cdata: Dictionary = prop.get("collision", {"w": 32, "h": 32})
	shape.size = Vector2(cdata.get("w", 32), cdata.get("h", 32))
	col.shape  = shape
	if cdata.has("offset_y"):
		col.position.y = cdata["offset_y"]
	area.add_child(col)

	# prompt label
	var label := Label.new()
	var interact: Dictionary = prop.get("interact", {})
	label.text    = interact.get("prompt", "Press E")
	label.visible = false
	label.add_theme_font_size_override("font_size", 6)
	label.offset_left = -32.0; label.offset_right  = 32.0
	label.offset_top  = -24.0; label.offset_bottom = -14.0
	label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	area.add_child(label)

	# wire signals
	area.body_entered.connect(_on_interactable_entered.bind(area, label, interact))
	area.body_exited.connect(_on_interactable_exited.bind(area, label))

	_props.add_child(area)

func _make_item(prop: Dictionary) -> void:
	var scene: PackedScene = load("res://scenes/Item.tscn")
	var item: Node = scene.instantiate()
	item.position      = Vector2(prop["x"], prop["y"])
	item.item_name     = prop.get("item_name", "Item")
	item.item_count    = prop.get("item_count", 1)
	if prop.has("color"):
		var c: Array = prop["color"]
		item.get_node("Sprite").color = Color(c[0], c[1], c[2])
	_props.add_child(item)

func _make_colorect(prop: Dictionary) -> void:
	var cr := ColorRect.new()
	var c: Array = prop.get("color", [0.5, 0.5, 0.5])
	cr.color        = Color(c[0], c[1], c[2])
	cr.offset_left  = prop["x"]
	cr.offset_top   = prop["y"]
	cr.offset_right = prop["x"] + prop.get("w", 16)
	cr.offset_bottom= prop["y"] + prop.get("h", 16)
	_props.add_child(cr)

func _make_npc(prop: Dictionary) -> void:
	# Placeholder — wire to dialogue system when ready.
	push_warning("LevelLoader: NPC placement not yet implemented for '%s'" % prop.get("id", "?"))

func _set_spawn(data: Dictionary) -> void:
	var spawn: Dictionary = data.get("spawn", {"x": 0, "y": 0})
	_player.global_position = Vector2(spawn["x"], spawn["y"])

func _play_music(data: Dictionary) -> void:
	if _music == null:
		return
	var track: String = data.get("music", "")
	if track == "":
		_music.stop()
		return
	if _music.stream == null or _music.stream.resource_path != track:
		_music.stream = load(track)
		_music.play()

# ── interaction callbacks ───────────────────────────────────

func _on_interactable_entered(body: Node, _area: Area2D, label: Label, interact: Dictionary) -> void:
	if not body.is_in_group("player"):
		return
	label.visible = true
	if body.has_method("set_interactable_data"):
		body.set_interactable_data(interact)

func _on_interactable_exited(body: Node, _area: Area2D, label: Label) -> void:
	if not body.is_in_group("player"):
		return
	label.visible = false
	if body.has_method("clear_interactable_data"):
		body.clear_interactable_data()