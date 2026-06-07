extends Camera2D

# Smooth-follow the player. Assign target in World.tscn via inspector.
@export var target: Node2D
@export var smoothing := 6.0

func _process(delta: float) -> void:
	if target:
		global_position = global_position.lerp(target.global_position, smoothing * delta)
