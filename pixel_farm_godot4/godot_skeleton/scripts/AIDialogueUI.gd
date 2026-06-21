class_name AIDialogueUI
extends CanvasLayer

signal message_submitted(player_text: String)
signal dialogue_closed
signal record_requested
signal transcribe_requested

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

var _chat_busy := false
var _voice_state := "ready"

func _ready() -> void:
	panel.visible = false
	player_input.release_focus()
	send_button.pressed.connect(_submit_text)
	close_button.pressed.connect(close_dialogue)
	record_button.pressed.connect(_on_record_pressed)
	transcribe_button.pressed.connect(_on_transcribe_pressed)
	player_input.text_submitted.connect(_on_text_submitted)
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
	status_label.text = "Thinking..." if thinking else "Ready"
	status_label.modulate = Color(1.0, 0.85, 0.45) if thinking else Color(0.65, 0.85, 0.7)
	_refresh_controls()

func is_request_active() -> bool:
	return _chat_busy or _voice_state != "ready"

func set_recording() -> void:
	_voice_state = "recording"
	transcript_status.text = "Voice: Recording..."
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

func set_transcript(transcript: String) -> void:
	_voice_state = "ready"
	transcript_status.text = "Voice: Transcript received: %s" % transcript
	transcript_status.modulate = Color(0.65, 0.9, 0.7)
	player_input.text = transcript
	player_input.caret_column = transcript.length()
	_refresh_controls()
	if panel.visible:
		player_input.grab_focus()

func show_voice_error(message: String) -> void:
	_voice_state = "ready"
	transcript_status.text = message
	transcript_status.modulate = Color(1.0, 0.4, 0.4)
	_refresh_controls()
	if panel.visible:
		player_input.grab_focus()

func reset_voice_state() -> void:
	_voice_state = "ready"
	transcript_status.text = "Voice: Ready"
	transcript_status.modulate = Color(0.65, 0.85, 0.7)
	_refresh_controls()

func show_error(message: String) -> void:
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

	player_input.clear()
	message_submitted.emit(text)

func _on_record_pressed() -> void:
	if _voice_state == "ready" and not _chat_busy:
		record_requested.emit()

func _on_transcribe_pressed() -> void:
	if _voice_state == "recording":
		transcribe_requested.emit()

func _refresh_controls() -> void:
	if not is_node_ready():
		return
	var voice_busy := _voice_state == "recording" or _voice_state == "transcribing"
	player_input.editable = not _chat_busy and not voice_busy
	send_button.disabled = _chat_busy or voice_busy
	record_button.disabled = _chat_busy or _voice_state != "ready"
	transcribe_button.disabled = _voice_state != "recording"
	close_button.disabled = false

func _on_text_submitted(_text: String) -> void:
	_submit_text()

func _escape_bbcode(text: String) -> String:
	return text.replace("[", "[lb]")
