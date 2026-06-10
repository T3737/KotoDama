extends CharacterBody2D

const SPEED := 80.0
const SPRINT_SPEED := 140.0
const STAMINA_MAX := 100.0
const STAMINA_DRAIN := 30.0
const STAMINA_REGEN := 20.0

@onready var sprite: ColorRect = $Sprite
@onready var anim: AnimationPlayer = $AnimationPlayer

var facing := Vector2.DOWN
var _interact_data: Dictionary = {}
var _stamina := STAMINA_MAX
var _stamina_bar: Node = null


func _ready() -> void:
	add_to_group("player")
	call_deferred("_find_stamina_bar")


func _find_stamina_bar() -> void:
	_stamina_bar = get_tree().get_first_node_in_group("stamina_bar")


func _physics_process(delta: float) -> void:
	var direction := Vector2(
		Input.get_axis("ui_left", "ui_right"),
		Input.get_axis("ui_up", "ui_down"),
	)
	var sprinting := Input.is_action_pressed("sprint") and _stamina > 0.0
	var speed := SPRINT_SPEED if sprinting else SPEED

	if sprinting:
		_stamina = max(0.0, _stamina - STAMINA_DRAIN * delta)
	else:
		_stamina = min(STAMINA_MAX, _stamina + STAMINA_REGEN * delta)

	if direction != Vector2.ZERO:
		facing = direction
		velocity = direction.normalized() * speed
		_play_walk(direction)
	else:
		velocity = Vector2.ZERO
		anim.play("idle_" + _dir_name(facing))

	if _stamina_bar:
		_stamina_bar.update(_stamina)
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
		"pickup":
			data["node"].pickup(self)
		"show_text":
			print(data.get("text", "..."))
		"enter_house":
			var loader := get_tree().get_first_node_in_group("level_loader")
			if loader:
				loader.load_level("res://levels/" + data["target_level"] + ".json")


func _dir_name(direction: Vector2) -> String:
	if abs(direction.x) >= abs(direction.y):
		return "side"
	return "down" if direction.y >= 0 else "up"


func _play_walk(direction: Vector2) -> void:
	var animation_name := "walk_" + _dir_name(direction)
	if anim.current_animation != animation_name:
		anim.play(animation_name)
	sprite.scale.x = -1.0 if direction.x < 0 else 1.0
