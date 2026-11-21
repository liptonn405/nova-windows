"""Structured actions, complete-plan validation, and a confined file workspace."""

from dataclasses import dataclass
import json
from pathlib import Path
import re

SCHEMA = {
    "open_app": {"query": str},
    "list_apps": {},
    "list_windows": {},
    "window": {"query": str, "operation": str},
    "desktop": {"number": int},
    "media": {"operation": str},
    "volume": {"percent": int},
    "volume_delta": {"percent": int},
    "mute": {"enabled": bool},
    "system": {},
    "list_files": {"path": str},
    "read_file": {"path": str},
    "create_note": {"name": str, "text": str},
    "search_web": {"query": str},
    "timer": {"minutes": int},
}


@dataclass(frozen=True)
class Action:
    tool: str
    args: dict

    def dump(self):
        return {"tool": self.tool, "args": dict(self.args)}


def validate(action):
    if not isinstance(action, dict) or set(action) != {"tool", "args"}:
        raise ValueError("Действие должно содержать только tool и args.")
    name = action["tool"]
    args = action["args"]
    if (
        not isinstance(name, str)
        or name not in SCHEMA
        or not isinstance(args, dict)
        or set(args) != set(SCHEMA[name])
    ):
        raise ValueError("Неизвестный инструмент или неверные аргументы.")
    for key, kind in SCHEMA[name].items():
        if type(args[key]) is not kind:
            raise ValueError("Неверный тип аргумента " + key)
        if kind is str and (len(args[key]) > 8000 or "\0" in args[key]):
            raise ValueError("Слишком длинный аргумент.")
    if name == "desktop" and not 1 <= args["number"] <= 20:
        raise ValueError("Номер стола: 1–20.")
    if name == "volume" and not 0 <= args["percent"] <= 100:
        raise ValueError("Громкость: 0–100%.")
    if name == "volume_delta" and not -100 <= args["percent"] <= 100:
        raise ValueError("Изменение громкости: −100…100.")
    if name == "timer" and not 1 <= args["minutes"] <= 180:
        raise ValueError("Таймер: 1–180 минут.")
    if name == "window" and args["operation"] not in ("focus", "minimize", "maximize", "restore"):
        raise ValueError("Неизвестная операция с окном.")
    if name == "media" and args["operation"] not in ("next", "previous", "play", "pause", "info"):
        raise ValueError("Неизвестная операция плеера.")
    if name == "create_note" and not re.fullmatch(r"[\wА-Яа-яЁё .-]{1,80}\.md", args["name"]):
        raise ValueError("Название заметки должно оканчиваться на .md, без путей.")
    if name == "create_note" and args["name"].split(".")[0].upper() in {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *[f"COM{i}" for i in range(1, 10)],
        *[f"LPT{i}" for i in range(1, 10)],
    }:
        raise ValueError("Это зарезервированное имя устройства Windows.")
    return Action(name, dict(args))


def parse_plan(raw):
    data = json.loads(raw)
    if (
        not isinstance(data, dict)
        or set(data) != {"summary", "actions"}
        or not isinstance(data["summary"], str)
        or len(data["summary"]) > 1000
    ):
        raise ValueError("Модель не вернула понятный план.")
    actions = data["actions"]
    if not isinstance(actions, list) or not 1 <= len(actions) <= 6:
        raise ValueError("План должен содержать от 1 до 6 действий.")
    return data["summary"], [validate(x) for x in actions]


class Workspace:
    def __init__(self, root):
        self.root = Path(root).expanduser().resolve()

    def path(self, relative):
        p = Path(relative)
        if p.is_absolute() or ".." in p.parts or ":" in relative or "\\" in relative:
            raise ValueError("Укажи относительный путь внутри рабочей папки, через /.")
        target = (self.root / p).resolve()
        if not target.is_relative_to(self.root):
            raise ValueError("Путь выходит за рабочую папку.")
        return target

    def list(self, relative="."):
        p = self.path(relative)
        if p == self.root and not p.exists():
            return []
        return [
            {"name": x.name, "directory": x.is_dir()}
            for x in sorted(p.iterdir(), key=lambda x: x.name.casefold())[:100]
        ]

    def read(self, relative):
        p = self.path(relative)
        if p.suffix.lower() not in (
            ".txt",
            ".md",
            ".py",
            ".js",
            ".ts",
            ".json",
            ".toml",
            ".yaml",
            ".yml",
            ".csv",
            ".c",
            ".h",
            ".cpp",
        ):
            raise ValueError("Поддерживаются только текстовые файлы и исходники.")
        if p.stat().st_size > 64000:
            raise ValueError("Файл больше 64 КБ. Выбери меньший файл.")
        return p.read_text(encoding="utf-8")

    def note(self, name, text):
        validate({"tool": "create_note", "args": {"name": name, "text": text}})
        self.root.mkdir(parents=True, exist_ok=True)
        p = self.path(name)
        with p.open("x", encoding="utf-8") as out:
            out.write(text)
        return "Создана заметка: " + str(p)
