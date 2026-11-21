import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import threading
import time
import pytest
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt, QCoreApplication, QEvent
from PySide6.QtTest import QTest
from nova.config import Settings
from nova.monitor import Monitor
from nova.pet import Pet
from nova.app import Chat, Controller


@pytest.fixture(scope="module")
def app():
    instance = QApplication.instance() or QApplication([])
    yield instance
    for widget in instance.topLevelWidgets():
        widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def wait(app, condition, seconds=2):
    until = time.monotonic() + seconds
    while time.monotonic() < until:
        app.processEvents()
        if condition():
            return
        time.sleep(0.01)
    assert condition()


def test_pet_toolbar_does_not_overlap_face(app, tmp_path):
    pet = Pet(Settings(workspace=str(tmp_path)), Monitor())
    pet.show()
    app.processEvents()
    assert pet.chat_button.geometry().bottom() < 60
    assert pet.pin_button.geometry().bottom() < 60
    assert not pet.grab().isNull()
    pet.timer.stop()
    pet.close()


def test_chat_stays_on_focus_loss_and_esc_closes(app):
    chat = Chat()
    closed = []
    chat.closed.connect(lambda: closed.append(True))
    chat.show()
    other = Chat()
    other.show()
    other.activateWindow()
    app.processEvents()
    assert chat.isVisible() and not closed
    QTest.keyClick(chat, Qt.Key_Escape)
    assert not chat.isVisible() and closed
    other.close()


def test_closed_chat_cancels_request_and_unloads(app, tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    controller = Controller(app, demo=True)
    controller.settings.voice = False
    controller.show_chat()
    entered = threading.Event()
    unloaded = threading.Event()

    class Fake:
        def chat(self, messages, cancel, ch):
            entered.set()
            while not cancel.wait(0.01):
                pass
            return "late result"

        def unload(self):
            unloaded.set()

    monkeypatch.setattr(controller, "ollama", lambda: Fake())
    controller.chat.input.setText("привет")
    controller.submit()
    wait(app, entered.is_set)
    controller.chat.close()
    wait(app, lambda: unloaded.is_set() and controller.active is None)
    assert not controller.pet.behavior.busy
    assert "late result" not in controller.chat.output.toPlainText()
    controller.pet.timer.stop()
    controller.pet.close()
    controller.tray.hide()
