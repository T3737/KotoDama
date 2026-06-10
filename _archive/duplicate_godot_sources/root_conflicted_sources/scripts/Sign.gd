extends Interactable

@export var sign_text := "Welcome to the farm!"

func _ready() -> void:
	prompt_text = "Read  [E]"
	super._ready()

func _on_interact(_player: Node) -> void:
	print("Sign says: ", sign_text)
