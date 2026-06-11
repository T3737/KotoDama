class_name AIVoiceRecorder
extends Node

const CAPTURE_BUS_NAME := "Record"
const WAV_SAVE_BASE := "user://voice_recording"
const WAV_PATH := "user://voice_recording.wav"

var _record_effect: AudioEffectRecord
var _last_recording: AudioStreamWAV
var _last_error := ""

@onready var _microphone_player: AudioStreamPlayer = $AudioStreamRecord
@onready var _playback_player: AudioStreamPlayer = $Playback


func _ready() -> void:
	_print_audio_input_diagnostics()
	if not _setup_capture_bus():
		push_error(_last_error)
		return
	if _microphone_player.stream == null:
		_microphone_player.stream = AudioStreamMicrophone.new()
	_microphone_player.bus = CAPTURE_BUS_NAME
	if not _microphone_player.playing:
		_microphone_player.play()
	print("Voice recorder ready")
	_print_recorder_diagnostics()


func start_recording() -> bool:
	_last_error = ""
	if _record_effect == null:
		_last_error = "Voice: recorder unavailable"
		push_error("Voice recorder has no AudioEffectRecord.")
		return false
	if _record_effect.is_recording_active():
		return false
	_remove_temporary_wav()
	if not _microphone_player.playing:
		_microphone_player.play()
	if not _microphone_player.playing:
		_last_error = "Voice: microphone player unavailable"
		push_error("Microphone AudioStreamPlayer did not start.")
		return false
	_record_effect.set_recording_active(true)
	if not _record_effect.is_recording_active():
		_last_error = "Voice: microphone input unavailable"
		push_error("Voice recorder could not activate microphone recording.")
		return false
	print("Voice recording started")
	return true


func stop_recording() -> String:
	_last_error = ""
	if _record_effect == null:
		_last_error = "Voice: recorder unavailable"
		push_error("Voice recorder has no AudioEffectRecord.")
		return ""
	if not _record_effect.is_recording_active():
		_last_error = "Voice: no active recording"
		return ""

	var recording: AudioStreamWAV = _record_effect.get_recording()
	_record_effect.set_recording_active(false)
	print("Voice recording stopped")
	if recording == null or recording.data.is_empty():
		_last_error = "Voice: no audio recorded"
		print("Voice recording stopped without audio data")
		return ""
	_last_recording = recording

	var absolute_path := ProjectSettings.globalize_path(WAV_PATH)
	var save_error := recording.save_to_wav(WAV_SAVE_BASE)
	var file_exists := FileAccess.file_exists(WAV_PATH)
	var file_size := get_saved_file_size()
	print("Voice WAV Godot path: ", WAV_PATH)
	print("Voice WAV absolute path: ", absolute_path)
	print("Voice WAV save result: ", save_error)
	print("Voice WAV exists: ", file_exists)
	print("Voice WAV file size: ", file_size, " bytes")
	if save_error != OK or not file_exists:
		_last_error = "Voice: recording file missing/empty"
		print("Voice WAV save failed")
		return ""
	if file_size <= 0:
		_last_error = "Voice: recording file missing/empty"
		print("Voice WAV save produced an empty file")
		_remove_temporary_wav()
		return ""
	print("Voice WAV saved: %s (%d bytes)" % [WAV_PATH, file_size])
	return WAV_PATH


func cancel_recording() -> void:
	if _record_effect != null and _record_effect.is_recording_active():
		_record_effect.get_recording()
		_record_effect.set_recording_active(false)
		print("Voice recording cancelled")
	_remove_temporary_wav()


func is_recording() -> bool:
	return _record_effect != null and _record_effect.is_recording_active()


func get_last_error() -> String:
	return _last_error if not _last_error.is_empty() else "Voice: recorder unavailable"


func get_saved_file_size() -> int:
	if not FileAccess.file_exists(WAV_PATH):
		return 0
	var file := FileAccess.open(WAV_PATH, FileAccess.READ)
	return file.get_length() if file != null else 0


func play_recording_debug() -> bool:
	if _last_recording == null or _last_recording.data.is_empty():
		print("Voice playback unavailable: no recording is loaded")
		return false
	_playback_player.stream = _last_recording
	_playback_player.play()
	print("Voice debug playback started")
	return true


func remove_temporary_wav() -> void:
	_remove_temporary_wav()


func _setup_capture_bus() -> bool:
	var bus_index := AudioServer.get_bus_index(CAPTURE_BUS_NAME)
	if bus_index == -1:
		AudioServer.add_bus()
		bus_index = AudioServer.bus_count - 1
		if bus_index < 0:
			_last_error = "Voice: audio bus unavailable"
			return false
		AudioServer.set_bus_name(bus_index, CAPTURE_BUS_NAME)
		print("Record bus created")
	else:
		print("Record bus exists")
	AudioServer.set_bus_mute(bus_index, true)
	print("Record bus index: ", bus_index)
	print("Record bus effect count: ", AudioServer.get_bus_effect_count(bus_index))

	for effect_index in range(AudioServer.get_bus_effect_count(bus_index)):
		var effect := AudioServer.get_bus_effect(bus_index, effect_index)
		if effect is AudioEffectRecord:
			_record_effect = effect
			print("AudioEffectRecord found at effect index ", effect_index)
			return true

	var record_effect := AudioEffectRecord.new()
	record_effect.format = AudioStreamWAV.FORMAT_16_BITS
	AudioServer.add_bus_effect(bus_index, record_effect)
	for effect_index in range(AudioServer.get_bus_effect_count(bus_index)):
		var effect := AudioServer.get_bus_effect(bus_index, effect_index)
		if effect is AudioEffectRecord:
			_record_effect = effect
			print("AudioEffectRecord created at effect index ", effect_index)
			return true

	_last_error = "Voice: recorder unavailable"
	return false


func _remove_temporary_wav() -> void:
	if FileAccess.file_exists(WAV_PATH):
		DirAccess.remove_absolute(ProjectSettings.globalize_path(WAV_PATH))


func _print_audio_input_diagnostics() -> void:
	var input_enabled := bool(ProjectSettings.get_setting("audio/driver/enable_input", false))
	print("Audio input enabled: ", input_enabled)
	if not input_enabled:
		print(
			"Microphone input is disabled. Enable Project Settings > Audio > Driver > Enable Input."
		)
	# On Windows, also allow microphone access for desktop apps/Godot under:
	# Settings > Privacy & security > Microphone.


func _print_recorder_diagnostics() -> void:
	var bus_index := AudioServer.get_bus_index(CAPTURE_BUS_NAME)
	print("Record bus exists: ", bus_index != -1)
	print("Record bus index: ", bus_index)
	print(
		"Record bus effect count: ",
		AudioServer.get_bus_effect_count(bus_index) if bus_index != -1 else 0
	)
	print("AudioEffectRecord available: ", _record_effect != null)
	print("Microphone player exists: ", _microphone_player != null)
	print(
		"Microphone player playing: ",
		_microphone_player.playing if _microphone_player != null else false
	)
	print(
		"Microphone player bus: ",
		_microphone_player.bus if _microphone_player != null else "<missing>"
	)
