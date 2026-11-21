"""Native Windows adapters; imports are delayed so pure logic is testable on Linux."""

from contextlib import contextmanager
from dataclasses import dataclass
import asyncio
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import webbrowser
from urllib.parse import quote_plus
import psutil


@contextmanager
def com():
    if sys.platform != "win32":
        raise RuntimeError("Эта команда доступна только в Windows. Сейчас режим демонстрации.")
    import pythoncom

    pythoncom.CoInitialize()
    try:
        yield
    finally:
        pythoncom.CoUninitialize()


@dataclass(frozen=True)
class App:
    name: str
    target: str
    kind: str = "exe"


ALIASES = {
    "браузер": ("chromium", "chrome", "firefox", "msedge", "edge"),
    "browser": ("chromium", "chrome", "firefox", "msedge", "edge"),
    "стим": ("steam",),
    "steam": ("steam",),
    "терминал": ("windows terminal", "terminal", "wt"),
    "калькулятор": ("calculator", "калькулятор", "calc"),
    "блокнот": ("notepad", "блокнот"),
    "яндекс музыка": ("yandex music", "яндекс музыка", "yandexmusic"),
    "яндекс музыку": ("yandex music", "яндекс музыка", "yandexmusic"),
    "vs code": ("visual studio code", "code"),
}


def resolve_app(query, apps):
    q = query.casefold().strip()
    for alias in ALIASES.get(q, (q,)):
        exact = [a for a in apps if a.name.casefold() == alias or Path(a.target).stem.casefold() == alias]
        if exact:
            return sorted(exact, key=lambda a: a.kind != "exe")[0]
        matches = [a for a in apps if alias in a.name.casefold()]
        if len(matches) == 1:
            return matches[0]
    matches = [a for a in apps if q in a.name.casefold()]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise RuntimeError(
            "Несколько приложений: " + ", ".join(a.name for a in matches[:5]) + ". Уточни название."
        )
    raise RuntimeError("Приложение не найдено: " + query + ". Проверь «Список приложений».")


class Windows:
    def __init__(self):
        self._apps = []
        self._apps_at = 0

    def apps(self):
        if sys.platform != "win32":
            return []
        if self._apps and time.monotonic() - self._apps_at < 60:
            return self._apps
        import winreg

        apps = []
        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
                try:
                    with winreg.OpenKey(
                        hive,
                        r"Software\Microsoft\Windows\CurrentVersion\App Paths",
                        0,
                        winreg.KEY_READ | view,
                    ) as parent:
                        for i in range(winreg.QueryInfoKey(parent)[0]):
                            name = winreg.EnumKey(parent, i)
                            try:
                                with winreg.OpenKey(parent, name) as child:
                                    target = winreg.QueryValue(child, None).strip('"')
                                if Path(target).is_file():
                                    apps.append(App(Path(name).stem, target))
                            except OSError:
                                pass
                except OSError:
                    pass
        for root in [
            Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs",
            Path(os.environ.get("PROGRAMDATA", "")) / "Microsoft/Windows/Start Menu/Programs",
        ]:
            for p in list(root.rglob("*.lnk"))[:2000] if root.exists() else []:
                apps.append(App(p.stem, str(p), "shortcut"))
        # Fixed script only. Never interpolate model/user text into PowerShell.
        command = "[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new(); @(Get-StartApps | Select-Object Name,AppID) | ConvertTo-Json -Compress"
        try:
            r = subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
                capture_output=True,
                timeout=12,
                creationflags=0x08000000,
            )
            if r.returncode == 0:
                values = json.loads(r.stdout.decode("utf-8-sig"))
                if isinstance(values, dict):
                    values = [values]
                apps.extend(
                    App(a["Name"], a["AppID"], "aumid") for a in values if a.get("Name") and a.get("AppID")
                )
        except (OSError, ValueError, subprocess.TimeoutExpired):
            pass
        for name, exe in [
            ("notepad", "notepad.exe"),
            ("calculator", "calc.exe"),
            ("Windows Terminal", "wt.exe"),
        ]:
            path = shutil.which(exe)
            if path:
                apps.append(App(name, path))
        unique = {(a.name.casefold(), a.target): a for a in apps}
        self._apps = sorted(unique.values(), key=lambda a: a.name.casefold())
        self._apps_at = time.monotonic()
        return self._apps

    def windows(self):
        if sys.platform != "win32":
            return []
        import win32gui, win32process

        result = []
        foreground = win32gui.GetForegroundWindow()

        def collect(hwnd, _):
            if not win32gui.IsWindowVisible(hwnd):
                return
            title = win32gui.GetWindowText(hwnd)
            if not title:
                return
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            if pid == os.getpid():
                return
            try:
                exe = psutil.Process(pid).exe()
            except psutil.Error:
                exe = ""
            result.append({"id": hwnd, "title": title[:180], "exe": exe, "focused": hwnd == foreground})

        win32gui.EnumWindows(collect, None)
        return result

    def focus(self, hwnd):
        import win32gui, win32con

        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        try:
            win32gui.SetForegroundWindow(hwnd)
        except Exception:
            pass
        for _ in range(10):
            if win32gui.GetForegroundWindow() == hwnd:
                return "Окно показано на экране."
            time.sleep(0.05)
        raise RuntimeError(
            "Окно открыто, но Windows не разрешила перехват фокуса. Выбери его на панели задач."
        )

    def open_app(self, query, cancel):
        if sys.platform != "win32":
            raise RuntimeError("Запуск приложений доступен в Windows.")
        q = query.casefold().strip()
        if q in ("файлы", "проводник"):
            os.startfile(str(Path.home()))
            return "Проводнику передан запрос открытия домашней папки."
        if q in ("настройки", "настройки звука"):
            os.startfile("ms-settings:sound" if q.endswith("звука") else "ms-settings:")
            return "Windows передан запрос открытия настроек."
        try:
            app = resolve_app(query, self.apps())
        except RuntimeError:
            if q not in ("браузер", "browser"):
                raise
            if not webbrowser.open("about:blank"):
                raise RuntimeError("Не удалось запустить браузер по умолчанию.")
            return "Запрос отправлен браузеру по умолчанию. Фокус окна не подтверждён."

        def matches(w):
            if app.kind == "exe":
                return os.path.normcase(w["exe"]) == os.path.normcase(app.target)
            return app.name.casefold() in w["title"].casefold()

        existing = [w for w in self.windows() if matches(w)]
        if existing:
            return self.focus(existing[0]["id"])
        if app.kind == "aumid":
            subprocess.Popen(["explorer.exe", "shell:AppsFolder\\" + app.target])
        else:
            os.startfile(app.target)
        until = time.monotonic() + 8
        while time.monotonic() < until:
            if cancel.is_set():
                raise RuntimeError("Остановлено. Уже запущенное приложение оставлено открытым.")
            found = [w for w in self.windows() if matches(w)]
            if found:
                return app.name + ": " + self.focus(found[0]["id"])
            time.sleep(0.15)
        return "Запуск " + app.name + " запрошен; появление окна не подтверждено. Повторно не запускаю."

    def window(self, query, operation):
        if sys.platform != "win32":
            raise RuntimeError("Окна доступны в Windows.")
        import win32gui, win32con

        q = query.casefold()
        items = self.windows()
        matches = (
            [w for w in items if w["focused"]]
            if q in ("текущее", "активное", "это")
            else [w for w in items if q in (w["title"] + " " + Path(w["exe"]).stem).casefold()]
        )
        if len(matches) != 1:
            raise RuntimeError(
                "Уточни окно: " + ", ".join(w["title"] for w in matches[:4])
                if matches
                else "Окно не найдено."
            )
        hwnd = matches[0]["id"]
        if operation == "focus":
            return self.focus(hwnd)
        flag = {
            "minimize": win32con.SW_MINIMIZE,
            "maximize": win32con.SW_MAXIMIZE,
            "restore": win32con.SW_RESTORE,
        }[operation]
        win32gui.ShowWindow(hwnd, flag)
        time.sleep(0.15)
        state = win32gui.GetWindowPlacement(hwnd)[1]
        expected = {
            "minimize": win32con.SW_SHOWMINIMIZED,
            "maximize": win32con.SW_SHOWMAXIMIZED,
            "restore": win32con.SW_SHOWNORMAL,
        }[operation]
        if state != expected:
            raise RuntimeError("Windows не подтвердила изменение окна.")
        return {
            "minimize": "Окно свёрнуто.",
            "maximize": "Окно развёрнуто.",
            "restore": "Размер окна восстановлен.",
        }[operation]

    def desktop(self, number):
        with com():
            try:
                from pyvda import VirtualDesktop, get_virtual_desktops

                while len(get_virtual_desktops()) < number:
                    VirtualDesktop.create()
                VirtualDesktop(number).go()
                for _ in range(20):
                    if VirtualDesktop.current().number == number:
                        return f"Рабочий стол {number} открыт."
                    time.sleep(0.05)
            except Exception as e:
                raise RuntimeError(
                    "Управление столами недоступно на этой сборке Windows. Обнови pyvda; Win+Tab остаётся доступным."
                ) from e
        raise RuntimeError("Переключение рабочего стола не подтверждено.")

    def pin(self, hwnd, follow):
        with com():
            from pyvda import AppView

            view = AppView(hwnd=hwnd)
            if follow:
                view.pin()
            else:
                view.unpin()
            if bool(view.is_pinned()) != follow:
                raise RuntimeError("Windows не подтвердила закрепление.")

    def audio(self, percent=None, delta=None, mute=None):
        with com():
            from pycaw.pycaw import AudioUtilities

            volume = AudioUtilities.GetSpeakers().EndpointVolume
            if mute is not None:
                volume.SetMute(int(mute), None)
                if bool(volume.GetMute()) != mute:
                    raise RuntimeError("Звук не переключился.")
                return "Звук выключен." if mute else "Звук включён."
            target = percent if delta is None else round(volume.GetMasterVolumeLevelScalar() * 100) + delta
            target = max(0, min(100, target))
            volume.SetMasterVolumeLevelScalar(target / 100, None)
            actual = round(volume.GetMasterVolumeLevelScalar() * 100)
            if abs(actual - target) > 1:
                raise RuntimeError("Громкость не подтверждена.")
            return f"Громкость {actual}%."

    async def _media(self, operation):
        from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionManager as Manager

        manager = await Manager.request_async()
        sessions = list(manager.get_sessions())
        preferred = [s for s in sessions if "yandex" in s.source_app_user_model_id.casefold()]
        session = preferred[0] if len(preferred) == 1 else manager.get_current_session()
        if session is None:
            raise RuntimeError("Нет активного плеера Windows. Открой музыку и выбери трек.")
        before = await session.try_get_media_properties_async()
        if operation == "info":
            return f"{before.artist} — {before.title}"
        names = {
            "next": "try_skip_next_async",
            "previous": "try_skip_previous_async",
            "play": "try_play_async",
            "pause": "try_pause_async",
        }
        accepted = await getattr(session, names[operation])()
        if not accepted:
            raise RuntimeError("Плеер отклонил команду.")
        for _ in range(20):
            await asyncio.sleep(0.1)
            info = session.get_playback_info()
            if operation in ("play", "pause") and int(info.playback_status) == (
                4 if operation == "play" else 5
            ):
                return "Музыка играет." if operation == "play" else "Музыка на паузе."
            after = await session.try_get_media_properties_async()
            if operation in ("next", "previous") and (after.title, after.artist) != (
                before.title,
                before.artist,
            ):
                return "Трек: " + after.title
        return "Плеер принял команду, но изменение состояния не подтверждено."

    def media(self, operation):
        if sys.platform != "win32":
            raise RuntimeError("Музыка доступна в Windows.")
        return asyncio.run(asyncio.wait_for(self._media(operation), timeout=7))

    def search(self, query):
        if not webbrowser.open("https://www.google.com/search?q=" + quote_plus(query)):
            raise RuntimeError("Браузер не принял запрос.")
        return "Поиск открыт в браузере: " + query

    def system(self):
        ram = psutil.virtual_memory()
        battery = psutil.sensors_battery()
        disk = psutil.disk_usage(Path.home().anchor)
        top = []
        for proc in psutil.process_iter(["name", "memory_info"]):
            try:
                top.append((proc.info["memory_info"].rss, proc.info["name"]))
            except (psutil.Error, TypeError, AttributeError):
                pass
        return {
            "ram_used_gb": round((ram.total - ram.available) / 1024**3, 2),
            "ram_available_gb": round(ram.available / 1024**3, 2),
            "cpu_percent": psutil.cpu_percent(interval=0.15),
            "disk_free_gb": round(disk.free / 1024**3, 1),
            "battery": round(battery.percent) if battery else None,
            "largest_processes": [
                {"name": name, "mb": round(size / 1024**2)} for size, name in sorted(top, reverse=True)[:5]
            ],
        }
