class_name AIBackendClient
extends Node

signal response_received(response: Dictionary)
signal request_failed(message: String)

@export var endpoint := "http://127.0.0.1:8000/npc/chat"

var _request: HTTPRequest
var _busy := false

func _ready() -> void:
	_request = HTTPRequest.new()
	_request.timeout = 35.0
	add_child(_request)
	_request.request_completed.connect(_on_request_completed)

func send_message(payload: Dictionary) -> void:
	if _busy:
		request_failed.emit("A request is already in progress.")
		return

	var headers := PackedStringArray(["Content-Type: application/json"])
	var request_error := _request.request(
		endpoint,
		headers,
		HTTPClient.METHOD_POST,
		JSON.stringify(payload)
	)

	if request_error != OK:
		print("AI backend error: request could not start (", request_error, ")")
		request_failed.emit("Could not start the backend request (error %d)." % request_error)
		return

	_busy = true
	print("AI backend request sent to ", endpoint)

func _on_request_completed(
	result: int,
	response_code: int,
	_headers: PackedStringArray,
	body: PackedByteArray
) -> void:
	_busy = false

	if result != HTTPRequest.RESULT_SUCCESS:
		print("AI backend error: network result ", result)
		request_failed.emit(
			"Cannot contact the AI backend at %s (network error %d)." % [endpoint, result]
		)
		return

	var response_text := body.get_string_from_utf8()
	var json := JSON.new()
	var parse_error := json.parse(response_text)
	var parsed: Variant = json.data if parse_error == OK else null

	if response_code < 200 or response_code >= 300:
		var detail := response_text
		if parsed is Dictionary and parsed.has("detail"):
			detail = str(parsed["detail"])
		print("AI backend error: HTTP ", response_code)
		request_failed.emit("Backend error %d: %s" % [response_code, detail])
		return

	if not parsed is Dictionary:
		print("AI backend error: malformed JSON response")
		request_failed.emit("The backend returned malformed JSON.")
		return
	var dialogue := str(parsed.get("dialogue", parsed.get("npc_text", ""))).strip_edges()
	if dialogue.is_empty():
		print("AI backend error: response missing dialogue")
		request_failed.emit("The backend response did not contain dialogue text.")
		return
	parsed["dialogue"] = dialogue
	parsed["npc_text"] = dialogue

	print("AI backend response received with dialogue")
	response_received.emit(parsed)

func is_busy() -> bool:
	return _busy
