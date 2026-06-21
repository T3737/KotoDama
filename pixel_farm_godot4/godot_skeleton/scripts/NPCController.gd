class_name NPCController
extends Interactable

signal dialogue_requested(npc: NPCController)

@export var npc_id := "aiko"

var profile: Dictionary = {}

@onready var name_label: Label = $NameLabel
@onready var body_polygon: Polygon2D = $Body
@onready var accent_polygon: Polygon2D = $Accent
@onready var hair_polygon: Polygon2D = $Hair

func _ready() -> void:
	super._ready()
	add_to_group("ai_npc")
	profile = NPCProfileStore.load_profile(npc_id)
	if profile.is_empty():
		name_label.text = "Missing: " + npc_id
		monitoring = false
		return
	name_label.text = str(profile.get("display_name", npc_id.capitalize()))
	var colors: Dictionary = profile.get("colors", {})
	body_polygon.color = Color.from_string(str(colors.get("body", "#405CC7")), Color.BLUE)
	accent_polygon.color = Color.from_string(str(colors.get("accent", "#F2CC59")), Color.YELLOW)
	hair_polygon.color = Color.from_string(str(colors.get("hair", "#331A14")), Color.DARK_GRAY)

func _on_interact(_player: Node) -> void:
	if not profile.is_empty():
		dialogue_requested.emit(self)

func _on_body_entered(body: Node) -> void:
	super._on_body_entered(body)
	if body.is_in_group("player"):
		print("Player entered %s's interaction range" % npc_id)

func _on_body_exited(body: Node) -> void:
	super._on_body_exited(body)
	if body.is_in_group("player"):
		print("Player left %s's interaction range" % npc_id)
