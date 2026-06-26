class_name AIDialogueUI
extends CanvasLayer

signal message_submitted(player_text: String)
signal dialogue_closed
signal record_requested
signal transcribe_requested
signal stop_npc_voice_requested

@export_enum("confirm", "auto_send") var voice_transcript_mode := "confirm"
@export_range(0, 10000, 100) var voice_auto_send_delay_ms := 1200

@onready var panel: Panel = $Panel
@onready var npc_name_label: Label = $Panel/NPCName
@onready var conversation: RichTextLabel = $Panel/Conversation
@onready var player_input: LineEdit = $Panel/PlayerInput
@onready var send_button: Button = $Panel/SendButton
@onready var close_button: Button = $Panel/CloseButton
@onready var status_label: Label = $Panel/Status
@onready var transcript_status: Label = $Panel/TranscriptStatus
@onready var record_button: Button = $Panel/RecordButton
@onready var transcribe_button: Button = $Panel/TranscribeButton
@onready var stop_voice_button: Button = $Panel/StopVoiceButton

var _chat_busy := false
var _voice_state := "ready"
var _auto_send_timer: Timer
var _auto_send_pending := false
var _auto_send_turn_id := 0
var _setting_input_text := false

func _ready() -> void:
	panel.visible = false
	_auto_send_timer = Timer.new()
	_auto_send_timer.one_shot = true
	add_child(_auto_send_timer)
	_auto_send_timer.timeout.connect(_on_auto_send_timeout)
	player_input.release_focus()
	send_button.pressed.connect(_submit_text)
	close_button.pressed.connect(close_dialogue)
	record_button.pressed.connect(_on_record_pressed)
	transcribe_button.pressed.connect(_on_transcribe_pressed)
	stop_voice_button.pressed.connect(_on_stop_voice_pressed)
	player_input.text_submitted.connect(_on_text_submitted)
	player_input.text_changed.connect(_on_input_text_changed)
	reset_voice_state()

func open_dialogue(npc_name: String, history: Array = [], greeting: String = "") -> void:
	npc_name_label.text = npc_name
	conversation.clear()
	for message in history:
		if not message is Dictionary:
			continue
		var role := str(message.get("role", ""))
		var content := str(message.get("content", ""))
		if role == "user":
			append_player_text(content)
		elif role == "assistant":
			append_npc_text(content)
	if history.is_empty() and not greeting.is_empty():
		append_npc_text(greeting)
	status_label.text = "Ready"
	status_label.modulate = Color(0.65, 0.85, 0.7)
	reset_voice_state()
	panel.visible = true
	player_input.grab_focus()

func close_dialogue() -> void:
	cancel_pending_transcript("")
	player_input.release_focus()
	panel.visible = false
	reset_voice_state()
	dialogue_closed.emit()

func is_open() -> bool:
	return panel.visible

func append_player_text(text: String) -> void:
	conversation.append_text("[color=#8ecbff][b]You:[/b][/color] %s\n" % _escape_bbcode(text))

func append_npc_text(text: String) -> void:
	conversation.append_text(
		"[color=#ffd38e][b]%s:[/b][/color] %s\n" % [
			_escape_bbcode(npc_name_label.text),
			_escape_bbcode(text),
		]
	)

func set_thinking(thinking: bool) -> void:
	_chat_busy = thinking
	status_label.text = "NPC is responding..." if thinking else "Ready"
	status_label.modulate = Color(1.0, 0.85, 0.45) if thinking else Color(0.65, 0.85, 0.7)
	_refresh_controls()

func set_session_status(text: String, is_error: bool = false) -> void:
	status_label.text = text
	status_label.modulate = Color(1.0, 0.4, 0.4) if is_error else Color(0.65, 0.85, 0.7)

func is_request_active() -> bool:
	return _chat_busy or _voice_state != "ready"

func set_recording() -> void:
	_voice_state = "recording"
	transcript_status.text = "Voice: Listening..."
	transcript_status.modulate = Color(1.0, 0.55, 0.45)
	_refresh_controls()

func set_transcribing(file_size: int = 0) -> void:
	_voice_state = "transcribing"
	transcript_status.text = (
		"Voice: WAV saved (%d bytes); transcribing..." % file_size
		if file_size > 0
		else "Voice: Transcribing..."
	)
	transcript_status.modulate = Color(1.0, 0.85, 0.45)
	_refresh_controls()

func set_speech_detected() -> void:
	_voice_state = "recording"
	transcript_status.text = "Voice: Speech detected"
	transcript_status.modulate = Color(0.65, 0.9, 0.7)
	_refresh_controls()

func set_waiting_for_speech_end() -> void:
	_voice_state = "recording"
	transcript_status.text = "Voice: Waiting for you to finish..."
	transcript_status.modulate = Color(1.0, 0.85, 0.45)
	_refresh_controls()

func set_vad_unavailable() -> void:
	_voice_state = "recording"
	transcript_status.text = "Voice: Automatic stopping unavailable - use Stop"
	transcript_status.modulate = Color(1.0, 0.65, 0.35)
	_refresh_controls()

func set_maximum_length_reached() -> void:
	_voice_state = "transcribing"
	transcript_status.text = "Voice: Maximum recording length reached"
	transcript_status.modulate = Color(1.0, 0.65, 0.35)
	_refresh_controls()

func set_sending_audio(byte_count: int) -> void:
	_voice_state = "transcribing"
	transcript_status.text = "Voice: Sending audio... (%d bytes)" % byte_count
	transcript_status.modulate = Color(1.0, 0.85, 0.45)
	_refresh_controls()

func set_stream_transcribing(byte_count: int) -> void:
	_voice_state = "transcribing"
	transcript_status.text = "Voice: Transcribing... (%d bytes streamed)" % byte_count
	transcript_status.modulate = Color(1.0, 0.85, 0.45)
	_refresh_controls()

func set_npc_speaking() -> void:
	_voice_state = "speaking"
	transcript_status.text = "NPC is speaking..."
	transcript_status.modulate = Color(1.0, 0.85, 0.45)
	status_label.text = "NPC is speaking..."
	status_label.modulate = Color(1.0, 0.85, 0.45)
	_refresh_controls()

func set_transcript(transcript: String) -> void:
	cancel_pending_transcript("")
	var clean_transcript := transcript.strip_edges()
	if clean_transcript.is_empty():
		show_voice_error("Voice: Empty transcript")
		return
	transcript_status.text = "Voice: Transcript received: %s" % transcript
	transcript_status.modulate = Color(0.65, 0.9, 0.7)
	_setting_input_text = true
	player_input.text = clean_transcript
	player_input.caret_column = clean_transcript.length()
	_setting_input_text = false
	if is_auto_send_transcript_enabled():
		_start_auto_send_countdown()
	else:
		_voice_state = "ready"
		_refresh_controls()
	if panel.visible:
		player_input.grab_focus()

func show_voice_error(message: String) -> void:
	cancel_pending_transcript("")
	_voice_state = "ready"
	transcript_status.text = message
	transcript_status.modulate = Color(1.0, 0.4, 0.4)
	_refresh_controls()
	if panel.visible:
		player_input.grab_focus()

func reset_voice_state() -> void:
	cancel_pending_transcript("")
	_voice_state = "ready"
	transcript_status.text = "Voice: Ready"
	transcript_status.modulate = Color(0.65, 0.85, 0.7)
	_refresh_controls()

func show_error(message: String) -> void:
	cancel_pending_transcript("")
	set_thinking(false)
	status_label.text = message
	status_label.modulate = Color(1.0, 0.4, 0.4)
	conversation.append_text("[color=#ff7777][b]Error:[/b] %s[/color]\n" % _escape_bbcode(message))
	if panel.visible:
		player_input.grab_focus()

func _submit_text() -> void:
	var text := player_input.text.strip_edges()
	if text.is_empty() or send_button.disabled:
		return

	cancel_pending_transcript("")
	player_input.clear()
	message_submitted.emit(text)

func _on_record_pressed() -> void:
	if _auto_send_pending:
		cancel_pending_transcript("")
	if _voice_state == "ready" and not _chat_busy:
		record_requested.emit()

func _on_transcribe_pressed() -> void:
	if _voice_state == "recording":
		transcribe_requested.emit()

func _on_stop_voice_pressed() -> void:
	if _voice_state == "speaking":
		stop_npc_voice_requested.emit()

func _refresh_controls() -> void:
	if not is_node_ready():
		return
	var voice_busy := _voice_state in ["recording", "transcribing", "speaking"]
	var transcript_pending := _voice_state == "transcript_pending"
	player_input.editable = not _chat_busy and not voice_busy
	send_button.disabled = _chat_busy or voice_busy
	record_button.disabled = _chat_busy or voice_busy
	transcribe_button.disabled = _voice_state != "recording"
	stop_voice_button.disabled = _voice_state != "speaking"
	stop_voice_button.visible = _voice_state == "speaking"
	close_button.disabled = false

	if transcript_pending:
		record_button.disabled = false

func _on_text_submitted(_text: String) -> void:
	_submit_text()

func is_auto_send_transcript_enabled() -> bool:
	return voice_transcript_mode == "auto_send"

func has_pending_transcript() -> bool:
	return _auto_send_pending

func cancel_pending_transcript(message: String = "Automatic send cancelled - review and press Send") -> void:
	if not _auto_send_pending:
		return
	_auto_send_pending = false
	_auto_send_turn_id += 1
	if _auto_send_timer != null:
		_auto_send_timer.stop()
	_voice_state = "ready"
	if not message.is_empty():
		transcript_status.text = message
		transcript_status.modulate = Color(1.0, 0.85, 0.45)
	else:
		transcript_status.text = "Voice: Ready"
		transcript_status.modulate = Color(0.65, 0.85, 0.7)
	_refresh_controls()

func _start_auto_send_countdown() -> void:
	_auto_send_pending = true
	_auto_send_turn_id += 1
	_voice_state = "transcript_pending"
	var delay_seconds: float = maxf(float(voice_auto_send_delay_ms) / 1000.0, 0.0)
	transcript_status.text = "Sending automatically in %s seconds..." % _format_seconds(delay_seconds)
	transcript_status.modulate = Color(1.0, 0.85, 0.45)
	_refresh_controls()
	_auto_send_timer.start(delay_seconds)

func _on_auto_send_timeout() -> void:
	if not _auto_send_pending or _chat_busy or not panel.visible:
		cancel_pending_transcript("")
		return
	var text := player_input.text.strip_edges()
	if text.is_empty():
		show_voice_error("Voice: Empty transcript")
		return
	cancel_pending_transcript("")
	player_input.clear()
	message_submitted.emit(text)

func _on_input_text_changed(_new_text: String) -> void:
	if _setting_input_text or not _auto_send_pending:
		return
	cancel_pending_transcript()

func _unhandled_input(event: InputEvent) -> void:
	if _auto_send_pending and event.is_action_pressed("ui_cancel"):
		cancel_pending_transcript()
		get_viewport().set_input_as_handled()

func _format_seconds(seconds: float) -> String:
	return "%0.1f" % seconds

func _escape_bbcode(text: String) -> String:
	return text.replace("[", "[lb]")
