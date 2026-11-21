import json
import threading
import httpx
import pytest
from nova.intents import parse
from nova.policy import Action, validate, parse_plan, Workspace
from nova.agent import Executor
from nova.config import local_url, Settings
from nova.ollama import Ollama, Cancelled
from nova.behavior import Behavior
from nova.windows import App, resolve_app


@pytest.mark.parametrize(
    "text,tool,args",
    [
        ("открой браузер", "open_app", {"query": "браузер"}),
        ("NOVA, открой мне стим пожалуйста", "open_app", {"query": "стим"}),
        ("можешь открыть браузер", "open_app", {"query": "браузер"}),
        ("переключись на рабочий стол номер 3", "desktop", {"number": 3}),
        ("открой третий рабочий стол", "desktop", {"number": 3}),
        ("громкость 30", "volume", {"percent": 30}),
        ("сделай громче на десять", "volume_delta", {"percent": 10}),
        ("сделай тише", "volume_delta", {"percent": -10}),
        ("выключи звук", "mute", {"enabled": True}),
        ("следующий трек", "media", {"operation": "next"}),
        ("поставь музыку на паузу", "media", {"operation": "pause"}),
        ("таймер двадцать пять минут", "timer", {"minutes": 25}),
        ("прочитай файл MyNote.md", "read_file", {"path": "MyNote.md"}),
        ("проверь систему", "system", {}),
        ("разверни окно Chromium", "window", {"query": "chromium", "operation": "maximize"}),
    ],
)
def test_fast_commands(text, tool, args):
    action = parse(text)
    assert action == Action(tool, args)
    validate(action.dump())


@pytest.mark.parametrize("text", ["привет", "кто ты", "как открыть браузер?", "расскажи про Steam"])
def test_conversation_does_not_trigger_actions(text):
    assert parse(text) is None


@pytest.mark.parametrize("text", ["открой стим и браузер", "переключись на стол 1 или 2", "громкость"])
def test_ambiguous_commands(text):
    with pytest.raises(ValueError):
        parse(text)


@pytest.mark.parametrize(
    "payload",
    [
        {"tool": "shell", "args": {"command": "cmd /c del *"}},
        {"tool": "desktop", "args": {"number": True}},
        {"tool": "desktop", "args": {"number": 21}},
        {"tool": "volume", "args": {"percent": 101}},
        {"tool": "open_app", "args": {"query": "Steam", "hidden": True}},
        {"tool": "media", "args": {"operation": "like"}},
        {"tool": "create_note", "args": {"name": "../x.md", "text": "x"}},
        {"tool": "window", "args": {"query": "x", "operation": "close"}},
    ],
)
def test_invalid_actions(payload):
    with pytest.raises(ValueError):
        validate(payload)


def test_entire_plan_validated_before_execution(tmp_path):
    calls = []

    class Fake:
        def desktop(self, number):
            calls.append(number)

    executor = Executor(Fake(), tmp_path)
    with pytest.raises(ValueError):
        executor.execute_plan([Action("desktop", {"number": 2}), Action("shell", {})], threading.Event())
    assert calls == []


def test_plan_stops_on_failure(tmp_path):
    calls = []

    class Fake:
        def desktop(self, number):
            calls.append(number)
            raise RuntimeError("failed")

    results = Executor(Fake(), tmp_path).execute_plan(
        [Action("desktop", {"number": 2}), Action("desktop", {"number": 3})], threading.Event()
    )
    assert calls == [2]
    assert results[0]["error"] == "failed"


def test_plan_json():
    summary, actions = parse_plan(
        json.dumps({"summary": "Открыть Steam", "actions": [{"tool": "open_app", "args": {"query": "стим"}}]})
    )
    assert actions[0].tool == "open_app"
    with pytest.raises(ValueError):
        parse_plan('{"summary":"x","actions":[]}')


@pytest.mark.parametrize("path", ["../secret", "/tmp/x", "C:/Windows/x", "C:\\Windows\\x", "foo/../../bar"])
def test_workspace_boundary(tmp_path, path):
    with pytest.raises(ValueError):
        Workspace(tmp_path).path(path)


def test_workspace_symlink(tmp_path):
    inside = tmp_path / "inside"
    inside.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        (inside / "link").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("Windows symlink privileges unavailable")
    with pytest.raises(ValueError):
        Workspace(inside).path("link/secret.txt")


def test_note_never_overwrites(tmp_path):
    files = Workspace(tmp_path)
    files.note("note.md", "first")
    assert files.read("note.md") == "first"
    with pytest.raises(FileExistsError):
        files.note("note.md", "second")
    assert files.read("note.md") == "first"


def test_reject_binary_large_file(tmp_path):
    (tmp_path / "bin.exe").write_bytes(b"x")
    (tmp_path / "large.txt").write_text("x" * 64001)
    for name in ["bin.exe", "large.txt"]:
        with pytest.raises(ValueError):
            Workspace(tmp_path).read(name)


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com",
        "http://127.0.0.1.evil:11434",
        "http://user@localhost:11434",
        "http://localhost:11434/evil",
        "http://localhost:0",
    ],
)
def test_endpoint_is_local_only(url):
    with pytest.raises(ValueError):
        local_url(url)


def test_settings_roundtrip(tmp_path):
    path = tmp_path / "settings.json"
    s = Settings(workspace=str(tmp_path), model="custom:7b")
    s.save(path)
    assert Settings.load(path).model == "custom:7b"
    path.write_text("{oops")
    assert Settings.load(path).model == "qwen3:4b"


def test_ollama_stream_and_model_options():
    sent = []

    def handler(request):
        sent.append(json.loads(request.content))
        lines = [
            {"message": {"content": "При"}, "done": False},
            {"message": {"content": "вет"}, "done": True},
        ]
        return httpx.Response(200, text="\n".join(json.dumps(x) for x in lines))

    client = Ollama("http://localhost:11434", "qwen3:4b", transport=httpx.MockTransport(handler))
    chunks = []
    assert client.chat([{"role": "user", "content": "привет"}], threading.Event(), chunks.append) == "Привет"
    assert chunks == ["При", "вет"]
    assert sent[0]["think"] is False
    assert sent[0]["keep_alive"] == 0
    client.model = "other:latest"
    client.chat([], threading.Event())
    assert "think" not in sent[1]


def test_ollama_cancelled():
    event = threading.Event()
    event.set()
    with pytest.raises(Cancelled):
        Ollama("http://localhost:11434", "x").chat([], event)


def test_ollama_missing_done():
    client = Ollama(
        "http://localhost:11434",
        "x",
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, text='{"message":{"content":"partial"}}')
        ),
    )
    with pytest.raises(RuntimeError, match="не завершила"):
        client.chat([], threading.Event())


def test_ollama_unloads_only_selected_model():
    captured = []

    def handler(r):
        captured.append((r.url.path, json.loads(r.content)))
        return httpx.Response(200, json={})

    Ollama("http://localhost:11434", "chosen:4b", transport=httpx.MockTransport(handler)).unload()
    assert captured == [("/api/generate", {"model": "chosen:4b", "keep_alive": 0})]


def test_app_alias_prefers_chromium():
    apps = [App("Chrome", "chrome.exe"), App("Chromium", "chromium.exe"), App("Steam", "steam.exe")]
    assert resolve_app("браузер", apps).name == "Chromium"
    assert resolve_app("стим", apps).name == "Steam"
    with pytest.raises(RuntimeError):
        resolve_app("cmd /c something", apps)


def test_attention_expires_and_emotion_changes():
    b = Behavior(seed=2)
    for _ in range(120):
        b.update(1 / 60, (1, 1))
    assert b.attention_until < b.now
    b.emotion("angry", 0.5)
    for _ in range(60):
        b.update(1 / 60, (1, 1))
    assert b.mood != "angry"


def test_frame_rate_independent_and_bounded():
    a = Behavior(2)
    b = Behavior(2)
    for _ in range(60):
        a.update(1 / 60, (1, -1))
    for _ in range(30):
        b.update(1 / 30, (1, -1))
    assert abs(a.look_x - b.look_x) < 0.001
    assert -1 <= a.look_x <= 1 and -1 <= a.look_y <= 1


def test_audio_pulse_visible():
    b = Behavior()
    b.music = True
    for _ in range(20):
        b.update(1 / 60, (0, 0), 0.8)
    assert b.eyes()[3] > 1.2


@pytest.mark.parametrize("name", ["CON.md", "aux.md", "COM1.md", "LPT9.txt.md"])
def test_windows_device_names_rejected(tmp_path, name):
    with pytest.raises(ValueError):
        Workspace(tmp_path).note(name, "test")


def test_empty_workspace_lists_without_creating_directory(tmp_path):
    root = tmp_path / "new"
    assert Workspace(root).list() == []
    assert not root.exists()
