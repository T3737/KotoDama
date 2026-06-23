extends Node2D

@export_enum("confirm_transcript", "auto_send_transcript") var transcript_mode := "confirm_transcript"

const NO_AUDIO_WARNING := "No microphone audio detected. Check the selected system input device."

const LEVEL_SCENES := {
	"level_01": "res://scenes/levels/level_01.tscn",
	"level_02": "res://scenes/levels/level_02.tscn",
}

@onready var level_container: Node2D = $LevelContainer
@onready var player = $Player
@onready var dialogue_ui: AIDialogueUI = $DialogueUI
@onready var backend_client: AIBackendClient = $AIBackendClient
@onready var voice_session_client: Node = $AIVoiceSessionClient
@onready var voice_recorder: AIVoiceRecorder = $AIVoiceRecorder
@onready var voice_capture: Node = $AIVoiceCapture

var _current_level: Node2D
var _active_npc: Node
var _request_npc_id := ""
var _pending_player_text := ""
var _transitioning := false
var _use_http_fallback := false
var _using_stream_capture := false

func _ready() -> void:
	dialogue_ui.message_submitted.connect(_on_message_submitted)
	dialogue_ui.dialogue_closed.connect(_on_dialogue_closed)
	dialogue_ui.record_requested.connect(_on_record_requested)
	dialogue_ui.transcribe_requested.connect(_on_transcribe_requested)
	backend_client.response_received.connect(_on_response_received)
	backend_client.request_failed.connect(_on_request_failed)
	backend_client.transcription_received.connect(_on_transcription_received)
	backend_client.transcription_failed.connect(_on_transcription_failed)
	voice_session_client.session_ready.connect(_on_voice_session_ready)
	voice_session_client.state_changed.connect(_on_voice_state_changed)
	voice_session_client.npc_text_final.connect(_on_voice_npc_text_final)
	voice_session_client.audio_ready.connect(_on_voice_audio_ready)
	voice_session_client.audio_received.connect(_on_voice_audio_received)
	voice_session_client.transcript_final.connect(_on_voice_transcript_final)
	voice_session_client.session_error.connect(_on_voice_session_error)
	voice_capture.capture_warning.connect(_on_voice_capture_warning)
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
	_use_http_fallback = false
	voice_session_client.start_session(
		"default_save:%s" % npc.npc_id,
		npc.npc_id,
		{
			"level_id": GameState.current_level_id,
			"player_state": GameState.player_state,
			"npc_state": npc_state,
			"visible_world_facts": GameState.get_visible_world_facts(npc.npc_id),
			"scene_context": "The player is speaking with %s in %s." % [npc.npc_id, GameState.current_level_id],
		}
	)
	dialogue_ui.set_session_status("Connecting...")
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
	print("Text sent to NPC %s (%d characters)" % [npc_id, player_text.length()])
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
	if not _use_http_fallback and voice_session_client.is_session_ready():
		if voice_session_client.send_player_text(player_text):
			return
	_use_http_fallback = true
	dialogue_ui.set_session_status("Thinking... (HTTP fallback)")
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
	print("NPC response received (%d characters)" % dialogue.length())
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
	voice_capture.cancel_capture()
	voice_session_client.close_session()
	voice_recorder.cancel_recording()
	backend_client.cancel_transcription()
	voice_recorder.remove_temporary_wav()
	player.set_movement_enabled(true)
	_active_npc = null
	_using_stream_capture = false
	print("AI dialogue closed")

func _on_voice_session_ready() -> void:
	if dialogue_ui.is_open():
		dialogue_ui.set_session_status("Ready")
	print("AI voice session ready")

func _on_voice_state_changed(state: String) -> void:
	if not dialogue_ui.is_open():
		return
	match state:
		"LISTENING":
			dialogue_ui.set_recording()
		"TRANSCRIBING":
			dialogue_ui.set_transcribing(voice_capture.get_bytes_transmitted())
		"GENERATING":
			dialogue_ui.set_thinking(true)
		"READY":
			if _pending_player_text.is_empty():
				dialogue_ui.set_thinking(false)
		"ERROR":
			dialogue_ui.set_session_status("Session error", true)

func _on_voice_npc_text_final(payload: Dictionary) -> void:
	var response := payload.duplicate(true)
	response["dialogue"] = str(payload.get("text", ""))
	response["npc_text"] = response["dialogue"]
	_on_response_received(response)

func _on_voice_audio_ready(payload: Dictionary) -> void:
	if dialogue_ui.is_open():
		dialogue_ui.set_session_status(
			"Listening (%d Hz mono PCM16)" % int(payload.get("sample_rate", 0))
		)

func _on_voice_audio_received(payload: Dictionary) -> void:
	if dialogue_ui.is_open():
		dialogue_ui.set_transcribing(int(payload.get("received_bytes", 0)))
	print(
		"Backend received streamed audio: %d bytes (%d ms)" % [
			int(payload.get("received_bytes", 0)), int(payload.get("duration_ms", 0))
		]
	)

func _on_voice_transcript_final(payload: Dictionary) -> void:
	var transcript := str(payload.get("text", "")).strip_edges()
	if transcript.is_empty() or not dialogue_ui.is_open():
		return
	dialogue_ui.set_transcript(transcript)
	print("Final streamed transcript: ", transcript)
	if bool(payload.get("auto_sent", false)) and _active_npc != null:
		_request_npc_id = _active_npc.npc_id
		_pending_player_text = transcript
		dialogue_ui.player_input.clear()
		dialogue_ui.append_player_text(transcript)
		dialogue_ui.set_thinking(true)
	_using_stream_capture = false

func _on_voice_session_error(code: String, message: String, fatal: bool) -> void:
	if code in ["connection_failed", "connection_timeout", "connection_closed", "send_failed"]:
		_use_http_fallback = true
		if dialogue_ui.is_open():
			dialogue_ui.set_session_status("Ready (HTTP fallback)")
		if not _pending_player_text.is_empty() and not backend_client.is_busy():
			_send_pending_over_http()
		print("WebSocket unavailable; using HTTP fallback: ", code)
		return
	if code in ["audio_too_short", "audio_idle_timeout"] and voice_capture.get_bytes_transmitted() == 0:
		if dialogue_ui.is_open():
			dialogue_ui.show_voice_error(NO_AUDIO_WARNING)
		_using_stream_capture = false
		return
	if code.begins_with("audio_") or code in ["stt_unavailable", "transcription_failed"]:
		voice_capture.cancel_capture()
		_using_stream_capture = false
		if dialogue_ui.is_open():
			dialogue_ui.show_voice_error(message)
		return
	if dialogue_ui.is_open():
		dialogue_ui.show_error(message)
	_request_npc_id = ""
	_pending_player_text = ""
	if fatal:
		_use_http_fallback = true

func _send_pending_over_http() -> void:
	if _active_npc == null or _pending_player_text.is_empty():
		return
	var npc_id: String = _active_npc.npc_id
	var profile: Dictionary = _active_npc.profile
	backend_client.send_message({
		"npc_id": npc_id,
		"session_id": "default_save:%s" % npc_id,
		"player_message": _pending_player_text,
		"player_text": _pending_player_text,
		"level_id": GameState.current_level_id,
		"player_state": GameState.player_state,
		"npc_state": GameState.get_npc_state(npc_id),
		"visible_world_facts": GameState.get_visible_world_facts(npc_id),
		"npc_name": str(profile.get("display_name", npc_id)),
		"target_language": str(profile.get("teaching", {}).get("target_language", "Japanese")),
		"scene_context": "The player is speaking with %s in %s." % [npc_id, GameState.current_level_id],
	})

func _on_record_requested() -> void:
	if not dialogue_ui.is_open() or backend_client.is_busy():
		return
	if voice_session_client.is_session_ready():
		_using_stream_capture = voice_capture.start_capture(transcript_mode == "auto_send_transcript")
		if _using_stream_capture:
			dialogue_ui.set_recording()
			return
		dialogue_ui.show_voice_error(voice_capture.get_last_error())
		return
	if voice_recorder.start_recording():
		_using_stream_capture = false
		dialogue_ui.set_recording()
	else:
		dialogue_ui.show_voice_error(voice_recorder.get_last_error())

func _on_transcribe_requested() -> void:
	if _using_stream_capture:
		var bytes_sent: int = voice_capture.stop_capture()
		_using_stream_capture = false
		dialogue_ui.set_transcribing(bytes_sent)
		if bytes_sent == 0:
			dialogue_ui.show_voice_error(NO_AUDIO_WARNING)
		return
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

func _on_voice_capture_warning(message: String) -> void:
	if voice_capture.is_capturing():
		voice_capture.stop_capture("no_audio_detected")
	_using_stream_capture = false
	if dialogue_ui.is_open():
		dialogue_ui.show_voice_error(message)

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
