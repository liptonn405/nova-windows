from dataclasses import asdict, dataclass, fields
import json
import os
from pathlib import Path
from urllib.parse import urlparse


def data_dir():
    return Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local/share")) / "NOVA"


def local_url(value):
    value = value.strip().rstrip("/")
    parsed = urlparse(value)
    if (
        parsed.scheme != "http"
        or parsed.hostname not in ("localhost", "127.0.0.1", "::1")
        or parsed.username
        or parsed.password
        or parsed.path
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Ollama должна быть локальной: http://127.0.0.1:11434")
    try:
        port = parsed.port
    except ValueError as e:
        raise ValueError("Некорректный порт Ollama.") from e
    if port is not None and not 1 <= port <= 65535:
        raise ValueError("Некорректный порт.")
    return value


@dataclass
class Settings:
    model: str = "qwen3:4b"
    endpoint: str = "http://127.0.0.1:11434"
    workspace: str = str(Path.home() / "Documents" / "NOVA")
    keep_warm: bool = False
    voice: bool = True
    voice_id: str = ""
    voice_rate: int = 0
    microphone_device: int = -1
    speech_model: str = ""
    follow_desktops: bool = True
    x: int = -1
    y: int = -1

    @classmethod
    def load(cls, path=None):
        path = path or data_dir() / "settings.json"
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            obj = cls(**{k: v for k, v in raw.items() if k in {f.name for f in fields(cls)}})
            obj.validate()
            return obj
        except (OSError, ValueError, TypeError, AttributeError):
            return cls()

    def validate(self):
        self.endpoint = local_url(self.endpoint)
        if not isinstance(self.model, str) or not self.model.strip() or len(self.model) > 120:
            raise ValueError("Укажи имя модели Ollama.")
        for name in ("keep_warm", "voice", "follow_desktops"):
            if type(getattr(self, name)) is not bool:
                raise ValueError("Некорректный переключатель.")
        for name in ("voice_rate", "microphone_device", "x", "y"):
            if type(getattr(self, name)) is not int:
                raise ValueError("Некорректное число.")
        if not -5 <= self.voice_rate <= 5:
            raise ValueError("Темп голоса: от -5 до 5.")
        if not Path(self.workspace).is_absolute():
            raise ValueError("Выбери абсолютный путь рабочей папки.")
        if not isinstance(self.speech_model, str) or not isinstance(self.voice_id, str):
            raise ValueError("Некорректная настройка голоса.")

    def save(self, path=None):
        self.validate()
        path = path or data_dir() / "settings.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)
