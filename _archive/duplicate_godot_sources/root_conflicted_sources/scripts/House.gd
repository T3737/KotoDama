extends Interactable

func _ready() -> void:
	prompt_text = "Enter house  [E]"
	super._ready()

func _on_interact(_player: Node) -> void:
	print("Player entered the house!")
