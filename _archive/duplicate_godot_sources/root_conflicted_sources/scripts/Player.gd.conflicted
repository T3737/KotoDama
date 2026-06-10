extends CharacterBody2D

<<<<<<< HEAD
const SPEED := 80.0

@onready var sprite: ColorRect     = $Sprite
@onready var anim:   AnimationPlayer = $AnimationPlayer

var facing           := Vector2.DOWN
var _interactable: Interactable = null   # closest interactable in range

func _ready() -> void:
	add_to_group("player")

func _physics_process(_delta: float) -> void:
=======
const SPEED        := 80.0
const SPRINT_SPEED := 140.0
const STAMINA_MAX  := 100.0
const STAMINA_DRAIN := 30.0   # per second sprinting
const STAMINA_REGEN := 20.0   # per second not sprinting

@onready var sprite: ColorRect       = $Sprite
@onready var anim:   AnimationPlayer = $AnimationPlayer
@onready var _stamina_bar = null

var facing             := Vector2.DOWN
var _interact_data: Dictionary = {}
var _stamina := STAMINA_MAX

func _ready() -> void:
	add_to_group("player")
	# defer so World is ready
	call_deferred("_find_stamina_bar")

func _find_stamina_bar() -> void:
	var bars := get_tree().get_nodes_in_group("stamina_bar")
	if bars.size() > 0:
		_stamina_bar = bars[0]

func _physics_process(delta: float) -> void:
>>>>>>> 815e1b43d5dcaf5d5c61c16c137340871972938f
	var dir := Vector2(
		Input.get_axis("ui_left",  "ui_right"),
		Input.get_axis("ui_up",    "ui_down"),
	)

<<<<<<< HEAD
	if dir != Vector2.ZERO:
		facing = dir
		velocity = dir.normalized() * SPEED
=======
	var sprinting := Input.is_action_pressed("sprint") and _stamina > 0.0
	var speed := SPRINT_SPEED if sprinting else SPEED

	if sprinting:
		_stamina = max(0.0, _stamina - STAMINA_DRAIN * delta)
	else:
		_stamina = min(STAMINA_MAX, _stamina + STAMINA_REGEN * delta)

	if dir != Vector2.ZERO:
		facing = dir
		velocity = dir.normalized() * speed
>>>>>>> 815e1b43d5dcaf5d5c61c16c137340871972938f
		_play_walk(dir)
	else:
		velocity = Vector2.ZERO
		anim.play("idle_" + _dir_name(facing))
<<<<<<< HEAD

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
=======
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
>>>>>>> 815e1b43d5dcaf5d5c61c16c137340871972938f

func _dir_name(d: Vector2) -> String:
	if abs(d.x) >= abs(d.y):
		return "side"
	return "down" if d.y >= 0 else "up"

func _play_walk(d: Vector2) -> void:
	var anim_name := "walk_" + _dir_name(d)
	if anim.current_animation != anim_name:
		anim.play(anim_name)
<<<<<<< HEAD
	sprite.scale.x = -1.0 if d.x < 0 else 1.0
=======
	sprite.scale.x = -1.0 if d.x < 0 else 1.0
>>>>>>> 815e1b43d5dcaf5d5c61c16c137340871972938f
