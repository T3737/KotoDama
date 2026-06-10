extends Node

const SAVE_VERSION := 1
const SAVE_PATH := "user://koto_dama_demo_save.json"
const DEFAULT_LEVEL := "level_01"
const DEFAULT_SPAWN := "level_01_start"

var current_level_id := DEFAULT_LEVEL
var destination_spawn_id := DEFAULT_SPAWN
var player_state: Dictionary = {}
var npc_states: Dictionary = {}
var world_state: Dictionary = {}

func _ready() -> void:
	reset_to_defaults()

func reset_to_defaults() -> void:
	current_level_id = DEFAULT_LEVEL
	destination_spawn_id = DEFAULT_SPAWN
	player_state = {
		"display_name": "",
		"language_level": 1,
		"known_words": [],
		"completed_topics": [],
		"flags": {},
	}
	npc_states = {}
	for npc_id in ["aiko", "haru", "emi"]:
		npc_states[npc_id] = _new_npc_state()
	world_state = {
		"shared_facts": [],
		"events": [],
		"flags": {},
	}

func get_npc_state(npc_id: String) -> Dictionary:
	if not npc_states.has(npc_id) or not npc_states[npc_id] is Dictionary:
		npc_states[npc_id] = _new_npc_state()
	return npc_states[npc_id]

func update_npc_state(npc_id: String, updates: Dictionary) -> void:
	var state := get_npc_state(npc_id)
	for key in updates:
		state[key] = updates[key]

func add_conversation_message(npc_id: String, role: String, content: String) -> void:
	var state := get_npc_state(npc_id)
	var history: Array = state.get("conversation_history", [])
	history.append({"role": role, "content": content})
	if history.size() > 20:
		history = history.slice(history.size() - 20)
	state["conversation_history"] = history

func add_private_npc_fact(npc_id: String, fact: Dictionary) -> void:
	var safe_fact := fact.duplicate(true)
	safe_fact["visibility"] = "private"
	safe_fact["owner"] = npc_id
	var state := get_npc_state(npc_id)
	var facts: Array = state.get("known_player_facts", [])
	if not facts.has(safe_fact):
		facts.append(safe_fact)
	state["known_player_facts"] = facts

func add_shared_world_fact(fact: Dictionary) -> void:
	var safe_fact := fact.duplicate(true)
	safe_fact["visibility"] = "world"
	var facts: Array = world_state.get("shared_facts", [])
	if not facts.has(safe_fact):
		facts.append(safe_fact)
	world_state["shared_facts"] = facts

func get_visible_world_facts(npc_id: String) -> Array:
	var visible: Array = []
	for fact in world_state.get("shared_facts", []):
		if not fact is Dictionary:
			continue
		var visibility := str(fact.get("visibility", "world"))
		if visibility == "world":
			visible.append(fact)
		elif visibility == "selected_npcs" and npc_id in fact.get("known_by", []):
			visible.append(fact)
	return visible

func set_destination_spawn(spawn_id: String) -> void:
	destination_spawn_id = spawn_id

func save_game() -> bool:
	var file := FileAccess.open(SAVE_PATH, FileAccess.WRITE)
	if file == null:
		push_error("Could not open save file for writing: %s" % SAVE_PATH)
		return false
	var data := {
		"save_version": SAVE_VERSION,
		"current_level_id": current_level_id,
		"destination_spawn_id": destination_spawn_id,
		"player_state": player_state,
		"npc_states": npc_states,
		"world_state": world_state,
	}
	file.store_string(JSON.stringify(data, "  "))
	return true

func load_game() -> bool:
	if not FileAccess.file_exists(SAVE_PATH):
		print("No save file found; starting with defaults.")
		return false
	var file := FileAccess.open(SAVE_PATH, FileAccess.READ)
	if file == null:
		push_warning("Could not open save file; starting with defaults.")
		return false
	var json := JSON.new()
	if json.parse(file.get_as_text()) != OK or not json.data is Dictionary:
		push_warning("Save file is malformed; starting with defaults.")
		reset_to_defaults()
		return false
	var parsed: Dictionary = json.data
	var save_version := int(parsed.get("save_version", SAVE_VERSION))
	if save_version != SAVE_VERSION:
		push_warning("Unsupported save version %d; attempting compatible defaults." % save_version)
	current_level_id = str(parsed.get("current_level_id", DEFAULT_LEVEL))
	destination_spawn_id = str(parsed.get("destination_spawn_id", DEFAULT_SPAWN))
	player_state = _dictionary_or_default(parsed.get("player_state"), player_state)
	npc_states = _dictionary_or_default(parsed.get("npc_states"), npc_states)
	world_state = _dictionary_or_default(parsed.get("world_state"), world_state)
	return true

func _new_npc_state() -> Dictionary:
	return {
		"relationship": 0,
		"conversation_summary": "",
		"conversation_history": [],
		"known_player_facts": [],
	}

func _dictionary_or_default(value: Variant, fallback: Dictionary) -> Dictionary:
	return value if value is Dictionary else fallback
