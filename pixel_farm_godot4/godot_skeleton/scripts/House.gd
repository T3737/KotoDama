# Example interactable: the farmhouse door.
# Extend _on_interact to open a menu, trigger a scene change, etc.
extends Interactable

@export var prompt_text := "Enter house  [E]"

func _on_interact(_player: Node) -> void:
	# TODO: transition to interior scene
	print("Player entered the house!")
