import os


_ORIGINAL_STT_MODE = os.environ.get("STT_MODE")
_ORIGINAL_TTS_MODE = os.environ.get("TTS_MODE")

os.environ["STT_MODE"] = "mock"
os.environ["TTS_MODE"] = "mock"


def pytest_unconfigure(config):
    if _ORIGINAL_STT_MODE is None:
        os.environ.pop("STT_MODE", None)
    else:
        os.environ["STT_MODE"] = _ORIGINAL_STT_MODE

    if _ORIGINAL_TTS_MODE is None:
        os.environ.pop("TTS_MODE", None)
    else:
        os.environ["TTS_MODE"] = _ORIGINAL_TTS_MODE
