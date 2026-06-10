class_name SceneDoor
extends Interactable

signal transition_requested(destination_scene: String, destination_spawn_id: String)

@export_file("*.tscn") var destination_scene: String
@export var destination_spawn_id := ""
@export var interaction_required := false

var _transition_pending := false

func _ready() -> void:
	super._ready()
	add_to_group("scene_door")

func _on_interact(_player: Node) -> void:
	if interaction_required:
		_request_transition()

func _on_body_entered(body: Node) -> void:
	super._on_body_entered(body)
	if body.is_in_group("player") and not interaction_required:
		_request_transition()

func _request_transition() -> void:
	if _transition_pending:
		return
	if destination_scene.is_empty() or destination_spawn_id.is_empty():
		push_error("Door is missing a destination scene or spawn ID.")
		return
	_transition_pending = true
	transition_requested.emit(destination_scene, destination_spawn_id)
