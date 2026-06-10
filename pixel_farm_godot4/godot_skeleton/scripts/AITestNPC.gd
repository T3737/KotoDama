class_name AITestNPC
extends Interactable

signal dialogue_requested(npc_name: String)

@export var npc_name := "Aiko"

func _on_interact(_player: Node) -> void:
	dialogue_requested.emit(npc_name)

func _on_body_entered(body: Node) -> void:
	super._on_body_entered(body)
	if body.is_in_group("player"):
		print("Player entered Aiko's interaction range")

func _on_body_exited(body: Node) -> void:
	super._on_body_exited(body)
	if body.is_in_group("player"):
		print("Player left Aiko's interaction range")
