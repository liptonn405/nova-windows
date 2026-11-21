"""Windows SAPI output; optional offline push-to-talk via Vosk. No idle recording."""

import json
from pathlib import Path
import queue
import sys
import threading
import time
from .windows import com


class Voice:
    def __init__(self, status=lambda _: None):
        self.status = status
        self._cancel = threading.Event()
        self._thread = None

    @staticmethod
    def voices():
        if sys.platform != "win32":
            return []
        with com():
            import win32com.client

            speaker = win32com.client.Dispatch("SAPI.SpVoice")
            return [(v.Id, v.GetDescription()) for v in speaker.GetVoices()]

    def stop(self):
        self._cancel.set()

    def speak(self, text, settings):
        self.stop()
        cancel = threading.Event()
        self._cancel = cancel

        def run():
            try:
                with com():
                    import win32com.client

                    speaker = win32com.client.Dispatch("SAPI.SpVoice")
                    if settings.voice_id:
                        found = [v for v in speaker.GetVoices() if v.Id == settings.voice_id]
                        if not found:
                            raise RuntimeError("Выбранный голос Windows удалён. Выбери другой в настройках.")
                        speaker.Voice = found[0]
                    speaker.Rate = settings.voice_rate
                    self.status("speaking")
                    speaker.Speak(text[:6000], 1 | 16)  # Async and plain text, never interpret SSML.
                    while not speaker.WaitUntilDone(40):
                        if cancel.is_set():
                            speaker.Speak("", 2)
                            return
                    if not cancel.is_set():
                        self.status("idle")
            except Exception as e:
                if not cancel.is_set():
                    self.status("Голос: " + str(e)[:180])

        self._thread = threading.Thread(target=run, daemon=True)
        self._thread.start()


def recognize(settings, cancel, status=lambda _: None):
    """Capture at most 12 seconds, stop after a complete utterance. Model freed on return."""
    try:
        import sounddevice as sd
        from vosk import Model, KaldiRecognizer, SetLogLevel
    except ImportError as e:
        raise RuntimeError(
            'Установи поддержку микрофона: .venv\\Scripts\\python -m pip install -e ".[voice]"'
        ) from e
    root = Path(settings.speech_model)
    if not root.is_dir() or not (root / "am").is_dir():
        raise RuntimeError("Выбери распакованную модель Vosk в настройках. См. README.")
    SetLogLevel(-1)
    status("Загрузка распознавания…")
    model = Model(str(root))
    recognizer = KaldiRecognizer(model, 16000)
    chunks = queue.Queue(maxsize=30)

    def callback(data, frames, timing, flags):
        if flags:
            status("Микрофон: " + str(flags))
        try:
            chunks.put_nowait(bytes(data))
        except queue.Full:
            pass

    text = ""
    started = time.monotonic()
    status("Говори… (до 12 секунд)")
    device = None if settings.microphone_device < 0 else settings.microphone_device
    with sd.RawInputStream(
        samplerate=16000, blocksize=4000, device=device, dtype="int16", channels=1, callback=callback
    ):
        while time.monotonic() - started < 12 and not cancel.is_set():
            try:
                data = chunks.get(timeout=0.2)
            except queue.Empty:
                continue
            if recognizer.AcceptWaveform(data):
                text = json.loads(recognizer.Result()).get("text", "")
                if text:
                    break
        if not text and not cancel.is_set():
            text = json.loads(recognizer.FinalResult()).get("text", "")
    if cancel.is_set():
        raise RuntimeError("Запись остановлена.")
    if not text:
        raise RuntimeError("Речь не распознана. Проверь микрофон и русский язык модели.")
    return text
