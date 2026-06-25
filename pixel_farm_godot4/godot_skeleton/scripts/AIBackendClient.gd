class_name AIBackendClient
extends Node

signal response_received(response: Dictionary)
signal request_failed(message: String)
signal transcription_received(transcript: String)
signal transcription_failed(message: String)

@export var endpoint := "http://127.0.0.1:8000/npc/chat"
@export var speech_endpoint := "http://127.0.0.1:8000/speech/transcribe"

var _request: HTTPRequest
var _speech_request: HTTPRequest
var _busy := false
var _speech_busy := false

func _ready() -> void:
	_request = HTTPRequest.new()
	_request.timeout = 35.0
	add_child(_request)
	_request.request_completed.connect(_on_request_completed)
	_speech_request = HTTPRequest.new()
	_speech_request.timeout = 60.0
	add_child(_speech_request)
	_speech_request.request_completed.connect(_on_transcription_completed)

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

func transcribe_audio(wav_path: String) -> void:
	if _speech_busy:
		transcription_failed.emit("A transcription request is already active.")
		return
	if not FileAccess.file_exists(wav_path):
		transcription_failed.emit("No audio recording was prepared.")
		return

	var audio_bytes := FileAccess.get_file_as_bytes(wav_path)
	if audio_bytes.is_empty():
		transcription_failed.emit("No audio recorded.")
		return

	var boundary := "KotoDamaBoundary%d" % Time.get_ticks_usec()
	var body := _build_multipart_body(boundary, "voice_input.wav", audio_bytes)
	var headers := PackedStringArray([
		"Content-Type: multipart/form-data; boundary=%s" % boundary,
		"Content-Length: %d" % body.size(),
	])
	var request_error := _speech_request.request_raw(
		speech_endpoint,
		headers,
		HTTPClient.METHOD_POST,
		body
	)
	if request_error != OK:
		print("Transcription request could not start: ", request_error)
		transcription_failed.emit(
			"Could not contact speech endpoint (error %d)." % request_error
		)
		return

	_speech_busy = true
	print(
		"Transcription request sent to %s (%d audio bytes)"
		% [speech_endpoint, audio_bytes.size()]
	)

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
		var detail := _response_error_message(parsed, response_text)
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

func is_transcribing() -> bool:
	return _speech_busy

func cancel_transcription() -> void:
	if not _speech_busy:
		return
	_speech_request.cancel_request()
	_speech_busy = false
	print("Transcription request cancelled")

func _on_transcription_completed(
	result: int,
	response_code: int,
	_headers: PackedStringArray,
	body: PackedByteArray
) -> void:
	_speech_busy = false

	if result != HTTPRequest.RESULT_SUCCESS:
		print("Transcription failed with network result ", result)
		transcription_failed.emit("Could not contact speech endpoint.")
		return

	var response_text := body.get_string_from_utf8()
	var json := JSON.new()
	var parse_error := json.parse(response_text)
	var parsed: Variant = json.data if parse_error == OK else null

	if response_code < 200 or response_code >= 300:
		var detail := _response_error_message(parsed, response_text)
		print("Transcription failed with HTTP ", response_code, ": ", detail)
		transcription_failed.emit("Speech endpoint error %d: %s" % [response_code, detail])
		return
	if not parsed is Dictionary:
		print("Transcription failed: malformed JSON response")
		transcription_failed.emit("Speech endpoint returned malformed JSON.")
		return

	var transcript := str(parsed.get("transcript", "")).strip_edges()
	if transcript.is_empty():
		print("Transcription failed: response contained no transcript")
		transcription_failed.emit("Speech endpoint returned no transcript.")
		return

	print("Transcript received (%d characters)" % transcript.length())
	transcription_received.emit(transcript)

func _build_multipart_body(
	boundary: String,
	filename: String,
	audio_bytes: PackedByteArray
) -> PackedByteArray:
	var body := PackedByteArray()
	body.append_array(("--%s\r\n" % boundary).to_utf8_buffer())
	body.append_array(
		(
			'Content-Disposition: form-data; name="file"; filename="%s"\r\n'
			% filename
		).to_utf8_buffer()
	)
	body.append_array("Content-Type: audio/wav\r\n\r\n".to_utf8_buffer())
	body.append_array(audio_bytes)
	body.append_array(("\r\n--%s--\r\n" % boundary).to_utf8_buffer())
	return body

func _response_error_message(parsed: Variant, fallback: String) -> String:
	if not parsed is Dictionary or not parsed.has("detail"):
		return fallback
	var detail: Variant = parsed["detail"]
	if detail is Dictionary:
		return str(detail.get("message", detail.get("code", fallback)))
	return str(detail)
