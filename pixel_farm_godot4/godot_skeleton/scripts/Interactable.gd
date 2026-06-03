# Base class for anything the player can interact with.
# Extend this and override _on_interact(player) for custom behaviour.
class_name Interactable
extends Area2D

signal interacted(player)

# Text shown above the object when the player is in range.
@export var prompt_text := "Press E"

@onready var prompt_label: Label = $PromptLabel

func _ready() -> void:
	prompt_label.visible = false
	prompt_label.text = prompt_text
	body_entered.connect(_on_body_entered)
	body_exited.connect(_on_body_exited)

func show_prompt() -> void:
	prompt_label.visible = true

func hide_prompt() -> void:
	prompt_label.visible = false

# Called by Player when E is pressed and this is the active interactable.
func interact(player: Node) -> void:
	interacted.emit(player)
	_on_interact(player)

# Override in subclasses.
func _on_interact(_player: Node) -> void:
	pass

func _on_body_entered(body: Node) -> void:
	if body.is_in_group("player"):
		body.set_interactable(self)
		show_prompt()

func _on_body_exited(body: Node) -> void:
	if body.is_in_group("player"):
		body.clear_interactable(self)
		hide_prompt()
