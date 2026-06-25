class_name AIVoiceCapture
extends Node

signal capture_warning(message: String)

const CAPTURE_BUS_NAME := "VoiceCapture"
const NO_AUDIO_WARNING := "No microphone audio detected. Check the selected Windows input device."

@export var session_client_path: NodePath
@export var no_frames_timeout_seconds := 1.5

@onready var microphone_player: AudioStreamPlayer = $Microphone

var _session_client: Node
var _capture_effect: AudioEffectCapture
var _capturing := false
var _started_ms := 0
var _frames_captured := 0
var _bytes_transmitted := 0
var _warned_no_audio := false
var _last_error := ""

func _ready() -> void:
	_session_client = get_node_or_null(session_client_path)
	_prepare_capture_bus()
	print("Voice input driver: %s; device: %s" % [AudioServer.get_driver_name(), AudioServer.input_device])

func _process(_delta: float) -> void:
	if not _capturing or _capture_effect == null:
		return
	var frames_available := _capture_effect.get_frames_available()
	if frames_available > 0:
		if _frames_captured == 0:
			print("Voice capture first chunk: frames_available=%d" % frames_available)
		var frames := _capture_effect.get_buffer(frames_available)
		var pcm := _stereo_frames_to_pcm16_mono(frames)
		_frames_captured += frames.size()
		if not pcm.is_empty() and _session_client.send_audio_frame(pcm):
			_bytes_transmitted += pcm.size()
	elif not _warned_no_audio and Time.get_ticks_msec() - _started_ms >= int(no_frames_timeout_seconds * 1000.0):
		_warned_no_audio = true
		_last_error = NO_AUDIO_WARNING
		capture_warning.emit(_last_error)

func start_capture() -> bool:
	_last_error = ""
	if _capturing:
		_last_error = "Microphone capture is already active."
		return false
	if not bool(ProjectSettings.get_setting("audio/driver/enable_input", false)):
		_last_error = "Microphone input is disabled in the Godot project settings."
		return false
	var devices := AudioServer.get_input_device_list()
	if devices.is_empty():
		_last_error = "No audio input device is available."
		return false
	if _session_client == null or not _session_client.is_session_ready():
		_last_error = "Voice session is not ready."
		return false
	if _capture_effect == null:
		_prepare_capture_bus()
	if _capture_effect == null:
		_last_error = "Microphone capture effect is not ready."
		return false

	var sample_rate := int(AudioServer.get_mix_rate())
	if not _session_client.start_audio(sample_rate):
		_last_error = "Could not start the streamed audio turn."
		return false
	_capture_effect.clear_buffer()
	_frames_captured = 0
	_bytes_transmitted = 0
	_warned_no_audio = false
	_started_ms = Time.get_ticks_msec()
	_capturing = true
	microphone_player.play()
	print(
		"Voice capture started: driver=%s device=%s bus_ready=true effect_ready=true sample_rate=%d" % [
			AudioServer.get_driver_name(), AudioServer.input_device, sample_rate
		]
	)
	return true

func stop_capture(reason: String = "player_released") -> int:
	if not _capturing:
		return 0
	_process(0.0)
	_capturing = false
	microphone_player.stop()
	_session_client.stop_audio(reason)
	print("Voice capture stopped: frames=%d bytes_transmitted=%d" % [_frames_captured, _bytes_transmitted])
	return _bytes_transmitted

func stop_capture_from_server() -> int:
	if not _capturing:
		return _bytes_transmitted
	_capturing = false
	microphone_player.stop()
	print(
		"Voice capture auto-stopped: frames=%d bytes_transmitted=%d"
		% [_frames_captured, _bytes_transmitted]
	)
	return _bytes_transmitted

func cancel_capture() -> void:
	if _capturing:
		stop_capture("cancelled")

func is_capturing() -> bool:
	return _capturing

func get_bytes_transmitted() -> int:
	return _bytes_transmitted

func get_last_error() -> String:
	return _last_error

func _prepare_capture_bus() -> void:
	var bus_index := AudioServer.get_bus_index(CAPTURE_BUS_NAME)
	if bus_index == -1:
		AudioServer.add_bus()
		bus_index = AudioServer.bus_count - 1
		AudioServer.set_bus_name(bus_index, CAPTURE_BUS_NAME)
	AudioServer.set_bus_mute(bus_index, true)
	microphone_player.bus = CAPTURE_BUS_NAME
	for effect_index in range(AudioServer.get_bus_effect_count(bus_index)):
		var effect := AudioServer.get_bus_effect(bus_index, effect_index)
		if effect is AudioEffectCapture:
			_capture_effect = effect
			break
	if _capture_effect == null:
		_capture_effect = AudioEffectCapture.new()
		_capture_effect.buffer_length = 0.25
		AudioServer.add_bus_effect(bus_index, _capture_effect)
	print("Voice capture bus ready: %s; capture effect ready: %s" % [bus_index != -1, _capture_effect != null])

func _stereo_frames_to_pcm16_mono(frames: PackedVector2Array) -> PackedByteArray:
	var pcm := PackedByteArray()
	pcm.resize(frames.size() * 2)
	for index in range(frames.size()):
		var frame := frames[index]
		var mono := clampf((frame.x + frame.y) * 0.5, -1.0, 1.0)
		var sample := clampi(int(round(mono * 32767.0)), -32768, 32767)
		pcm.encode_s16(index * 2, sample)
	return pcm
