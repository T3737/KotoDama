extends CharacterBody2D

const SPEED := 80.0

@onready var sprite: ColorRect       = $Sprite
@onready var anim:   AnimationPlayer = $AnimationPlayer

var facing             := Vector2.DOWN
var _interact_data: Dictionary = {}

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
	if event.is_action_pressed("interact") and not _interact_data.is_empty():
		_handle_interact(_interact_data)

func set_interactable_data(data: Dictionary) -> void:
	_interact_data = data

func clear_interactable_data() -> void:
	_interact_data = {}

func _handle_interact(data: Dictionary) -> void:
	match data.get("action", ""):
		"show_text":
			print(data.get("text", "..."))
		"enter_house":
			var loader := get_tree().get_first_node_in_group("level_loader")
			if loader:
				loader.load_level("res://levels/" + data["target_level"] + ".json")
		_:
			pass

func _dir_name(d: Vector2) -> String:
	if abs(d.x) >= abs(d.y):
		return "side"
	return "down" if d.y >= 0 else "up"

func _play_walk(d: Vector2) -> void:
	var anim_name := "walk_" + _dir_name(d)
	if anim.current_animation != anim_name:
		anim.play(anim_name)
	sprite.scale.x = -1.0 if d.x < 0 else 1.0