"""Read-only dependency/connectivity report. Does not start apps or alter Windows."""

import importlib
import platform
import sys
from nova.config import Settings, data_dir
from nova.ollama import Ollama
from nova.voice import Voice

print("Python:", sys.version.split()[0], platform.machine())
print("OS:", platform.platform())
print("Settings:", data_dir() / "settings.json")
for package in [
    "PySide6",
    "httpx",
    "psutil",
    "win32gui",
    "pycaw.pycaw",
    "pyvda",
    "winrt.windows.media.control",
    "vosk",
    "sounddevice",
]:
    try:
        importlib.import_module(package)
        print(package, "OK")
    except Exception as e:
        print(package, type(e).__name__, str(e)[:180])
settings = Settings.load()
try:
    print("Ollama models:", Ollama(settings.endpoint, settings.model).models())
except Exception as e:
    print("Ollama:", str(e))
try:
    print("SAPI voices:", [name for _, name in Voice.voices()])
except Exception as e:
    print("SAPI:", str(e))
