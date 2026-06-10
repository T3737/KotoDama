extends CharacterBody2D

@export var movement_speed := 80.0
@export var movement_bounds := Rect2(8.0, 18.0, 304.0, 154.0)

var _interactable: Interactable
var _movement_enabled := true
var _was_moving := false

func _ready() -> void:
	add_to_group("player")
	print("AI demo player ready")

func _physics_process(_delta: float) -> void:
	if not _movement_enabled:
		velocity = Vector2.ZERO
		_was_moving = false
		return

	var direction := Input.get_vector(
		"demo_move_left",
		"demo_move_right",
		"demo_move_up",
		"demo_move_down"
	)
	if direction != Vector2.ZERO and not _was_moving:
		print("AI demo movement input detected: ", direction)
		_was_moving = true
	if direction == Vector2.ZERO:
		_was_moving = false

	velocity = direction.normalized() * movement_speed
	move_and_slide()
	global_position = global_position.clamp(
		movement_bounds.position,
		movement_bounds.end
	)

func _unhandled_input(event: InputEvent) -> void:
	if not _movement_enabled or not event.is_action_pressed("demo_interact"):
		return

	print("AI demo interaction key pressed")
	if _interactable != null:
		_interactable.interact(self)

func set_interactable(interactable: Interactable) -> void:
	_interactable = interactable

func clear_interactable(interactable: Interactable) -> void:
	if _interactable == interactable:
		_interactable = null

func set_movement_enabled(enabled: bool) -> void:
	_movement_enabled = enabled
	if not enabled:
		velocity = Vector2.ZERO
		_was_moving = false

func is_movement_enabled() -> bool:
	return _movement_enabled
