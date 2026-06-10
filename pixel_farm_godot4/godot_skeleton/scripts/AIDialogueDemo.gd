extends Node2D

const NPC_NAME := "Aiko"
const TARGET_LANGUAGE := "Japanese"
const SCENE_CONTEXT := "A friendly villager is chatting with the player in a quiet farm clearing."

@onready var player: CharacterBody2D = $Player
@onready var npc: AITestNPC = $Aiko
@onready var dialogue_ui: AIDialogueUI = $DialogueUI
@onready var backend_client: AIBackendClient = $AIBackendClient

var _session_id := "godot_demo_%d" % Time.get_unix_time_from_system()

func _ready() -> void:
	npc.dialogue_requested.connect(dialogue_ui.open_dialogue)
	dialogue_ui.message_submitted.connect(_on_message_submitted)
	dialogue_ui.dialogue_closed.connect(_on_dialogue_closed)
	backend_client.response_received.connect(_on_response_received)
	backend_client.request_failed.connect(_on_request_failed)

func _on_message_submitted(player_text: String) -> void:
	dialogue_ui.append_player_text(player_text)
	dialogue_ui.set_thinking(true)
	player.set_physics_process(false)
	backend_client.send_message(
		player_text,
		NPC_NAME,
		TARGET_LANGUAGE,
		SCENE_CONTEXT,
		_session_id
	)

func _on_response_received(npc_text: String) -> void:
	dialogue_ui.append_npc_text(npc_text)
	dialogue_ui.set_thinking(false)
	dialogue_ui.player_input.grab_focus()

func _on_request_failed(message: String) -> void:
	dialogue_ui.show_error(message)

func _on_dialogue_closed() -> void:
	player.set_physics_process(true)
