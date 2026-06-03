# Example interactable: a readable sign.
extends Interactable

@export var prompt_text := "Read sign  [E]"
@export var sign_text   := "Welcome to the farm!"

func _on_interact(_player: Node) -> void:
	# TODO: wire to a dialog system
	print("Sign says: ", sign_text)
