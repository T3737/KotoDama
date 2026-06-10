class_name NPCProfileStore
extends RefCounted

const PROFILE_DIRECTORY := "res://data/npcs"

static func load_profile(npc_id: String) -> Dictionary:
	var path := "%s/%s.json" % [PROFILE_DIRECTORY, npc_id]
	if not FileAccess.file_exists(path):
		push_error("Missing NPC profile: %s" % path)
		return {}
	var file := FileAccess.open(path, FileAccess.READ)
	if file == null:
		push_error("Could not open NPC profile: %s" % path)
		return {}
	var json := JSON.new()
	if json.parse(file.get_as_text()) != OK or not json.data is Dictionary:
		push_error("NPC profile is not a JSON object: %s" % path)
		return {}
	var parsed: Dictionary = json.data
	if str(parsed.get("id", "")) != npc_id:
		push_error("NPC profile ID does not match filename: %s" % path)
		return {}
	return parsed
