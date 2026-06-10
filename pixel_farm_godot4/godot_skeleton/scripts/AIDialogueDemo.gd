extends Node2D

const LEVEL_SCENES := {
	"level_01": "res://scenes/levels/level_01.tscn",
	"level_02": "res://scenes/levels/level_02.tscn",
}

@onready var level_container: Node2D = $LevelContainer
@onready var player = $Player
@onready var dialogue_ui: AIDialogueUI = $DialogueUI
@onready var backend_client: AIBackendClient = $AIBackendClient

var _current_level: Node2D
var _active_npc: Node
var _request_npc_id := ""
var _pending_player_text := ""
var _transitioning := false

func _ready() -> void:
	dialogue_ui.message_submitted.connect(_on_message_submitted)
	dialogue_ui.dialogue_closed.connect(_on_dialogue_closed)
	backend_client.response_received.connect(_on_response_received)
	backend_client.request_failed.connect(_on_request_failed)
	GameState.load_game()
	var level_id := GameState.current_level_id
	if not LEVEL_SCENES.has(level_id):
		level_id = "level_01"
	await _load_level(LEVEL_SCENES[level_id], GameState.destination_spawn_id)

func _load_level(scene_path: String, spawn_id: String) -> void:
	if not ResourceLoader.exists(scene_path):
		push_error("Missing destination scene: %s" % scene_path)
		player.set_movement_enabled(true)
		_transitioning = false
		return
	if _current_level != null:
		_current_level.queue_free()
		await _current_level.tree_exited
	var packed: PackedScene = load(scene_path)
	_current_level = packed.instantiate()
	level_container.add_child(_current_level)
	GameState.current_level_id = _current_level.level_id
	GameState.set_destination_spawn(spawn_id)
	_connect_level_components()
	var spawn: Node2D = _find_spawn(spawn_id)
	if spawn == null:
		push_warning("Missing spawn '%s'; using the first available spawn." % spawn_id)
		spawn = _find_spawn("")
	if spawn != null:
		player.global_position = spawn.global_position
	else:
		push_error("Level has no spawn markers: %s" % scene_path)
	player.clear_interactable(player._interactable)
	await get_tree().create_timer(0.2).timeout
	player.set_movement_enabled(true)
	_transitioning = false
	GameState.save_game()
	print("Loaded %s at spawn %s" % [GameState.current_level_id, spawn_id])

func _connect_level_components() -> void:
	for npc in get_tree().get_nodes_in_group("ai_npc"):
		if _current_level.is_ancestor_of(npc):
			npc.dialogue_requested.connect(_on_dialogue_requested)
	for door in get_tree().get_nodes_in_group("scene_door"):
		if _current_level.is_ancestor_of(door):
			door.transition_requested.connect(_on_transition_requested)

func _find_spawn(spawn_id: String) -> Node2D:
	var fallback: Node2D
	for spawn in get_tree().get_nodes_in_group("level_spawn"):
		if not _current_level.is_ancestor_of(spawn):
			continue
		if fallback == null:
			fallback = spawn
		if spawn_id.is_empty() or spawn.spawn_id == spawn_id:
			return spawn
	return fallback

func _on_transition_requested(destination_scene: String, spawn_id: String) -> void:
	if _transitioning:
		return
	if dialogue_ui.is_open():
		print("Door ignored while dialogue is open.")
		return
	_transitioning = true
	player.set_movement_enabled(false)
	var destination_level := _level_id_for_scene(destination_scene)
	if destination_level == "level_02":
		GameState.add_shared_world_fact({
			"fact": "The player has entered Level 2.",
			"source": "level_transition",
		})
	await _load_level(destination_scene, spawn_id)

func _on_dialogue_requested(npc: Node) -> void:
	if _transitioning or backend_client.is_busy():
		return
	_active_npc = npc
	var npc_state := GameState.get_npc_state(npc.npc_id)
	player.set_movement_enabled(false)
	dialogue_ui.open_dialogue(
		str(npc.profile.get("display_name", npc.npc_id)),
		npc_state.get("conversation_history", []),
		str(npc.profile.get("greeting", "Hello."))
	)
	print("AI dialogue opened for ", npc.npc_id)

func _on_message_submitted(player_text: String) -> void:
	if _active_npc == null or backend_client.is_busy():
		dialogue_ui.show_error("No NPC is available, or a request is already active.")
		return
	var npc_id: String = _active_npc.npc_id
	var profile: Dictionary = _active_npc.profile
	var npc_state := GameState.get_npc_state(npc_id)
	_request_npc_id = npc_id
	_pending_player_text = player_text
	dialogue_ui.append_player_text(player_text)
	dialogue_ui.set_thinking(true)
	var payload := {
		"npc_id": npc_id,
		"session_id": "default_save:%s" % npc_id,
		"player_message": player_text,
		"player_text": player_text,
		"level_id": GameState.current_level_id,
		"player_state": GameState.player_state,
		"npc_state": npc_state,
		"visible_world_facts": GameState.get_visible_world_facts(npc_id),
		"npc_name": str(profile.get("display_name", npc_id)),
		"target_language": str(profile.get("teaching", {}).get("target_language", "Japanese")),
		"scene_context": "The player is speaking with %s in %s." % [npc_id, GameState.current_level_id],
	}
	backend_client.send_message(payload)

func _on_response_received(response: Dictionary) -> void:
	var dialogue := str(response.get("dialogue", response.get("npc_text", "")))
	if _request_npc_id.is_empty():
		return
	GameState.add_conversation_message(_request_npc_id, "user", _pending_player_text)
	GameState.add_conversation_message(_request_npc_id, "assistant", dialogue)
	_apply_controlled_updates(_request_npc_id, response)
	dialogue_ui.set_thinking(false)
	if dialogue_ui.is_open() and _active_npc != null and _active_npc.npc_id == _request_npc_id:
		dialogue_ui.append_npc_text(dialogue)
		dialogue_ui.player_input.grab_focus()
	GameState.save_game()
	_request_npc_id = ""
	_pending_player_text = ""

func _on_request_failed(message: String) -> void:
	if dialogue_ui.is_open():
		dialogue_ui.show_error(message)
	else:
		dialogue_ui.set_thinking(false)
	_request_npc_id = ""
	_pending_player_text = ""

func _on_dialogue_closed() -> void:
	player.set_movement_enabled(true)
	_active_npc = null
	print("AI dialogue closed")

func _apply_controlled_updates(npc_id: String, response: Dictionary) -> void:
	for fact in response.get("memory_updates", []):
		if fact is Dictionary and str(fact.get("type", "")) == "remember_fact":
			GameState.add_private_npc_fact(npc_id, fact)
	for fact in response.get("world_updates", []):
		if fact is Dictionary and str(fact.get("type", "")) == "shared_fact":
			GameState.add_shared_world_fact(fact)

func _level_id_for_scene(scene_path: String) -> String:
	for level_id in LEVEL_SCENES:
		if LEVEL_SCENES[level_id] == scene_path:
			return level_id
	return ""
