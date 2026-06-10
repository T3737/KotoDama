class_name AITestNPC
extends Interactable

signal dialogue_requested(npc_name: String)

@export var npc_name := "Aiko"

func _on_interact(_player: Node) -> void:
	dialogue_requested.emit(npc_name)
