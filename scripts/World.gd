extends Node2D

<<<<<<< HEAD
# Entry point. Nothing special yet — extend for day/night, saving, etc.
func _ready() -> void:
	pass
=======
func _ready() -> void:
	$LevelLoader.load_level("res://levels/farm.json")
>>>>>>> 815e1b43d5dcaf5d5c61c16c137340871972938f
