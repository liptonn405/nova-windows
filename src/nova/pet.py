"""Transparent Qt pet: procedural eyes/headphones share a single animated transform."""

import math
import time
from PySide6.QtCore import Qt, QTimer, QRectF, Signal
from PySide6.QtGui import QPainter, QColor, QPen, QCursor, QFont, QPainterPath
from PySide6.QtWidgets import QWidget, QToolButton, QMenu
from .behavior import Behavior

GREEN = QColor("#55ff77")


class Pet(QWidget):
    chat_requested = Signal()
    settings_requested = Signal()
    follow_requested = Signal(bool)
    quit_requested = Signal()

    def __init__(self, settings, monitor):
        super().__init__()
        self.settings = settings
        self.monitor = monitor
        self.behavior = Behavior()
        self.setWindowTitle("NOVA")
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.resize(260, 220)
        self.setMouseTracking(True)
        self.locked = False
        self.drag_start = None
        self.origin = None
        self.dragged = False
        self._last = time.monotonic()
        self._saved = 0
        self.next_click = 0
        self.chat_button = self.button("···", 18, "Открыть чат", self.chat_requested.emit)
        self.pin_button = self.button(
            "◇", 52, "Закрепить на текущем рабочем столе / следовать", self.toggle_follow
        )
        self.menu_button = self.button("≡", 86, "Меню", self.menu)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.frame)
        self.timer.start(16)
        self.update_pin()

    def button(self, text, x, tip, fn):
        b = QToolButton(self)
        b.setText(text)
        b.setGeometry(x, 12, 28, 26)
        b.setToolTip(tip)
        b.clicked.connect(fn)
        b.setStyleSheet(
            "QToolButton{color:#7acc8d;background:rgba(7,18,11,180);border:1px solid #24452e;border-radius:10px;font-size:16px;} QToolButton:hover{background:#183d23;}"
        )
        return b

    def update_pin(self):
        self.pin_button.setText("◇" if self.settings.follow_desktops else "◆")

    def toggle_follow(self):
        self.follow_requested.emit(not self.settings.follow_desktops)

    def menu(self):
        menu = QMenu(self)
        menu.setStyleSheet("QMenu{background:#08100b;color:#b8e4c1;}")
        menu.addAction("Чат", self.chat_requested.emit)
        menu.addAction("Настройки", self.settings_requested.emit)
        action = menu.addAction("Зафиксировать положение")
        action.setCheckable(True)
        action.setChecked(self.locked)
        action.toggled.connect(lambda value: setattr(self, "locked", value))
        menu.addAction("Сюрприз", lambda: self.behavior.emotion("surprise", 3))
        menu.addSeparator()
        menu.addAction("Закрыть NOVA", self.quit_requested.emit)
        menu.exec(QCursor.pos())

    def frame(self):
        now = time.monotonic()
        dt = now - self._last
        self._last = now
        local = self.mapFromGlobal(QCursor.pos())
        self.behavior.low_battery = (
            self.monitor.battery is not None and self.monitor.battery < 20 and not self.monitor.plugged
        )
        self.behavior.music = self.monitor.playing
        self.behavior.update(dt, ((local.x() - 130) / 350, (local.y() - 120) / 300), self.monitor.energy)
        interval = (
            100
            if self.behavior.mood == "sleep" and not self.behavior.busy and not self.behavior.speaking
            else 16
        )
        if self.timer.interval() != interval:
            self.timer.setInterval(interval)
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        b = self.behavior
        p.setFont(QFont("Segoe UI", 8))
        p.setPen(QColor("#80ae8c"))
        p.drawText(20, 205, "NOVA  /  " + ("думаю…" if b.busy else "говорю" if b.speaking else "на связи"))
        # Compact battery lives outside the moving face, in a reserved toolbar row.
        if self.monitor.battery is not None:
            p.setPen(QPen(QColor("#55d775"), 1))
            p.setBrush(QColor("#061209"))
            p.drawRoundedRect(QRectF(214, 20, 27, 12), 3, 3)
            p.fillRect(QRectF(242, 24, 2, 4), GREEN)
            p.fillRect(QRectF(217, 23, 21 * self.monitor.battery / 100, 6), GREEN)
            if self.monitor.plugged:
                p.drawText(201, 30, "+")
        h1, h2, tilt, scale, shake = b.eyes()
        p.save()
        p.translate(130 + b.look_x * 23 + shake, 118 + b.look_y * 15)
        p.scale(scale, scale)
        for x, h, angle in [(-44, h1, tilt), (44, h2, -tilt)]:
            p.save()
            p.translate(x, 0)
            p.rotate(angle)
            rect = QRectF(-21, -28 * h, 42, 56 * h)
            # Layered translucent strokes form a glow, not a rectangular bitmap background.
            for width, alpha in [(width, 3) for width in range(32, 0, -2)]:
                p.setPen(QPen(QColor(60, 255, 105, alpha), width))
                p.setBrush(Qt.NoBrush)
                p.drawRoundedRect(rect, 17, 17)
            p.setPen(Qt.NoPen)
            p.setBrush(GREEN)
            p.drawRoundedRect(rect, 16, 16)
            p.restore()
        if b.music:
            path = QPainterPath()
            path.moveTo(-78, 2)
            path.cubicTo(-81, -70, 81, -70, 78, 2)
            for width, alpha in [(12, 12), (7, 25), (2, 200)]:
                p.setPen(QPen(QColor(85, 255, 119, alpha), width))
                p.setBrush(Qt.NoBrush)
                p.drawPath(path)
            for x in (-81, 73):
                rect = QRectF(x, -12, 9, 35)
                p.setPen(QPen(QColor("#235f30"), 5))
                p.setBrush(GREEN)
                p.drawRoundedRect(rect, 4, 4)
        if b.busy:
            for i in range(3):
                alpha = 70 + int(180 * (0.5 + 0.5 * math.sin(b.now * 5 - i)))
                p.setBrush(QColor(85, 255, 119, alpha))
                p.setPen(Qt.NoPen)
                p.drawEllipse(QRectF(-15 + i * 13, 49, 4, 4))
        if b.mood == "sleep":
            p.setPen(GREEN)
            p.setFont(QFont("Segoe UI", 12))
            p.drawText(35, -38 - int(math.sin(b.now) * 3), "z z")
        p.restore()
        p.end()

    def mousePressEvent(self, event):
        if event.button() == Qt.RightButton:
            self.menu()
            return
        if event.button() == Qt.LeftButton:
            self.drag_start = event.globalPosition().toPoint()
            self.origin = self.pos()
            self.dragged = False

    def mouseMoveEvent(self, event):
        if self.drag_start is None:
            return
        delta = event.globalPosition().toPoint() - self.drag_start
        if delta.manhattanLength() > 7:
            self.dragged = True
        if self.dragged and not self.locked:
            self.move(self.origin + delta)

    def mouseReleaseEvent(self, event):
        if self.drag_start is None:
            return
        if not self.dragged:
            self.chat_requested.emit()
        else:
            self.settings.x = self.x()
            self.settings.y = self.y()
            self.settings.save()
        self.drag_start = None
