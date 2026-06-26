# Local Piper Voices

Place local Piper voice files here for TTS mode. A voice needs both matching
files:

```text
models/tts/voice_name.onnx
models/tts/voice_name.onnx.json
```

From the `backend` directory, configure:

```powershell
$env:TTS_MODE = "local"
$env:TTS_VOICE_MODEL = "models/tts/voice_name.onnx"
$env:TTS_VOICE_CONFIG = "models/tts/voice_name.onnx.json"
$env:TTS_DEBUG = "true"
```

Voice model binaries are intentionally ignored by Git. Do not download models
during gameplay.
