class_name AIVoiceSessionClient
extends Node

signal connected
signal session_ready
signal state_changed(state: String)
signal npc_text_delta(text: String)
signal npc_text_final(payload: Dictionary)
signal audio_ready(payload: Dictionary)
signal audio_received(payload: Dictionary)
signal audio_bytes_sent(total_bytes: int)
signal audio_auto_stopped(payload: Dictionary)
signal vad_speech_started(payload: Dictionary)
signal vad_speech_ended(payload: Dictionary)
signal transcript_final(payload: Dictionary)
signal npc_audio_ready(payload: Dictionary)
signal session_error(code: String, message: String, fatal: bool)
signal voice_error(code: String, message: String, fatal: bool)
signal disconnected

@export var endpoint := "ws://127.0.0.1:8000/voice/session"
@export var connect_timeout_seconds := 3.0
@export var ping_interval_seconds := 10.0
@export var auto_send_transcript := false

var _socket: WebSocketPeer
var _session_id := ""
var _start_payload: Dictionary = {}
var _session_ready := false
var _start_sent := false
var _intentional_close := false
var _connect_started_ms := 0
var _last_ping_ms := 0
var _last_state := WebSocketPeer.STATE_CLOSED
var _conversation_state := "DISCONNECTED"
var _audio_sending := false
var _audio_bytes_sent := 0

func _process(_delta: float) -> void:
	if _socket == null:
		return
	_socket.poll()
	var state := _socket.get_ready_state()
	if state != _last_state:
		_last_state = state
		if state == WebSocketPeer.STATE_OPEN:
			connected.emit()
			_send_session_start()
		elif state == WebSocketPeer.STATE_CLOSED:
			_handle_closed()
			return

	if state == WebSocketPeer.STATE_CONNECTING:
		var elapsed := Time.get_ticks_msec() - _connect_started_ms
		if elapsed > int(connect_timeout_seconds * 1000.0):
			_fail_connection("connection_timeout", "WebSocket connection timed out.")
		return
	if state != WebSocketPeer.STATE_OPEN:
		return

	while _socket.get_available_packet_count() > 0:
		var packet := _socket.get_packet()
		if not _socket.was_string_packet():
			_emit_error("binary_not_supported", "Unexpected binary WebSocket event.", false)
			continue
		_handle_packet(packet.get_string_from_utf8())

	if _session_ready and Time.get_ticks_msec() - _last_ping_ms > int(ping_interval_seconds * 1000.0):
		_send_event("ping", {})
		_last_ping_ms = Time.get_ticks_msec()

func start_session(session_id: String, npc_id: String, context: Dictionary = {}) -> void:
	close_session()
	_session_id = session_id
	_start_payload = context.duplicate(true)
	_start_payload["npc_id"] = npc_id
	_session_ready = false
	_start_sent = false
	_audio_sending = false
	_audio_bytes_sent = 0
	_conversation_state = "CONNECTING"
	_intentional_close = false
	_socket = WebSocketPeer.new()
	_last_state = WebSocketPeer.STATE_CONNECTING
	_connect_started_ms = Time.get_ticks_msec()
	var result := _socket.connect_to_url(endpoint)
	if result != OK:
		_fail_connection("connection_failed", "Could not start WebSocket connection (error %d)." % result)

func send_player_text(text: String) -> bool:
	var clean_text := text.strip_edges()
	if not _session_ready or _conversation_state != "READY" or clean_text.is_empty():
		return false
	return _send_event("player.text", {"text": clean_text})

func send_npc_audio_finished(audio_id: String, cancelled: bool = false) -> bool:
	if not _session_ready or audio_id.strip_edges().is_empty():
		return false
	return _send_event(
		"npc.audio.finished",
		{
			"audio_id": audio_id,
			"cancelled": cancelled,
		}
	)

func start_audio(sample_rate: int) -> bool:
	if not _session_ready or _conversation_state != "READY" or _audio_sending:
		return false
	_audio_sending = _send_event(
		"audio.start",
		{
			"sample_rate": sample_rate,
			"channels": 1,
			"encoding": "pcm_s16le",
			"auto_send_transcript": auto_send_transcript,
		}
	)
	if _audio_sending:
		_audio_bytes_sent = 0
	return _audio_sending

func send_audio_frame(audio_bytes: PackedByteArray) -> bool:
	if not _audio_sending or audio_bytes.is_empty():
		return false
	if _socket == null or _socket.get_ready_state() != WebSocketPeer.STATE_OPEN:
		_audio_sending = false
		return false
	var error := _socket.send(audio_bytes, WebSocketPeer.WRITE_MODE_BINARY)
	if error != OK:
		_audio_sending = false
		_emit_error("send_failed", "Could not send microphone audio (error %d)." % error, false)
		return false
	_audio_bytes_sent += audio_bytes.size()
	audio_bytes_sent.emit(_audio_bytes_sent)
	return true

func stop_audio(reason: String = "player_released") -> bool:
	if not _audio_sending:
		return false
	var sent := _send_event("audio.stop", {"reason": reason})
	_audio_sending = false
	return sent

func is_session_ready() -> bool:
	return _session_ready and _conversation_state == "READY"

func close_session() -> void:
	if _socket == null:
		return
	_intentional_close = true
	if _socket.get_ready_state() == WebSocketPeer.STATE_OPEN:
		_send_event("session.close", {})
		_socket.close(1000, "Dialogue closed")
	_socket = null
	_session_ready = false
	_start_sent = false
	_audio_sending = false
	_audio_bytes_sent = 0
	_conversation_state = "DISCONNECTED"
	disconnected.emit()

func _send_session_start() -> void:
	if _start_sent:
		return
	_start_sent = _send_event("session.start", _start_payload)

func _send_event(event_type: String, payload: Dictionary) -> bool:
	if _socket == null or _socket.get_ready_state() != WebSocketPeer.STATE_OPEN:
		return false
	var envelope := {
		"type": event_type,
		"session_id": _session_id,
		"event_id": _new_event_id(),
		"timestamp": Time.get_datetime_string_from_system(true, true),
		"payload": payload,
	}
	var error := _socket.send_text(JSON.stringify(envelope))
	if error != OK:
		_emit_error("send_failed", "Could not send WebSocket event (error %d)." % error, false)
		return false
	return true

func _handle_packet(text: String) -> void:
	var json := JSON.new()
	if json.parse(text) != OK or not json.data is Dictionary:
		_emit_error("malformed_server_event", "Backend sent malformed JSON.", false)
		return
	var event: Dictionary = json.data
	if not event.has("type") or not event.has("payload") or not event["payload"] is Dictionary:
		_emit_error("invalid_server_event", "Backend sent an invalid event envelope.", false)
		return
	if str(event.get("session_id", "")) != _session_id:
		_emit_error("session_mismatch", "Backend event belongs to another session.", false)
		return
	var event_type := str(event["type"])
	var payload: Dictionary = event["payload"]
	match event_type:
		"session.ready":
			_session_ready = true
			_conversation_state = str(payload.get("state", "READY"))
			_last_ping_ms = Time.get_ticks_msec()
			session_ready.emit()
		"state.changed":
			_conversation_state = str(payload.get("state", ""))
			if _conversation_state != "LISTENING":
				_audio_sending = false
			state_changed.emit(_conversation_state)
		"npc.text.delta":
			npc_text_delta.emit(str(payload.get("text", "")))
		"npc.text.final":
			npc_text_final.emit(payload)
		"audio.ready":
			audio_ready.emit(payload)
		"audio.received":
			audio_received.emit(payload)
		"audio.auto_stopped":
			_audio_sending = false
			audio_auto_stopped.emit(payload)
		"vad.speech_started":
			vad_speech_started.emit(payload)
		"vad.speech_ended":
			vad_speech_ended.emit(payload)
		"transcript.final":
			transcript_final.emit(payload)
		"npc.audio.ready":
			npc_audio_ready.emit(payload)
		"error":
			_emit_error(
				str(payload.get("code", "unknown_error")),
				str(payload.get("message", "Unknown session error.")),
				bool(payload.get("fatal", false))
			)
		"pong":
			_last_ping_ms = Time.get_ticks_msec()
		_:
			_emit_error("unsupported_server_event", "Unsupported backend event: %s" % event_type, false)

func _handle_closed() -> void:
	var was_intentional := _intentional_close
	_socket = null
	_session_ready = false
	_start_sent = false
	_audio_sending = false
	_conversation_state = "DISCONNECTED"
	if not was_intentional:
		_emit_error("connection_closed", "WebSocket connection closed.", false)
	disconnected.emit()

func _fail_connection(code: String, message: String) -> void:
	if _socket != null:
		_socket.close()
	_socket = null
	_session_ready = false
	_audio_sending = false
	_conversation_state = "DISCONNECTED"
	_emit_error(code, message, false)
	disconnected.emit()

func _emit_error(code: String, message: String, fatal: bool) -> void:
	session_error.emit(code, message, fatal)
	voice_error.emit(code, message, fatal)

func _new_event_id() -> String:
	return "%d-%d" % [Time.get_unix_time_from_system(), Time.get_ticks_usec()]
