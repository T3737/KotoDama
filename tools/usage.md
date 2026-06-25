# existing level → Excel
python tools/level_excel_converter.py pixel_farm_godot4/godot_skeleton/levels/farm.json farm.xlsx

# edited Excel → JSON, drop straight back into the levels folder
python tools/level_excel_converter.py farm.xlsx pixel_farm_godot4/godot_skeleton/levels/farm.json