class_name SpawnPoint
extends Marker2D

@export var spawn_id := ""

func _ready() -> void:
	add_to_group("level_spawn")
