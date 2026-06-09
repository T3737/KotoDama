# Inventory: holds item name → count dict.
# Attach to Player or autoload as needed.
class_name Inventory
extends Node

signal changed

var _items: Dictionary = {}

func add(item_name: String, amount: int = 1) -> void:
	_items[item_name] = _items.get(item_name, 0) + amount
	changed.emit()

func remove(item_name: String, amount: int = 1) -> bool:
	if not has(item_name, amount):
		return false
	_items[item_name] -= amount
	if _items[item_name] <= 0:
		_items.erase(item_name)
	changed.emit()
	return true

func has(item_name: String, amount: int = 1) -> bool:
	return _items.get(item_name, 0) >= amount

func get_all() -> Dictionary:
	return _items.duplicate()
