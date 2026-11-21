"""NOVA desktop entry point. UI callbacks never perform network/model work."""

import argparse
from dataclasses import replace
import logging
from logging.handlers import RotatingFileHandler
import sys
import threading

from PySide6.QtCore import QObject, Signal, Qt, QTimer, QLockFile, QCoreApplication, QEvent
from PySide6.QtGui import QIcon, QPixmap, QPainter, QColor
from PySide6.QtWidgets import (
    QApplication,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QPlainTextEdit,
    QLineEdit,
    QDialog,
    QFormLayout,
    QComboBox,
    QCheckBox,
    QSpinBox,
    QFileDialog,
    QDialogButtonBox,
    QSystemTrayIcon,
    QMenu,
    QMessageBox,
)
from .config import Settings, data_dir
from .windows import Windows
from .monitor import Monitor
from .pet import Pet
from .voice import Voice, recognize
from .ollama import Ollama
from .intents import parse, HELP
from .agent import Executor, display
from .policy import validate

STYLE = """
QWidget {background:#080e0b;color:#d7e8dc;font-family:"Segoe UI";font-size:13px;}
QDialog {border:1px solid #246238;}
QLineEdit,QPlainTextEdit,QComboBox,QSpinBox {background:#0b1910;border:1px solid #225834;border-radius:9px;padding:8px;color:#deeee2;selection-background-color:#286139;}
QPushButton {background:#0d2416;border:1px solid #2d7945;border-radius:12px;padding:7px 11px;color:#a4efb4;}
QPushButton:hover {background:#164025;} QPushButton:disabled {color:#476451;border-color:#26392b;}
QLabel {background:transparent;} QCheckBox {padding:4px;} QMenu {background:#0c1a11;color:#d7e8dc;}
"""


class Signals(QObject):
    result = Signal(int, object)
    error = Signal(int, str)
    chunk = Signal(int, str)
    finished = Signal(int)
    voice = Signal(str)
    timer = Signal(int)


class Chat(QWidget):
    closed = Signal()
    submitted = Signal(bool)
    microphone = Signal()
    cancelled = Signal()
    settings_requested = Signal()

    def __init__(self):
        super().__init__()
        self.setWindowTitle("NOVA · чат")
        self.setWindowFlags(Qt.Tool | Qt.WindowStaysOnTopHint)
        self.resize(430, 450)
        self.setMinimumSize(340, 280)
        self.setStyleSheet(STYLE)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 12)
        top = QHBoxLayout()
        top.addWidget(QLabel("NOVA  /  ASSISTANT"))
        top.addStretch()
        settings = QPushButton("⚙")
        settings.setToolTip("Настройки")
        settings.clicked.connect(self.settings_requested)
        back = QPushButton("←")
        back.setToolTip("Назад · Esc")
        back.clicked.connect(self.close)
        top.addWidget(settings)
        top.addWidget(back)
        outer.addLayout(top)
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.document().setMaximumBlockCount(600)
        self.output.setPlainText("На связи. " + HELP)
        outer.addWidget(self.output)
        self.status = QLabel("Локальная модель · команды Windows без ожидания ИИ")
        self.status.setWordWrap(True)
        outer.addWidget(self.status)
        row = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setPlaceholderText("Напиши NOVA…")
        self.input.setMaxLength(4000)
        self.input.returnPressed.connect(lambda: self.submitted.emit(False))
        row.addWidget(self.input)
        self.send = QPushButton("↑")
        self.send.clicked.connect(lambda: self.submitted.emit(False))
        row.addWidget(self.send)
        outer.addLayout(row)
        controls = QHBoxLayout()
        self.mic = QPushButton("Микрофон")
        self.mic.clicked.connect(self.microphone)
        self.plan = QPushButton("План")
        self.plan.setToolTip("Составить план действий для просмотра")
        self.plan.clicked.connect(lambda: self.submitted.emit(True))
        self.stop = QPushButton("Стоп")
        self.stop.clicked.connect(self.cancelled)
        self.stop.setEnabled(False)
        for button in (self.mic, self.plan, self.stop):
            controls.addWidget(button)
        outer.addLayout(controls)

    def set_busy(self, value):
        for button in (self.send, self.plan, self.mic):
            button.setEnabled(not value)
        self.stop.setEnabled(value)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event):
        self.closed.emit()
        event.accept()


class SettingsDialog(QDialog):
    def __init__(self, settings, parent, fetch_models):
        super().__init__(parent)
        self.setWindowTitle("NOVA · настройки")
        self.setStyleSheet(STYLE)
        self.resize(550, 440)
        self.original = settings
        form = QFormLayout(self)
        self.endpoint = QLineEdit(settings.endpoint)
        form.addRow("Ollama (на этом ПК)", self.endpoint)
        row = QHBoxLayout()
        self.model = QComboBox()
        self.model.setEditable(True)
        self.model.addItem(settings.model)
        refresh = QPushButton("Обновить список")
        row.addWidget(self.model)
        row.addWidget(refresh)
        refresh.clicked.connect(lambda: fetch_models(self))
        form.addRow("Модель", row)
        self.warm = QCheckBox("Держать модель в памяти между запросами")
        self.warm.setChecked(settings.keep_warm)
        form.addRow(self.warm)
        self.voice = QCheckBox("Озвучивать ответы")
        self.voice.setChecked(settings.voice)
        form.addRow(self.voice)
        self.voices = QComboBox()
        self.voices.addItem("Голос Windows по умолчанию", "")
        try:
            for ident, name in Voice.voices():
                self.voices.addItem(name, ident)
        except Exception:
            pass
        if settings.voice_id and self.voices.findData(settings.voice_id) < 0:
            self.voices.addItem("Сохранённый голос (проверь доступность)", settings.voice_id)
        self.voices.setCurrentIndex(max(0, self.voices.findData(settings.voice_id)))
        form.addRow("Голос SAPI", self.voices)
        self.rate = QSpinBox()
        self.rate.setRange(-5, 5)
        self.rate.setValue(settings.voice_rate)
        form.addRow("Темп речи", self.rate)
        self.folder = QLineEdit(settings.workspace)
        form.addRow("Папка для файлов и заметок", self.folder)
        row = QHBoxLayout()
        self.speech = QLineEdit(settings.speech_model)
        row.addWidget(self.speech)
        browse = QPushButton("…")
        browse.clicked.connect(self.choose_model)
        row.addWidget(browse)
        form.addRow("Папка модели Vosk", row)
        self.device = QSpinBox()
        self.device.setRange(-1, 100)
        self.device.setValue(settings.microphone_device)
        form.addRow("Микрофон: −1 = системный", self.device)
        self.status = QLabel("Esc / Назад выгружает модель. Смена фокуса сохраняет чат.")
        self.status.setWordWrap(True)
        form.addRow(self.status)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def choose_model(self):
        folder = QFileDialog.getExistingDirectory(self, "Папка распакованной модели Vosk")
        if folder:
            self.speech.setText(folder)

    def save(self):
        try:
            self.value = replace(
                self.original,
                model=self.model.currentText().strip(),
                endpoint=self.endpoint.text().strip(),
                workspace=self.folder.text().strip(),
                voice=self.voice.isChecked(),
                voice_id=self.voices.currentData(),
                voice_rate=self.rate.value(),
                keep_warm=self.warm.isChecked(),
                speech_model=self.speech.text().strip(),
                microphone_device=self.device.value(),
            )
            self.value.validate()
            self.value.save()
            self.accept()
        except Exception as e:
            self.status.setText(str(e))


class Controller(QObject):
    def __init__(self, app, demo=False):
        super().__init__()
        self.app = app
        self.settings = Settings.load()
        self.windows = Windows()
        self.monitor = Monitor()
        self.pet = Pet(self.settings, self.monitor)
        self.chat = Chat()
        self.sig = Signals()
        self.voice = Voice(lambda state: self.sig.voice.emit(state) if not self.disposed.is_set() else None)
        self.seq = 0
        self.jobs = {}
        self.active = None
        self.release = threading.Event()
        self.history = []
        self.stream = ""
        self.shutting = False
        self.pending_plan = None
        self.ai_started = False
        self.disposed = threading.Event()
        self.sig.result.connect(self.result)
        self.sig.error.connect(self.error)
        self.sig.finished.connect(self.finished)
        self.sig.chunk.connect(self.chunk)
        self.sig.voice.connect(self.voice_status)
        self.sig.timer.connect(self.timer)
        self.pet.chat_requested.connect(self.show_chat)
        self.pet.settings_requested.connect(self.settings_dialog)
        self.pet.follow_requested.connect(self.follow)
        self.pet.quit_requested.connect(self.quit)
        self.chat.closed.connect(self.close_chat)
        self.chat.submitted.connect(self.submit)
        self.chat.microphone.connect(self.microphone)
        self.chat.cancelled.connect(self.cancel)
        self.chat.settings_requested.connect(self.settings_dialog)
        self.tray = QSystemTrayIcon(self.icon(), self)
        self.tray.setToolTip("NOVA · локальный помощник")
        menu = QMenu(self.pet)
        self.tray_menu = menu
        menu.addAction("Показать NOVA", self.show_pet)
        menu.addAction("Чат", self.show_chat)
        menu.addAction("Настройки", self.settings_dialog)
        menu.addAction("Справка", self.help)
        menu.addSeparator()
        menu.addAction("Выход", self.quit)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(
            lambda reason: self.show_chat() if reason == QSystemTrayIcon.DoubleClick else None
        )
        self.tray.show()
        self.pet.show()
        screen = app.primaryScreen().availableGeometry()
        x = self.settings.x if self.settings.x >= 0 else screen.right() - 290
        y = self.settings.y if self.settings.y >= 0 else screen.bottom() - 260
        self.pet.move(
            max(screen.left(), min(x, screen.right() - 260)), max(screen.top(), min(y, screen.bottom() - 220))
        )
        if not demo:
            self.monitor.start()
            QTimer.singleShot(1000, lambda: self.follow(self.settings.follow_desktops))

    def icon(self):
        pix = QPixmap(64, 64)
        pix.fill(Qt.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(QColor("#55ff77"))
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(9, 18, 17, 28, 7, 7)
        p.drawRoundedRect(38, 18, 17, 28, 7, 7)
        p.end()
        return QIcon(pix)

    def ollama(self):
        return Ollama(self.settings.endpoint, self.settings.model, self.settings.keep_warm)

    def executor(self):
        return Executor(self.windows, self.settings.workspace, self.sig.timer.emit)

    def show_pet(self):
        self.pet.show()
        self.pet.raise_()

    def show_chat(self):
        self.chat.show()
        self.chat.raise_()
        self.chat.activateWindow()
        self.chat.input.setFocus()
        if self.active is None:
            self.release.clear()

    def follow(self, value):
        if sys.platform != "win32":
            return
        try:
            self.windows.pin(int(self.pet.winId()), value)
            self.settings.follow_desktops = value
            self.settings.save()
            self.pet.update_pin()
        except Exception as e:
            self.tray.showMessage("NOVA · рабочие столы", str(e)[:250])
            logging.warning("Workspace pin unavailable: %s", type(e).__name__)

    def start_job(self, kind, fn, exclusive=True, extra=None, release_client=None):
        self.seq += 1
        ident = self.seq
        cancel = threading.Event()
        if exclusive and self.ai_started and release_client is None and kind != "unload":
            release_client = self.ollama()
        self.jobs[ident] = {"kind": kind, "cancel": cancel, "extra": extra, "exclusive": exclusive}
        if exclusive:
            self.active = ident
            self.chat.set_busy(True)
            self.pet.behavior.busy = kind != "unload"

        def run():
            try:
                result = fn(
                    cancel,
                    lambda text: self.sig.chunk.emit(ident, text) if not self.disposed.is_set() else None,
                )
                if not cancel.is_set() and not self.disposed.is_set():
                    self.sig.result.emit(ident, result)
            except Exception as e:
                logging.warning("Job %s failed: %s", kind, type(e).__name__)
                if not cancel.is_set() and not self.disposed.is_set():
                    self.sig.error.emit(ident, str(e))
            finally:
                if release_client and self.release.is_set():
                    try:
                        release_client.unload()
                    except Exception:
                        if not self.disposed.is_set():
                            self.sig.error.emit(
                                ident, "Не удалось подтвердить выгрузку модели. Проверь ollama ps."
                            )
                if not self.disposed.is_set():
                    self.sig.finished.emit(ident)

        threading.Thread(target=run, daemon=True).start()
        return ident

    def submit(self, plan=False):
        if self.active is not None:
            return
        text = self.chat.input.text().strip()
        if not text:
            return
        self.pending_plan = None
        self.voice.stop()
        self.pet.behavior.speaking = False
        self.release.clear()
        self.stream = ""
        self.chat.input.clear()
        self.chat.output.setPlainText("Ты: " + text + "\n\nNOVA: ")
        self.chat.status.setText("Составляю план…" if plan else "Обрабатываю…")
        client = self.ollama()
        executor = self.executor()
        try:
            action = None if plan else parse(text)
        except ValueError as e:
            self.chat.output.appendPlainText(str(e))
            return
        if plan:
            self.ai_started = True
            self.start_job("plan", lambda c, ch: executor.plan(text, client, c), release_client=client)
        elif action:
            try:
                validate(action.dump())
            except ValueError as e:
                self.chat.output.appendPlainText(str(e))
                return
            self.start_job("action", lambda c, ch: executor.execute(action, c))
        else:
            self.ai_started = True
            self.history.append({"role": "user", "content": text})
            self.history = self.history[-10:]
            messages = list(self.history)
            self.start_job("chat", lambda c, ch: client.chat(messages, c, ch), release_client=client)

    def chunk(self, ident, text):
        job = self.jobs.get(ident)
        if not job or job["cancel"].is_set():
            return
        if job["kind"] == "chat":
            self.stream += text
            self.chat.output.setPlainText(self.stream)
        else:
            self.chat.status.setText(text)

    def result(self, ident, result):
        job = self.jobs.get(ident)
        if not job or job["cancel"].is_set():
            return
        kind = job["kind"]
        if kind == "models":
            dialog = job["extra"]
            try:
                current = dialog.model.currentText()
                dialog.model.clear()
                dialog.model.addItems(result)
                dialog.model.setCurrentText(current)
                dialog.status.setText(f"Найдено моделей: {len(result)}")
            except RuntimeError:
                pass
            return
        if kind == "unload":
            return
        if kind == "microphone":
            self.chat.input.setText(result)
            self.chat.status.setText("Проверь распознанную фразу и нажми ↑.")
            return
        if kind == "plan":
            self.pending_plan = ident
            summary, actions = result
            # Defer until the planning worker has signalled finished; avoid overwriting active job.
            QTimer.singleShot(50, lambda: self.offer_plan(ident, summary, actions))
            return
        message = display(result)
        self.chat.output.setPlainText(message)
        self.chat.status.setText("Ответ получен" if kind == "chat" else "Результат выполнения")
        if kind == "chat":
            self.history.append({"role": "assistant", "content": message})
        self.pet.behavior.emotion("curious", 2)
        if self.settings.voice and self.chat.isVisible():
            self.voice.speak(message, self.settings)

    def offer_plan(self, ident, summary, actions):
        if self.pending_plan != ident or not self.chat.isVisible() or self.release.is_set():
            return
        if self.active is not None:
            QTimer.singleShot(50, lambda: self.offer_plan(ident, summary, actions))
            return
        box = QMessageBox(self.chat)
        box.setWindowTitle("NOVA · проверить план")
        box.setTextFormat(Qt.PlainText)
        box.setText(summary)
        box.setInformativeText(
            "\n".join(f"{i}. {a.tool}: {display(a.args)}" for i, a in enumerate(actions, 1))
        )
        box.setStandardButtons(QMessageBox.Ok | QMessageBox.Cancel)
        box.setDefaultButton(QMessageBox.Cancel)
        if box.exec() != QMessageBox.Ok:
            return
        if self.pending_plan != ident or self.release.is_set() or self.active is not None:
            return
        self.pending_plan = None
        executor = self.executor()
        self.start_job("action", lambda c, ch: executor.execute_plan(actions, c, ch))

    def error(self, ident, text):
        job = self.jobs.get(ident)
        if not job:
            return
        if job["kind"] == "models":
            try:
                job["extra"].status.setText(text)
            except RuntimeError:
                pass
        elif not job["cancel"].is_set():
            self.chat.output.setPlainText(text)
            self.chat.status.setText("Не выполнено")
            self.pet.behavior.emotion("angry", 1.5)

    def finished(self, ident):
        job = self.jobs.pop(ident, None)
        if self.active == ident:
            self.active = None
            self.chat.set_busy(False)
            self.pet.behavior.busy = False
        if job and job["kind"] == "unload":
            self.ai_started = False
        if self.shutting and not self.jobs:
            self.app.quit()

    def voice_status(self, state):
        self.pet.behavior.speaking = state == "speaking" and self.chat.isVisible()
        if state not in ("speaking", "idle"):
            self.chat.status.setText(state)

    def cancel(self):
        self.pending_plan = None
        self.voice.stop()
        self.pet.behavior.speaking = False
        if self.active in self.jobs:
            self.jobs[self.active]["cancel"].set()
            self.chat.status.setText("Отмена… завершаю текущий запрос.")

    def close_chat(self):
        self.release.set()
        self.cancel()
        self.history = []
        self.pet.behavior.busy = False
        # If inference is running it releases its own model after the stream closes.
        if self.active is None and self.ai_started:
            client = self.ollama()
            self.start_job("unload", lambda c, ch: client.unload(), release_client=None)

    def microphone(self):
        if self.active is not None:
            return
        self.voice.stop()
        self.pet.behavior.speaking = False
        settings = replace(self.settings)
        self.start_job("microphone", lambda c, ch: recognize(settings, c, ch))

    def settings_dialog(self):
        if self.active is not None:
            self.chat.status.setText("Сначала дождись завершения или нажми Стоп.")
            self.show_chat()
            return

        def fetch(dialog):
            try:
                client = Ollama(dialog.endpoint.text(), dialog.model.currentText())
            except Exception as e:
                dialog.status.setText(str(e))
                return
            self.start_job("models", lambda c, ch: client.models(), exclusive=False, extra=dialog)

        dialog = SettingsDialog(self.settings, self.chat, fetch)
        if dialog.exec() == QDialog.Accepted:
            old = self.ollama()
            self.settings = dialog.value
            self.pet.settings = self.settings
            self.history = []
            if self.ai_started:
                self.start_job("unload", lambda c, ch: old.unload())

    def timer(self, minutes):
        timer = QTimer(self)
        timer.setSingleShot(True)

        def ring():
            self.pet.behavior.emotion("surprise", 5)
            self.tray.showMessage("NOVA", f"Таймер {minutes} мин. завершён.")
            QApplication.beep()
            timer.deleteLater()

        timer.timeout.connect(ring)
        timer.start(minutes * 60 * 1000)

    def help(self):
        self.show_chat()
        self.chat.output.setPlainText(HELP + "\n\nФайлы: " + self.settings.workspace)

    def quit(self):
        if self.shutting:
            return
        self.shutting = True
        self.monitor.stop()
        self.voice.stop()
        self.pet.hide()
        self.chat.hide()
        self.tray.hide()
        self.release.set()
        for job in self.jobs.values():
            job["cancel"].set()
        if self.active is None and self.ai_started:
            client = self.ollama()
            self.start_job("unload", lambda c, ch: client.unload())
        if not self.jobs:
            self.app.quit()
            return
        QTimer.singleShot(23000, self.app.quit)  # Bounded shutdown if a local service is unavailable.


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--demo", action="store_true", help="UI preview without Windows integration")
    parser.add_argument(
        "--smoke-test", action="store_true", help="render UI then exit; no desktop/model actions"
    )
    parser.add_argument("--screenshot", help="PNG path with --smoke-test only")
    args = parser.parse_args()
    if sys.platform != "win32" and not (args.demo or args.smoke_test):
        parser.error("NOVA работает на Windows 11; для макета используй --demo.")
    root = data_dir()
    root.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(root / "nova.log", maxBytes=300000, backupCount=2, encoding="utf-8")
    logging.basicConfig(level=logging.WARNING, handlers=[handler])
    app = QApplication(sys.argv[:1])
    app.setApplicationName("NOVA")
    app.setQuitOnLastWindowClosed(False)
    lock = QLockFile(str(root / "instance.lock"))
    lock.setStaleLockTime(0)
    if not lock.tryLock(100):
        QMessageBox.information(None, "NOVA", "NOVA уже запущена. Найди зелёные глаза в системном трее.")
        return 0
    controller = Controller(app, args.demo or args.smoke_test)
    if args.smoke_test:

        def finish():
            if args.screenshot:
                controller.pet.grab().save(args.screenshot)
            app.quit()

        QTimer.singleShot(500, finish)
    result = app.exec()
    controller.disposed.set()
    controller.monitor.stop()
    controller.voice.stop()
    controller.pet.timer.stop()
    controller.tray.hide()
    controller.pet.deleteLater()
    controller.chat.deleteLater()
    controller.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    lock.unlock()
    return result


if __name__ == "__main__":
    raise SystemExit(main())
