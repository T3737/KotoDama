extends CanvasLayer

const STAMINA_MAX := 100.0
const HIDE_DELAY  := 2.0     # seconds after full before hiding

@onready var _bar: ColorRect      = $Bar
@onready var _fill: ColorRect     = $Bar/Fill

var _hide_timer := 0.0
var _visible    := false

func _ready() -> void:
	add_to_group("stamina_bar")
	$Bar.visible = false

func update(stamina: float) -> void:
	_fill.size.x = (_bar.size.x * stamina / STAMINA_MAX)
	
	if stamina < STAMINA_MAX:
		_hide_timer = HIDE_DELAY
		if not _visible:
			_bar.visible = true
			_visible = true
	
func _process(delta: float) -> void:
	if _visible and _hide_timer > 0.0:
		_hide_timer -= delta
		if _hide_timer <= 0.0:
			_bar.visible = false
			_visible = false