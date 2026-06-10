class_name AIBackendClient
extends Node

signal response_received(npc_text: String)
signal request_failed(message: String)

@export var endpoint := "http://127.0.0.1:8000/npc/chat"

var _request: HTTPRequest
var _busy := false

func _ready() -> void:
	_request = HTTPRequest.new()
	add_child(_request)
	_request.request_completed.connect(_on_request_completed)

func send_message(
	player_text: String,
	npc_name: String,
	target_language: String,
	scene_context: String,
	session_id: String
) -> void:
	if _busy:
		request_failed.emit("A request is already in progress.")
		return

	var payload := {
		"session_id": session_id,
		"player_text": player_text,
		"target_language": target_language,
		"npc_name": npc_name,
		"scene_context": scene_context,
	}
	var headers := PackedStringArray(["Content-Type: application/json"])
	var request_error := _request.request(
		endpoint,
		headers,
		HTTPClient.METHOD_POST,
		JSON.stringify(payload)
	)

	if request_error != OK:
		request_failed.emit("Could not start the backend request (error %d)." % request_error)
		return

	_busy = true

func _on_request_completed(
	result: int,
	response_code: int,
	_headers: PackedStringArray,
	body: PackedByteArray
) -> void:
	_busy = false

	if result != HTTPRequest.RESULT_SUCCESS:
		request_failed.emit(
			"Cannot contact the AI backend at %s (network error %d)." % [endpoint, result]
		)
		return

	var response_text := body.get_string_from_utf8()
	var parsed: Variant = JSON.parse_string(response_text)

	if response_code < 200 or response_code >= 300:
		var detail := response_text
		if parsed is Dictionary and parsed.has("detail"):
			detail = str(parsed["detail"])
		request_failed.emit("Backend error %d: %s" % [response_code, detail])
		return

	if not parsed is Dictionary or not parsed.has("npc_text"):
		request_failed.emit("The backend response did not contain npc_text.")
		return

	response_received.emit(str(parsed["npc_text"]))
