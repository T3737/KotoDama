extends CharacterBody2D

const SPEED := 80.0

var _interactable: Interactable

func _ready() -> void:
	add_to_group("player")

func _physics_process(_delta: float) -> void:
	var direction := Input.get_vector("ui_left", "ui_right", "ui_up", "ui_down")
	velocity = direction * SPEED
	move_and_slide()

func _unhandled_input(event: InputEvent) -> void:
	if event.is_action_pressed("interact") and _interactable != null:
		_interactable.interact(self)

func set_interactable(interactable: Interactable) -> void:
	_interactable = interactable

func clear_interactable(interactable: Interactable) -> void:
	if _interactable == interactable:
		_interactable = null
