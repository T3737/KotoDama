extends CharacterBody2D

const SPEED := 80.0

@onready var sprite: ColorRect     = $Sprite
@onready var anim:   AnimationPlayer = $AnimationPlayer

var facing           := Vector2.DOWN
var _interactable: Interactable = null   # closest interactable in range

func _ready() -> void:
	add_to_group("player")

func _physics_process(_delta: float) -> void:
	var dir := Vector2(
		Input.get_axis("ui_left",  "ui_right"),
		Input.get_axis("ui_up",    "ui_down"),
	)

	if dir != Vector2.ZERO:
		facing = dir
		velocity = dir.normalized() * SPEED
		_play_walk(dir)
	else:
		velocity = Vector2.ZERO
		anim.play("idle_" + _dir_name(facing))

	move_and_slide()

func _unhandled_input(event: InputEvent) -> void:
	if event.is_action_pressed("interact") and _interactable != null:
		_interactable.interact(self)

# Called by Interactable when the player enters its area.
func set_interactable(obj: Interactable) -> void:
	_interactable = obj

# Called by Interactable when the player leaves its area.
# Only clears if it's still the active one (handles overlapping zones).
func clear_interactable(obj: Interactable) -> void:
	if _interactable == obj:
		_interactable = null

func _dir_name(d: Vector2) -> String:
	if abs(d.x) >= abs(d.y):
		return "side"
	return "down" if d.y >= 0 else "up"

func _play_walk(d: Vector2) -> void:
	var anim_name := "walk_" + _dir_name(d)
	if anim.current_animation != anim_name:
		anim.play(anim_name)
	sprite.scale.x = -1.0 if d.x < 0 else 1.0
