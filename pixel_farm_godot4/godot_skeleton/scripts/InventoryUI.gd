extends CanvasLayer

# Draws a simple item list when open. Toggle with "inventory_toggle" action (I key).
# Expects player in group "player" with child node "Inventory".

@onready var _panel: PanelContainer = $Panel
@onready var _list:  VBoxContainer  = $Panel/Margin/List

var _open := false

func _ready() -> void:
	_panel.visible = false

func _unhandled_input(event: InputEvent) -> void:
	if event.is_action_pressed("inventory_toggle"):
		_open = !_open
		_panel.visible = _open
		if _open:
			_refresh()
		get_viewport().set_input_as_handled()

func _refresh() -> void:
	for child in _list.get_children():
		child.queue_free()

	var players := get_tree().get_nodes_in_group("player")
	if players.is_empty():
		return
	var inv: Inventory = players[0].get_node_or_null("Inventory")
	if inv == null:
		return

	var items := inv.get_all()
	if items.is_empty():
		_add_row("(empty)")
		return
	for name in items:
		_add_row("%s  ×%d" % [name, items[name]])

func _add_row(text: String) -> void:
	var lbl := Label.new()
	lbl.text = text
	lbl.add_theme_font_size_override("font_size", 6)
	_list.add_child(lbl)
