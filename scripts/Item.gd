extends Area2D

@export var item_name  := "Item"
@export var item_count := 1

@onready var _label: Label = $PromptLabel

func _ready() -> void:
	_label.text = "Pick up %s  [E]" % item_name
	_label.visible = false
	body_entered.connect(_on_body_entered)
	body_exited.connect(_on_body_exited)

func _on_body_entered(body: Node) -> void:
	if body.is_in_group("player"):
		_label.visible = true
		body.set_interactable_data({"action": "pickup", "node": self})

func _on_body_exited(body: Node) -> void:
	if body.is_in_group("player"):
		_label.visible = false
		body.clear_interactable_data()

func pickup(player: Node) -> void:
	if player.has_node("Inventory"):
		player.get_node("Inventory").add(item_name, item_count)
	queue_free()