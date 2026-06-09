extends Node2D

func _ready() -> void:
	$LevelLoader.load_level("res://levels/farm.json")