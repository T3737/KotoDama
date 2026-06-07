# A world item the player can pick up by pressing E.
extends Interactable

@export var item_name  := "Item"
@export var item_count := 1

func _ready() -> void:
	prompt_text = "Pick up %s  [E]" % item_name
	super._ready()

func _on_interact(player: Node) -> void:
	if player.has_node("Inventory"):
		player.get_node("Inventory").add(item_name, item_count)
	queue_free()
