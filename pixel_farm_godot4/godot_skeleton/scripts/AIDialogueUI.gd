class_name AIDialogueUI
extends CanvasLayer

signal message_submitted(player_text: String)
signal dialogue_closed

@onready var panel: Panel = $Panel
@onready var npc_name_label: Label = $Panel/NPCName
@onready var conversation: RichTextLabel = $Panel/Conversation
@onready var player_input: LineEdit = $Panel/PlayerInput
@onready var send_button: Button = $Panel/SendButton
@onready var close_button: Button = $Panel/CloseButton
@onready var status_label: Label = $Panel/Status

func _ready() -> void:
	panel.visible = false
	send_button.pressed.connect(_submit_text)
	close_button.pressed.connect(close_dialogue)
	player_input.text_submitted.connect(_on_text_submitted)

func open_dialogue(npc_name: String) -> void:
	npc_name_label.text = npc_name
	if conversation.text.is_empty():
		append_npc_text("Hello! What would you like to talk about?")
	status_label.text = "Connected to local demo UI"
	status_label.modulate = Color(0.65, 0.85, 0.7)
	panel.visible = true
	player_input.grab_focus()

func close_dialogue() -> void:
	panel.visible = false
	dialogue_closed.emit()

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
	player_input.editable = not thinking
	send_button.disabled = thinking
	status_label.text = "Thinking..." if thinking else "Ready"
	status_label.modulate = Color(1.0, 0.85, 0.45) if thinking else Color(0.65, 0.85, 0.7)

func show_error(message: String) -> void:
	set_thinking(false)
	status_label.text = message
	status_label.modulate = Color(1.0, 0.4, 0.4)
	conversation.append_text("[color=#ff7777][b]Error:[/b] %s[/color]\n" % _escape_bbcode(message))
	player_input.grab_focus()

func _submit_text() -> void:
	var text := player_input.text.strip_edges()
	if text.is_empty() or send_button.disabled:
		return

	player_input.clear()
	message_submitted.emit(text)

func _on_text_submitted(_text: String) -> void:
	_submit_text()

func _escape_bbcode(text: String) -> String:
	return text.replace("[", "[lb]")
