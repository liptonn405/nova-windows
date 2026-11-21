"""Fast common Russian/English commands, independent of the selected language model."""

import re
from .policy import Action

NUMBERS = {
    "один": 1,
    "первый": 1,
    "два": 2,
    "второй": 2,
    "три": 3,
    "третий": 3,
    "четыре": 4,
    "четвертый": 4,
    "пять": 5,
    "пятый": 5,
    "шесть": 6,
    "шестой": 6,
    "семь": 7,
    "седьмой": 7,
    "восемь": 8,
    "девять": 9,
    "десять": 10,
    "пятнадцать": 15,
    "двадцать": 20,
    "тридцать": 30,
    "сорок": 40,
    "пятьдесят": 50,
    "шестьдесят": 60,
    "семьдесят": 70,
    "восемьдесят": 80,
    "девяносто": 90,
    "сто": 100,
}


def norm(text):
    return " ".join(text.casefold().replace("ё", "е").split()).strip(" .!?")


def number(text):
    digits = re.findall(r"(?<!\w)-?\d+\b", text)
    if len(digits) > 1:
        raise ValueError("Укажи одно число.")
    if digits:
        return int(digits[0])
    parts = [NUMBERS[x] for x in re.findall(r"\w+", text) if x in NUMBERS]
    if len(parts) > 1 and not (len(parts) == 2 and parts[0] >= 20 and parts[0] % 10 == 0 and parts[1] < 10):
        raise ValueError("Уточни число.")
    return sum(parts) if parts else None


def parse(text):
    q = norm(text)
    q = re.sub(r"^(?:(?:нова|nova|пожалуйста|сэр)[, ]+)+", "", q)
    q = re.sub(r"^(?:можешь|можете)\s+", "", q)
    for a, b in {
        "открыть": "открой",
        "запустить": "запусти",
        "переключить": "переключи",
        "включить": "включи",
    }.items():
        q = re.sub("^" + a + r"\b", b, q)
    q = re.sub(r"^(открой|запусти|включи) (?:мне |пожалуйста )+", r"\1 ", q)
    q = re.sub(r"[, ]+пожалуйста$", "", q)
    if q in ("проверь компьютер", "проверь систему", "состояние системы", "system status"):
        return Action("system", {})
    if q in ("покажи приложения", "список приложений"):
        return Action("list_apps", {})
    if q in ("покажи окна", "список окон"):
        return Action("list_windows", {})
    if q in ("покажи файлы", "список файлов"):
        return Action("list_files", {"path": "."})
    if q in ("что играет", "какая песня играет"):
        return Action("media", {"operation": "info"})
    if q in ("следующий трек", "переключи трек", "включи следующий трек", "следующая песня", "next track"):
        return Action("media", {"operation": "next"})
    if q in ("предыдущий трек", "включи предыдущий трек", "previous track"):
        return Action("media", {"operation": "previous"})
    if q in ("пауза", "останови музыку", "поставь на паузу", "поставь музыку на паузу", "pause"):
        return Action("media", {"operation": "pause"})
    if q in ("продолжи музыку", "продолжи воспроизведение", "включи музыку"):
        return Action("media", {"operation": "play"})
    if q in ("выключи звук", "без звука", "mute"):
        return Action("mute", {"enabled": True})
    if q in ("включи звук", "верни звук", "unmute"):
        return Action("mute", {"enabled": False})
    if re.match(r"^(?:сделай |прибавь |убавь |громкость(?: |$)|звук(?: |$)|громче|тише)", q) and any(
        x in q for x in ("громк", "громче", "тише", "звук")
    ):
        n = number(q)
        delta = any(x in q for x in ("громче", "тише", "прибавь", "убавь"))
        if n is None and not delta:
            raise ValueError("Укажи громкость 0–100%.")
        n = 10 if n is None else n
        return Action(
            "volume_delta" if delta else "volume",
            {"percent": -n if any(x in q for x in ("тише", "убавь")) else n},
        )
    if re.match(r"^(?:открой|переключи(?:сь)?|перейди|покажи)\b", q) and re.search(r"\bстол\b", q):
        n = number(q)
        if n is None:
            raise ValueError("Укажи номер рабочего стола.")
        return Action("desktop", {"number": n})
    if re.match(r"^(?:таймер|поставь таймер|засеки)\b", q):
        n = number(q)
        if n is None:
            raise ValueError("Укажи число минут.")
        return Action("timer", {"minutes": n})
    m = re.fullmatch(r"(?:найди в интернете|поищи в интернете|поиск)\s+(.+)", q)
    if m:
        return Action("search_web", {"query": m[1]})
    m = re.fullmatch(r"(?:прочитай файл)\s+(.+)", text.strip(), re.I)
    if m:
        return Action("read_file", {"path": m[1].strip()})
    m = re.fullmatch(r"(открой|запусти|open)\s+(.+)", q)
    if m:
        if re.search(r"\b(?:и|затем|после)\b|[;]", m[2]):
            raise ValueError("Для нескольких действий используй кнопку «План».")
        return Action("open_app", {"query": m[2]})
    m = re.fullmatch(r"(сверни|разверни|восстанови|покажи окно)\s+(.+)", q)
    if m:
        return Action(
            "window",
            {
                "query": re.sub(r"^окно\s+", "", m[2]),
                "operation": {
                    "сверни": "minimize",
                    "разверни": "maximize",
                    "восстанови": "restore",
                    "покажи окно": "focus",
                }[m[1]],
            },
        )
    return None


HELP = "Открой браузер; открой стим; рабочий стол: «переключись на стол 3»; следующий трек; пауза; громкость 30; таймер 25 минут; проверь компьютер; покажи файлы; прочитай файл README.md. Для составной задачи нажми «План»: увидишь список действий перед выполнением."
