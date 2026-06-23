extends Node2D

@onready var level_loader: Node = $LevelLoader
@onready var player = $Player
@onready var dialogue_ui: AIDialogueUI = $DialogueUI
@onready var backend_client: AIBackendClient = $AIBackendClient
@onready var voice_recorder: AIVoiceRecorder = $AIVoiceRecorder

var _active_npc: Node
var _request_npc_id := ""
var _pending_player_text := ""
var _transitioning := false

func _ready() -> void:
	dialogue_ui.message_submitted.connect(_on_message_submitted)
	dialogue_ui.dialogue_closed.connect(_on_dialogue_closed)
	dialogue_ui.record_requested.connect(_on_record_requested)
	dialogue_ui.transcribe_requested.connect(_on_transcribe_requested)
	backend_client.response_received.connect(_on_response_received)
	backend_client.request_failed.connect(_on_request_failed)
	backend_client.transcription_received.connect(_on_transcription_received)
	backend_client.transcription_failed.connect(_on_transcription_failed)
	level_loader.exit_triggered.connect(_on_exit_triggered)
	level_loader.level_loaded.connect(_on_level_loaded)
	GameState.load_game()
	level_loader.load_level("res://levels/farm.json")

func _on_level_loaded(_level_id: String) -> void:
	_connect_npc_signals()
	_transitioning = false
	player.set_movement_enabled(true)
	GameState.save_game()

func _connect_npc_signals() -> void:
	for npc in get_tree().get_nodes_in_group("ai_npc"):
		if not npc.dialogue_requested.is_connected(_on_dialogue_requested):
			npc.dialogue_requested.connect(_on_dialogue_requested)

func _on_exit_triggered(target_level: String, destination_spawn_id: String) -> void:
	if _transitioning or dialogue_ui.is_open():
		return
	_transitioning = true
	player.set_movement_enabled(false)
	GameState.current_level_id = target_level
	GameState.set_destination_spawn(destination_spawn_id)
	level_loader.load_level("res://levels/" + target_level + ".json", destination_spawn_id)

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

func _on_message_submitted(player_text: String) -> void:
	if _active_npc == null or backend_client.is_busy():
		dialogue_ui.show_error("No NPC available or request already active.")
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
	voice_recorder.cancel_recording()
	backend_client.cancel_transcription()
	voice_recorder.remove_temporary_wav()
	player.set_movement_enabled(true)
	_active_npc = null

func _on_record_requested() -> void:
	if not dialogue_ui.is_open() or backend_client.is_busy():
		return
	if voice_recorder.start_recording():
		dialogue_ui.set_recording()
	else:
		dialogue_ui.show_voice_error(voice_recorder.get_last_error())

func _on_transcribe_requested() -> void:
	if backend_client.is_transcribing():
		return
	var wav_path := voice_recorder.stop_recording()
	if wav_path.is_empty():
		dialogue_ui.show_voice_error(voice_recorder.get_last_error())
		return
	var file_size := voice_recorder.get_saved_file_size()
	if file_size <= 0:
		dialogue_ui.show_voice_error("Voice: recording file missing/empty")
		return
	dialogue_ui.set_transcribing(file_size)
	backend_client.transcribe_audio(wav_path)

func _on_transcription_received(transcript: String) -> void:
	voice_recorder.remove_temporary_wav()
	if dialogue_ui.is_open():
		dialogue_ui.set_transcript(transcript)

func _on_transcription_failed(message: String) -> void:
	voice_recorder.remove_temporary_wav()
	if dialogue_ui.is_open():
		dialogue_ui.show_voice_error(message)

func _apply_controlled_updates(npc_id: String, response: Dictionary) -> void:
	for fact in response.get("memory_updates", []):
		if fact is Dictionary and str(fact.get("type", "")) == "remember_fact":
			GameState.add_private_npc_fact(npc_id, fact)
	for fact in response.get("world_updates", []):
		if fact is Dictionary and str(fact.get("type", "")) == "shared_fact":
			GameState.add_shared_world_fact(fact)