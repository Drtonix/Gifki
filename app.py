"""Gifki: сбор кандидатов, разбор по каналам и меткам, нарезка из видео."""
import bisect
import contextlib
import hashlib
import html
import os
import queue
import re
import sys
import threading
import time
import traceback
import urllib.parse
import urllib.request
from pathlib import Path

from PySide6.QtCore import (QEvent, QObject, QPoint, QPointF, QRectF, QSettings, QStandardPaths, Qt, QThread,
                            QTimer, QUrl, Signal)
from PySide6.QtGui import (QAction, QActionGroup, QColor, QDesktopServices, QFont, QIcon, QImage, QMovie,
                           QPainter, QPainterPath, QPen)
from PySide6.QtMultimedia import QMediaPlayer, QVideoSink
from PySide6.QtWidgets import (QApplication, QCheckBox, QDialog, QFileDialog, QFrame, QGridLayout,
                               QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QMenu, QMenuBar,
                               QMessageBox, QPushButton, QScrollArea, QSizePolicy,
                               QStackedWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
                               QWidget)

import actions
import i18n
import media
import relay
import sources
import _style
from _style import STYLE
from actions import BY_NAME, CHANNELS, GROUPS, LABELS, UNIVERSAL
from i18n import t, tf
from store import DATA, Store

APP = "Gifki"
AUTHOR = "DrTonix"
SITE = "bdub.space"
URL = "https://bdub.space"
ACCENT = "#ee86b0"
MAC = sys.platform == "darwin"
WINDOWS = sys.platform == "win32"
UNDO = "⌘Z" if MAC else "Ctrl+Z"
FINDER = "Показать в Finder" if MAC else "Показать в проводнике"
MEDIA_EXT = {".gif", ".mp4", ".webm", ".mov", ".m4v", ".mkv", ".avi"}

# Клавиши по физическому месту, а не по символу: на русской раскладке и с
# Shift символы другие, а палец помнит место. macOS отдаёт код клавиши,
# Windows — скан-код. Цифровой блок на Windows не берём: с выключенным NumLock
# его скан-коды совпадают со стрелками.
if MAC:
    _PLACES = {18: "1", 19: "2", 20: "3", 21: "4", 23: "5", 22: "6", 26: "7",
               83: "1", 84: "2", 85: "3", 86: "4", 87: "5", 88: "6", 89: "7",
               7: "x", 8: "c", 6: "z", 34: "i", 31: "o", 35: "p"}
else:
    _PLACES = {0x02: "1", 0x03: "2", 0x04: "3", 0x05: "4", 0x06: "5", 0x07: "6", 0x08: "7",
               0x2D: "x", 0x2E: "c", 0x2C: "z", 0x17: "i", 0x18: "o", 0x19: "p"}


def place(e) -> str:
    """Клавиша по месту на клавиатуре: «1»…«7», «x», «c», «z», «i», «o» или ""."""
    return _PLACES.get(e.nativeVirtualKey() if MAC else e.nativeScanCode(), "")


def digit(e):
    k = place(e)
    return int(k) - 1 if k.isdigit() else None


def default_out() -> Path:
    pictures = QStandardPaths.writableLocation(QStandardPaths.PicturesLocation)
    base = Path(pictures or Path.home() / "Pictures")
    # Уже собранная подборка остаётся на месте при любом языке.
    if (base / "Гифки действий").exists() or i18n.current() == "ru":
        return base / "Гифки действий"
    return base / "Action GIFs"

THEMES = ("system", "light", "dark")


def theme():
    name = QSettings("local", i18n.SETTINGS).value("theme", "system")
    return name if name in THEMES else "system"


def skin():
    name = theme()
    if name != "system":
        return name
    from PySide6.QtGui import QGuiApplication
    return "dark" if QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark else "light"


def themed(css):
    return _style.light(css) if skin() == "light" else css


def tone(hex_):
    return QColor(_style.light_hex(hex_) if skin() == "light" else hex_)


def ink(alpha):
    """Полупрозрачная заливка: белая на тёмном, чёрная на светлом."""
    return QColor(0, 0, 0, int(alpha * 0.8)) if skin() == "light" else QColor(255, 255, 255, alpha)


EXTRA = """
QLineEdit {
    background: rgba(255,255,255,0.07);
    border: none; border-radius: 10px;
    padding: 7px 11px; color: #e9ebef; font-size: 13px;
}
QLineEdit:focus { background: rgba(255,255,255,0.10); }
QFrame#panel { background: #232327; border: none; border-radius: 14px; }
QScrollArea#bare, QWidget#bare { background: transparent; border: none; }
QLabel#dim  { color: #8a8f98; font-size: 12px; }
QLabel#meta { color: #75797f; font-size: 12px; }
QLabel#empty { color: #6b6f76; font-size: 16px; }
QLabel#cap  { color: #8a8f98; font-size: 12px; padding-left: 2px; }
QLabel#title { color: #f4f5f7; font-size: 20px; font-weight: 600; }
QLabel#saved { color: #ee86b0; font-size: 13px; }
QPushButton#field {
    background: rgba(255,255,255,0.07);
    border: none; border-radius: 10px;
    padding: 0 12px; min-height: 30px;
    color: #e9ebef; font-size: 13px; text-align: left;
}
QPushButton#field:hover    { background: rgba(255,255,255,0.10); }
QPushButton#field:disabled { color: rgba(233,235,239,0.35); }
QPushButton#key, QPushButton#keyBig {
    background: rgba(255,255,255,0.07);
    border: 1.5px solid transparent;
    border-radius: 10px;
    color: #e9ebef;
}
QPushButton#key    { min-height: 34px; padding: 0 30px 0 16px; font-size: 13px; }
QPushButton#keyBig { min-height: 46px; padding: 0 24px; font-size: 16px; font-weight: 600; }
QPushButton#key:hover, QPushButton#keyBig:hover { background: rgba(255,255,255,0.11); }
QPushButton#key:disabled, QPushButton#keyBig:disabled { color: #5c5f65; background: rgba(255,255,255,0.04); }
QPushButton#keyBig[suggested="true"] { border: 1.5px solid #ee86b0; }
QPushButton#keyBig:checked { background: #ee86b0; color: #1e1e20; }
QMenu {
    background: #2c2c31;
    border: 1px solid rgba(255,255,255,0.10);
    border-radius: 9px;
    padding: 4px;
}
QMenu::item { padding: 6px 22px 6px 11px; border-radius: 6px; color: #e9ebef; font-size: 13px; }
QMenu::item:selected { background: #ee86b0; color: #1e1e20; }
QMenu::item:disabled { color: #5c5f65; }
QMenu::separator { height: 1px; background: rgba(255,255,255,0.08); margin: 4px 8px; }
QTreeWidget {
    background: #1a1a1d; border: none; border-radius: 12px;
    padding: 6px; color: #c3c8d0; font-size: 13px;
}
QTreeWidget::item { padding: 5px 2px; border-radius: 6px; }
QTreeWidget::item:hover    { background: rgba(255,255,255,0.05); }
QTreeWidget::item:selected { background: rgba(238,134,176,0.28); color: #ffffff; }
QTreeWidget::branch { background: transparent; }
QListWidget#results {
    background: #1a1a1d; border: none; border-radius: 12px;
    padding: 6px; color: #c3c8d0; font-size: 13px;
}
QListWidget#results::item { padding: 8px 10px; border-radius: 8px; }
QListWidget#results::item:hover    { background: rgba(255,255,255,0.06); }
QListWidget#results::item:selected { background: rgba(238,134,176,0.28); color: #ffffff; }
QScrollBar:vertical { background: transparent; width: 10px; margin: 4px 2px; }
QScrollBar::handle:vertical {
    background: rgba(255,255,255,0.13);
    border-radius: 4px;
    min-height: 36px;
}
QScrollBar::handle:vertical:hover { background: rgba(255,255,255,0.20); }
QScrollBar::add-line, QScrollBar::sub-line { height: 0px; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
QHeaderView { background: #1a1a1d; border: none; }
QHeaderView::section {
    background: transparent; border: none; color: #8a8f98;
    font-size: 12px; padding: 4px 2px 8px 2px;
}
"""

# Helvetica Neue на Windows нет, Arial там выглядит чужим: системный Segoe UI.
# Строка меню на Windows живёт в окне — тёмная, как оно.
WIN_EXTRA = """
QWidget { font-family: "Segoe UI", Arial, sans-serif; }
QMenuBar { background: #1e1e20; color: #a9adb5; padding: 2px 16px; }
QMenuBar::item { background: transparent; padding: 4px 10px; border-radius: 6px; }
QMenuBar::item:selected { background: rgba(255,255,255,0.08); color: #e9ebef; }
"""


def open_link(url):
    """Ссылки из чужих страниц открываются, только если это веб-адрес:
    file:///…/что-то.app по щелчку запустил бы программу."""
    url = QUrl(url) if isinstance(url, str) else url
    if url.scheme().lower() in ("http", "https", "mailto"):
        QDesktopServices.openUrl(url)


def app_icon():
    here = Path(__file__).resolve().parent
    name = "AppIcon.icns" if MAC else "AppIcon.ico"
    for p in (here.parent / name, here / "icon" / name):
        if p.exists():
            return QIcon(str(p))
    return QIcon()


def menu(parent) -> QMenu:
    m = QMenu(parent)
    # Иначе за скруглением остаётся квадратный угол системной подложки.
    m.setAttribute(Qt.WA_TranslucentBackground)
    m.setWindowFlags(m.windowFlags() | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
    return m


def repolish(w):
    w.style().unpolish(w)
    w.style().polish(w)
    w.update()


def clock(ms: float) -> str:
    s = max(ms, 0) / 1000
    m, s = divmod(s, 60)
    h, m = divmod(int(m), 60)
    return f"{h}:{m:02d}:{s:04.1f}" if h else f"{m:02d}:{s:04.1f}"


def seconds(s: float) -> str:
    text = f"{s:.1f} " + t("с")
    return text.replace(".", ",") if i18n.current() == "ru" else text


class Bar(QWidget):
    """Полоса хода работы: тонкая, акцентом, без процентов."""

    def __init__(self):
        super().__init__()
        self.setFixedHeight(6)
        self.value = 0.0

    def set(self, v: float):
        self.value = max(0.0, min(1.0, v))
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(ink(15))
        p.drawRoundedRect(QRectF(self.rect()), 3, 3)
        if self.value > 0:
            p.setBrush(QColor(ACCENT))
            p.drawRoundedRect(QRectF(0, 0, self.width() * self.value, self.height()), 3, 3)


class ElideLabel(QLabel):
    """Длинное имя файла — с многоточием в середине, а не тянет за собой окно."""

    def __init__(self):
        super().__init__()
        self.full = ""
        self.setMinimumWidth(40)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)

    def set(self, text):
        self.full = text
        self._fit()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._fit()

    def _fit(self):
        super().setText(self.fontMetrics().elidedText(self.full, Qt.ElideMiddle, max(self.width(), 10)))


class KeyButton(QPushButton):
    """Кнопка с клавишей в углу: здесь работают клавишами, мышь — запасной путь."""

    def __init__(self, text, key="", big=False):
        super().__init__(text)
        self.key = key
        self.setObjectName("keyBig" if big else "key")
        self.setFocusPolicy(Qt.NoFocus)
        self.setCursor(Qt.PointingHandCursor)

    def paintEvent(self, e):
        super().paintEvent(e)
        if not self.key:
            return
        p = QPainter(self)
        f = QFont(self.font())
        f.setPixelSize(10)
        f.setWeight(QFont.Normal)
        p.setFont(f)
        on = self.isChecked() and self.objectName() == "keyBig"
        p.setPen(QColor(30, 30, 32, 150) if on else tone("#6b6f76"))
        r = self.rect().adjusted(0, 0, -8, -5)
        p.drawText(r, Qt.AlignRight | Qt.AlignBottom, self.key)


class VideoView(QWidget):
    """Видео рисуется само из QVideoSink.

    Системный видеовиджет — отдельный слой: поверх него не нарисовать рамку
    кадрирования, и снимок окна без экрана видит на его месте пустоту.
    """
    cropChanged = Signal()
    sized = Signal(int, int)

    def __init__(self, cropping=False):
        super().__init__()
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumSize(320, 220)
        self.player = QMediaPlayer(self)
        self.sink = QVideoSink(self)
        self.player.setVideoSink(self.sink)
        self.sink.videoFrameChanged.connect(self._frame)
        self.image = QImage()
        self.cropping = cropping
        self.crop = QRectF()
        self._from = None
        self.text = ""
        self.overlay = None       # готовая гифка поверх видео, в натуральную величину
        self.overlay_text = ""

    def show_gif(self, path, text):
        self.hide_gif()
        movie = QMovie(str(path))
        movie.frameChanged.connect(lambda _: self.update())
        movie.start()
        self.overlay, self.overlay_text = movie, text
        self.update()

    def hide_gif(self):
        if self.overlay is not None:
            self.overlay.stop()
            self.overlay.deleteLater()
            self.overlay = None
            self.update()

    def _frame(self, frame):
        img = frame.toImage()
        if not img.isNull():
            first = self.image.isNull()
            self.image = img
            if first:
                self.sized.emit(img.width(), img.height())
            self.update()

    def load(self, path, loop=True, play=True):
        self.image = QImage()
        self.crop = QRectF()
        src = str(path)
        self.player.setSource(QUrl(src) if src.startswith(("http://", "https://"))
                              else QUrl.fromLocalFile(src))
        self.player.setLoops(QMediaPlayer.Loops.Infinite if loop else 1)
        if play:
            self.player.play()
        else:
            self.player.pause()
        self.update()

    def clear(self, text=""):
        self.player.stop()
        self.player.setSource(QUrl())
        self.image = QImage()
        self.text = text
        self.update()

    def target(self) -> QRectF:
        if self.image.isNull():
            return QRectF()
        area = QRectF(self.rect()).adjusted(12, 12, -12, -12)
        w, h = self.image.width(), self.image.height()
        k = min(area.width() / w, area.height() / h)
        tw, th = w * k, h * k
        return QRectF(area.center().x() - tw / 2, area.center().y() - th / 2, tw, th)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), 14, 14)
        p.fillPath(path, tone("#1a1a1d"))
        if self.image.isNull():
            if self.text:
                p.setPen(tone("#6b6f76"))
                f = QFont(self.font())
                f.setPixelSize(16)
                p.setFont(f)
                p.drawText(self.rect(), Qt.AlignCenter, self.text)
            return
        t = self.target()
        p.drawImage(t, self.image)
        if self.cropping and not self.crop.isEmpty():
            c = QRectF(t.x() + self.crop.x() * t.width(), t.y() + self.crop.y() * t.height(),
                       self.crop.width() * t.width(), self.crop.height() * t.height())
            shade = QPainterPath()
            shade.addRect(t)
            inner = QPainterPath()
            inner.addRect(c)
            p.fillPath(shade.subtracted(inner), QColor(0, 0, 0, 140))
            pen = QPen(QColor(ACCENT))
            pen.setWidthF(1.5)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawRect(c)
        if self.overlay is not None:
            self._paint_gif(p, path)

    def _paint_gif(self, p, path):
        p.fillPath(path, QColor(0, 0, 0, 190))
        frame = self.overlay.currentImage()
        if frame.isNull():
            return
        # Пиксель гифки — точка экрана, как её покажет Discord; не влезает — уменьшаем.
        room = QRectF(self.rect()).adjusted(20, 20, -20, -52)
        w, h = frame.width(), frame.height()
        k = min(1.0, room.width() / w, room.height() / h)
        box = QRectF(room.center().x() - w * k / 2, room.center().y() - h * k / 2, w * k, h * k)
        p.drawImage(box, frame)
        p.setPen(tone("#e9ebef"))
        f = QFont(self.font())
        f.setPixelSize(13)
        p.setFont(f)
        p.drawText(QRectF(0, box.bottom() + 10, self.width(), 24), Qt.AlignHCenter | Qt.AlignTop,
                   self.overlay_text)

    def _norm(self, pos) -> QPointF:
        t = self.target()
        return QPointF(min(max((pos.x() - t.x()) / t.width(), 0), 1),
                       min(max((pos.y() - t.y()) / t.height(), 0), 1))

    def mousePressEvent(self, e):
        if self.overlay is not None:
            self.hide_gif()
            return
        if self.cropping and not self.image.isNull() and self.target().contains(e.position()):
            self._from = self._norm(e.position())

    def mouseMoveEvent(self, e):
        if self._from is not None:
            self.crop = QRectF(self._from, self._norm(e.position())).normalized()
            self.update()

    def mouseReleaseEvent(self, e):
        if self._from is not None:
            self._from = None
            if self.crop.width() < 0.04 or self.crop.height() < 0.04:
                self.crop = QRectF()
            self.update()
            self.cropChanged.emit()

    def mouseDoubleClickEvent(self, e):
        if self.cropping:
            self.crop = QRectF()
            self.update()
            self.cropChanged.emit()


class Frames(QObject):
    """Кадры для ленты нарезки. ffmpeg по запросу, в три потока: у потокового
    видео каждый кадр — отдельный запрос к серверу. Новый запрос вытесняет
    старый — при масштабировании нужны кадры того места, где лента сейчас."""
    ready = Signal(str, int, QImage)

    def __init__(self, workers=3):
        super().__init__()
        self.cond = threading.Condition()
        self.want = []
        self.alive = True
        self.workers = workers
        self.remote_gate = threading.Lock()

    def start(self):
        for _ in range(self.workers):
            threading.Thread(target=self._work, daemon=True).start()

    def ask(self, src, times, height, fetch=None, headers=None, remote=False):
        with self.cond:
            self.want = [(src, t, height, fetch or src, headers or {}, remote) for t in times]
            self.cond.notify_all()

    def _work(self):
        while True:
            with self.cond:
                while self.alive and not self.want:
                    self.cond.wait()
                if not self.alive:
                    return
                src, t, h, fetch, headers, remote = self.want.pop(0)
            # Поток с сервера — по одному кадру: параллельные запросы сервер всё равно
            # отдаёт по очереди, а канал нужен нарезке.
            gate = self.remote_gate if remote else contextlib.nullcontext()
            with gate:
                data = media.frame_png(fetch, t / 1000, h, headers)
            if data:
                self.ready.emit(src, t, QImage.fromData(data, "PNG"))

    def stop(self):
        with self.cond:
            self.alive = False
            self.cond.notify_all()


class TrimBar(QWidget):
    """Лента кадров с рамкой отрезка, как в «Фото» на iPhone.

    Края рамки тянутся — это начало и конец, видео при этом показывает кадр под
    краем. Щелчок или протяжка по ленте — перемотка. Колесо и щипок — масштаб
    вокруг курсора, горизонтальная прокрутка — сдвиг; снизу полоса всей записи.
    """
    seek = Signal(int)
    changed = Signal()
    STRIP = 52
    GRIP = 14
    MIN_SPAN = 2000

    def __init__(self, frames: Frames):
        super().__init__()
        self.setFixedHeight(self.STRIP + 18)
        self.setMouseTracking(True)
        self.frames = frames
        frames.ready.connect(self._thumb)
        self.src = None
        self.duration = 0
        self.at = 0
        self.a = None
        self.b = None
        self.v0 = 0
        self.v1 = 0
        self.aspect = 16 / 9
        self.thumbs = {}
        self.fetch = (None, {}, False)
        self.drag = None
        self.press_x = 0
        self.span0 = (0, 0)
        self.moved = False
        self.setToolTip(t("Края рамки — начало и конец; рамку можно тащить целиком. Щелчок — перемотка."
                          " Колесо или щипок — масштаб, прокрутка вбок — сдвиг"))

    def set_source(self, src, duration, aspect, fetch=None, headers=None, remote=False):
        self.src = str(src)
        self.fetch = (str(fetch or src), headers or {}, remote)
        self.duration = int(duration)
        self.aspect = aspect if aspect and aspect > 0 else 16 / 9
        self.thumbs = {}
        # Длинную запись сначала показываем минутой: в серии на 24 минуты
        # отрезок в две секунды на полной ленте не ухватить.
        self.v0, self.v1 = 0, min(self.duration, 60000) or 1
        if remote:
            # Сначала первый кадр плееру, потом лента: канал у них один.
            QTimer.singleShot(1500, self._request)
        else:
            self._request()
        self.update()

    def strip(self) -> QRectF:
        return QRectF(self.GRIP, 2, max(self.width() - 2 * self.GRIP, 1), self.STRIP)

    def x_of(self, ms) -> float:
        r = self.strip()
        return r.left() + (ms - self.v0) / max(self.v1 - self.v0, 1) * r.width()

    def ms_of(self, x) -> int:
        r = self.strip()
        k = (x - r.left()) / r.width()
        return int(min(max(self.v0 + k * (self.v1 - self.v0), 0), self.duration))

    def _tiles(self):
        r = self.strip()
        w = self.STRIP * self.aspect
        n = max(1, int(r.width() // w) + 1)
        span = self.v1 - self.v0
        return [(r.left() + i * w, int(round(self.v0 + (i + 0.5) * w / r.width() * span, -2)))
                for i in range(n)], w

    def _request(self):
        if not self.src or not self.duration:
            return
        tiles, _ = self._tiles()
        missing = [t for _, t in tiles if t not in self.thumbs and t <= self.duration]
        self.frames.ask(self.src, missing, self.STRIP * 2, *self.fetch)

    def _thumb(self, src, t, img):
        if src == self.src and not img.isNull():
            self.thumbs[t] = img
            self.update()

    def set_view(self, v0, v1):
        span = min(max(v1 - v0, min(self.MIN_SPAN, self.duration)), self.duration)
        v0 = min(max(v0, 0), self.duration - span)
        self.v0, self.v1 = int(v0), int(v0 + span)
        self._request()
        self.update()

    def follow(self, ms):
        """Бегунок ушёл за край ленты — лента едет за ним."""
        if ms < self.v0 or ms > self.v1:
            span = self.v1 - self.v0
            self.set_view(ms - span * 0.2, ms + span * 0.8)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        r = self.strip()
        clip = QPainterPath()
        clip.addRoundedRect(r, 8, 8)
        p.fillPath(clip, tone("#1a1a1d"))
        if not self.duration:
            return
        p.save()
        p.setClipPath(clip)
        tiles, w = self._tiles()
        keys = sorted(self.thumbs)
        for x, at in tiles:
            img = self.thumbs.get(at)
            if img is None and keys:
                # Пока нужный кадр не готов — ближайший готовый, но только соседний:
                # иначе вся лента заполняется одним и тем же кадром.
                i = bisect.bisect_left(keys, at)
                near = min(keys[max(i - 1, 0):i + 1], key=lambda k: abs(k - at))
                step = (self.v1 - self.v0) * w / max(self.strip().width(), 1)
                if abs(near - at) <= step * 1.5:
                    img = self.thumbs[near]
            if img is not None:
                p.drawImage(QRectF(x, r.top(), w, r.height()), img)
        a = self.a if self.a is not None else 0
        b = self.b if self.b is not None else self.duration
        xa, xb = self.x_of(a), self.x_of(b)
        shade = QColor(0, 0, 0, 150)
        if xa > r.left():
            p.fillRect(QRectF(r.left(), r.top(), xa - r.left(), r.height()), shade)
        if xb < r.right():
            p.fillRect(QRectF(xb, r.top(), r.right() - xb, r.height()), shade)
        p.restore()
        if self.a is not None and self.b is not None:
            frame = QPainterPath()
            frame.addRoundedRect(QRectF(xa - self.GRIP, r.top() - 2, xb - xa + 2 * self.GRIP,
                                        r.height() + 4), 7, 7)
            inner = QPainterPath()
            inner.addRect(QRectF(xa, r.top() + 2, xb - xa, r.height() - 4))
            p.fillPath(frame.subtracted(inner), QColor(ACCENT))
            pen = QPen(tone("#1e1e20"))
            pen.setWidthF(2.2)
            pen.setCapStyle(Qt.RoundCap)
            pen.setJoinStyle(Qt.RoundJoin)
            p.setPen(pen)
            cy = r.center().y()
            for x, d in ((xa - self.GRIP / 2, 1), (xb + self.GRIP / 2, -1)):
                p.drawPolyline([QPointF(x + 2 * d, cy - 6), QPointF(x - 2 * d, cy), QPointF(x + 2 * d, cy + 6)])
        if self.v0 <= self.at <= self.v1:
            x = self.x_of(self.at)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(0, 0, 0, 90))
            p.drawRoundedRect(QRectF(x - 2.5, r.top() - 5, 5, r.height() + 10), 2.5, 2.5)
            p.setBrush(QColor("#ffffff"))
            p.drawRoundedRect(QRectF(x - 1.5, r.top() - 4, 3, r.height() + 8), 1.5, 1.5)
        # Полоса всей записи — только когда лента показывает её часть.
        if self.v1 - self.v0 < self.duration:
            y = r.bottom() + 8
            full = QRectF(r.left(), y, r.width(), 4)
            k = full.width() / self.duration
            p.setPen(Qt.NoPen)
            p.setBrush(ink(20))
            p.drawRoundedRect(full, 2, 2)
            p.setBrush(ink(70))
            p.drawRoundedRect(QRectF(full.left() + self.v0 * k, y, max((self.v1 - self.v0) * k, 3), 4), 2, 2)
            if self.a is not None and self.b is not None:
                p.setBrush(QColor(ACCENT))
                p.drawRoundedRect(QRectF(full.left() + a * k, y, max((b - a) * k, 2), 4), 2, 2)

    def _near(self, x):
        if self.a is None or self.b is None:
            return None
        da, db = abs(x - (self.x_of(self.a) - self.GRIP / 2)), abs(x - (self.x_of(self.b) + self.GRIP / 2))
        if min(da, db) > self.GRIP:
            return None
        return "a" if da <= db else "b"

    def mousePressEvent(self, e):
        if not self.duration:
            return
        x, y = e.position().x(), e.position().y()
        if y > self.strip().bottom() + 4 and self.v1 - self.v0 < self.duration:
            # Полоса всей записи: переход туда, куда щёлкнули.
            r = self.strip()
            ms = (x - r.left()) / r.width() * self.duration
            span = self.v1 - self.v0
            self.set_view(ms - span / 2, ms + span / 2)
            self.drag = None
            return
        near = self._near(x)
        if near:
            self.drag = near
        elif self._inside(x):
            # Внутри рамки: потянули — едет вся рамка, просто щёлкнули — перемотка.
            self.drag = "move"
            self.press_x, self.span0, self.moved = x, (self.a, self.b), False
            self.setCursor(Qt.ClosedHandCursor)
            return
        else:
            self.drag = "pos"
        self.mouseMoveEvent(e)

    def _inside(self, x) -> bool:
        return self.a is not None and self.b is not None and self.x_of(self.a) < x < self.x_of(self.b)

    def mouseMoveEvent(self, e):
        x = e.position().x()
        if self.drag is None:
            self.setCursor(Qt.SizeHorCursor if self._near(x)
                           else Qt.OpenHandCursor if self._inside(x) else Qt.PointingHandCursor)
            return
        if self.drag == "move":
            if abs(x - self.press_x) > 3:
                self.moved = True
            if self.moved:
                a0, b0 = self.span0
                shift = (x - self.press_x) / self.strip().width() * (self.v1 - self.v0)
                self.a = int(min(max(a0 + shift, 0), self.duration - (b0 - a0)))
                self.b = self.a + (b0 - a0)
                self.seek.emit(self.a)
                self.changed.emit()
                self.update()
            return
        ms = self.ms_of(x)
        if self.drag == "a":
            self.a = min(ms, self.b - 100)
            self.seek.emit(self.a)
            self.changed.emit()
        elif self.drag == "b":
            self.b = max(ms, self.a + 100)
            self.seek.emit(self.b)
            self.changed.emit()
        else:
            self.seek.emit(ms)
        self.update()

    def mouseReleaseEvent(self, e):
        if self.drag == "move" and not self.moved:
            self.seek.emit(self.ms_of(e.position().x()))
        self.drag = None
        self.mouseMoveEvent(e)

    def wheelEvent(self, e):
        if not self.duration:
            return
        d = e.pixelDelta() if not e.pixelDelta().isNull() else e.angleDelta() / 4
        span = self.v1 - self.v0
        if abs(d.x()) > abs(d.y()):
            shift = -d.x() / self.strip().width() * span
            self.set_view(self.v0 + shift, self.v1 + shift)
        else:
            self._zoom(0.99 ** d.y(), e.position().x())

    def event(self, e):
        if e.type() == QEvent.NativeGesture and e.gestureType() == Qt.ZoomNativeGesture:
            self._zoom(1 / (1 + e.value()), e.position().x())
            return True
        return super().event(e)

    def _zoom(self, k, x):
        span = self.v1 - self.v0
        new = min(max(span * k, min(self.MIN_SPAN, self.duration)), self.duration)
        center = self.ms_of(x)
        left = center - (center - self.v0) * new / max(span, 1)
        self.set_view(left, left + new)


class Labels(QWidget):
    """Ряд меток. Цифра — сохранить с этой меткой, Shift — собрать несколько, Enter — сохранить."""
    chosen = Signal(tuple)

    def __init__(self):
        super().__init__()
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        self.buttons = []
        for i, lab in enumerate(LABELS + (UNIVERSAL,)):
            b = KeyButton(t(lab), str(i + 1), big=True)
            b.setCheckable(True)
            b.clicked.connect(lambda _=False, n=i: self._click(n))
            row.addWidget(b, 2 if lab == UNIVERSAL else 1)
            self.buttons.append(b)
        self.retranslate()
        self.suggested = ()

    TIPS = {"М": "Мужчина один", "Ж": "Женщина одна", "МЖ": "Мужчина — женщине",
            "ЖМ": "Женщина — мужчине", "ММ": "Мужчина — мужчине", "ЖЖ": "Женщина — женщине",
            UNIVERSAL: "Пол не важен или не виден — подходит любой паре"}

    def retranslate(self):
        for i, (b, lab) in enumerate(zip(self.buttons, LABELS + (UNIVERSAL,))):
            b.setToolTip(tf("{tip}. Клавиша {n}; с Shift — добавить к другим меткам",
                            tip=t(self.TIPS[lab]), n=i + 1))

    def _label(self, n):
        return LABELS[n] if n < len(LABELS) else UNIVERSAL

    def _click(self, n):
        # С Shift кнопка уже переключилась сама — так набирается несколько меток.
        if QApplication.keyboardModifiers() & Qt.ShiftModifier and n < len(LABELS):
            return
        self.press(n)

    def press(self, n):
        self.reset()
        self.chosen.emit(() if n == len(LABELS) else (LABELS[n],))

    def toggle(self, n):
        if n >= len(LABELS):
            return
        b = self.buttons[n]
        b.setChecked(not b.isChecked())

    def picked(self) -> tuple:
        return tuple(LABELS[i] for i, b in enumerate(self.buttons[:-1]) if b.isChecked())

    def commit(self) -> bool:
        labels = self.picked() or self.suggested
        if not labels:
            return False
        self.reset()
        self.chosen.emit(labels)
        return True

    def reset(self):
        for b in self.buttons:
            b.setChecked(False)

    def suggest(self, labels):
        self.suggested = tuple(labels)
        for i, b in enumerate(self.buttons):
            want = (self._label(i) in self.suggested)
            if b.property("suggested") != want:
                b.setProperty("suggested", want)
                repolish(b)

    def setEnabled(self, on):
        for b in self.buttons:
            b.setEnabled(on)


def channel_menu(parent, pick, waiting=None, with_all=False) -> QMenu:
    m = menu(parent)
    if with_all:
        total = sum(waiting.values()) if waiting else 0
        m.addAction(tf("Все каналы — {n}", n=total) if waiting is not None else t("Все каналы"),
                    lambda: pick(None))
        m.addSeparator()
    for g in GROUPS:
        sub = menu(m)
        sub.setTitle(g)
        for ch in CHANNELS:
            if ch.group != g:
                continue
            if waiting is not None:
                n = waiting.get(ch.name, 0)
                act = sub.addAction(f"{ch.name} — {n}" if n else ch.name, lambda c=ch.name: pick(c))
                act.setEnabled(bool(n) or not with_all)
            else:
                sub.addAction(ch.name, lambda c=ch.name: pick(c))
        m.addMenu(sub)
    return m


def out_path(root: Path, channel: str, labels, name: str) -> Path:
    ch = BY_NAME.get(channel)
    folder = root / (ch.group if ch else "прочее") / channel / actions.label_folder(labels)
    folder.mkdir(parents=True, exist_ok=True)
    return folder / name


class Converter(QThread):
    """Очередь кодирования: разбор не ждёт ffmpeg, следующая гифка показывается сразу."""
    done = Signal(object, str)

    def __init__(self):
        super().__init__()
        self.q = queue.Queue()

    def put(self, key, fn, *args):
        self.q.put((key, fn, args))

    def flush(self):
        self.q.join()

    def run(self):
        while True:
            job = self.q.get()
            if job is None:
                self.q.task_done()
                return
            key, fn, args = job
            err = ""
            try:
                fn(*args)
            except Exception as e:
                err = str(e) or e.__class__.__name__
            self.q.task_done()
            self.done.emit(key, err)


class Task(QThread):
    """Сторонний поток для сборщика и добавления файлов; события — через сигнал."""
    event = Signal(tuple)

    def __init__(self, fn):
        super().__init__()
        self.fn = fn

    def run(self):
        try:
            self.fn(lambda *a: self.event.emit(a))
        except Exception:
            self.event.emit(("error", traceback.format_exc(limit=3)))


class SortPage(QWidget):
    toCut = Signal(str, str)

    def __init__(self, win):
        super().__init__()
        self.win = win
        self.store = win.store
        self.setFocusPolicy(Qt.StrongFocus)
        self.current = None
        self.filter = None
        self.done = []
        # Каналы, отложенные «Следующим каналом»: в конец очереди, в порядке
        # откладывания. Помнятся и после перезапуска, как и пропущенные гифки.
        later = win.settings.value("later", "")
        self.later = [n for n in later.split("|") if n in BY_NAME] if later else []

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(10)

        top = QHBoxLayout()
        top.setSpacing(8)
        # Наверху одно поле — какую очередь разбирать. Канал самой гифки стоит в
        # подписи под ней, а перенос — отдельной кнопкой внизу: когда оба были
        # полями рядом, выбор очереди путали с переносом гифки.
        self.title = QLabel()
        self.title.setObjectName("title")
        self.title.setToolTip(t("Канал этой гифки"))
        top.addWidget(self.title)
        top.addSpacing(10)
        self.queue_btn = QPushButton(t("Очередь: все каналы"))
        self.queue_btn.setObjectName("field")
        self.queue_btn.setFocusPolicy(Qt.NoFocus)
        self.queue_btn.setCursor(Qt.PointingHandCursor)
        self.queue_btn.setToolTip(t("Какие каналы разбирать"))
        self.queue_btn.clicked.connect(self._pick_queue)
        top.addWidget(self.queue_btn)
        top.addStretch()
        self.left = QLabel()
        self.left.setObjectName("dim")
        top.addWidget(self.left)
        add = QPushButton(t("Добавить файлы…"))
        add.setFocusPolicy(Qt.NoFocus)
        add.clicked.connect(win.choose_files)
        top.addWidget(add)
        folder = QPushButton(t("Папка подборки"))
        folder.setFocusPolicy(Qt.NoFocus)
        folder.clicked.connect(win.open_out)
        top.addWidget(folder)
        v.addLayout(top)

        self.view = VideoView()
        v.addWidget(self.view, 1)

        meta = QHBoxLayout()
        self.meta = QLabel()
        self.meta.setObjectName("meta")
        self.meta.setTextFormat(Qt.RichText)
        self.meta.linkActivated.connect(open_link)
        meta.addWidget(self.meta)
        meta.addStretch()
        self.status = QLabel()
        self.status.setObjectName("meta")
        meta.addWidget(self.status)
        v.addLayout(meta)

        cap = QLabel(t("Сохранить с меткой — кто действует и на кого. Shift — несколько меток, Enter — сохранить"))
        cap.setObjectName("cap")
        v.addWidget(cap)
        self.labels = Labels()
        self.labels.chosen.connect(self.keep)
        v.addWidget(self.labels)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.b_drop = KeyButton(t("Выкинуть"), "X")
        self.b_drop.clicked.connect(self.drop)
        self.b_skip = KeyButton(t("Пропустить"), "→")
        self.b_skip.clicked.connect(self.skip)
        self.b_cut = KeyButton(t("В нарезку"), "C")
        self.b_cut.clicked.connect(self.cut)
        self.b_next = KeyButton(t("Следующий канал"), "↓")
        self.b_next.clicked.connect(self.next_channel)
        self.b_move = KeyButton(t("Перенести в канал…"))
        self.b_move.clicked.connect(self._pick_channel)
        self.b_undo = KeyButton(t("Отменить"), UNDO)
        self.b_undo.clicked.connect(self.undo)
        for btn, tip in ((self.b_drop, "Больше не показывать"),
                         (self.b_skip, "Отложить в конец этого канала"),
                         (self.b_cut, "Вырезать кусок в «Нарезке»"),
                         (self.b_next, "Отложить весь канал, перейти к следующему"),
                         (self.b_move, "Гифка подходит к другому действию"),
                         (self.b_undo, "Вернуть последнее решение")):
            btn.setToolTip(t(tip))
        for b in (self.b_drop, self.b_skip, self.b_cut, self.b_next, self.b_move):
            row.addWidget(b)
        row.addStretch()
        row.addWidget(self.b_undo)
        v.addLayout(row)
        self._buttons(False)
        self.b_undo.setEnabled(False)

    def _buttons(self, on):
        self.labels.setEnabled(on)
        for b in (self.b_drop, self.b_skip, self.b_cut, self.b_next, self.b_move):
            b.setEnabled(on)

    def refresh_count(self):
        waiting = self.store.waiting()
        n = waiting.get(self.filter, 0) if self.filter else sum(waiting.values())
        here = waiting.get(self.current["channel"] or "", 0) if self.current is not None else 0
        if not n:
            self.left.setText("")
        elif self.filter or here == n:
            self.left.setText(tf("в очереди {n}", n=n))
        else:
            self.left.setText(tf("в канале {here} · всего {n}", here=here, n=n))
        return n

    def order(self) -> list:
        names = [c.name for c in CHANNELS]
        return [n for n in names if n not in self.later] + [n for n in self.later if n in names]

    def next_channel(self):
        row = self.current
        if row is None:
            return
        ch = row["channel"]
        if self.filter:
            # В очереди одного канала — переход к следующему каналу, где что-то есть.
            waiting = self.store.waiting()
            names = self.order()
            i = names.index(self.filter) if self.filter in names else -1
            ahead = names[i + 1:] + names[:max(i, 0)]
            target = next((n for n in ahead if waiting.get(n)), None)
            if target:
                self.status.setText("")
                self._set_queue(target)
            return
        if ch:
            if ch in self.later:
                self.later.remove(ch)
            self.later.append(ch)
            self.win.settings.setValue("later", "|".join(self.later))
            self.status.setText(tf("{ch} — позже", ch=ch))
        self.next()

    def next(self):
        order = self.order()
        while True:
            rows = self.store.queue(self.filter, order, limit=1)
            if not rows:
                self.current = None
                break
            row = rows[0]
            if row["path"] and Path(row["path"]).exists():
                self.current = row
                break
            self.store.decide(row["id"], "skip")
        self.show_current()

    def show_current(self):
        self.refresh_count()
        row = self.current
        if row is None:
            self.view.clear(tf("В канале «{name}» пусто", name=self.filter) if self.filter else t("Очередь пуста"))
            self.title.setText("")
            self.meta.setText("")
            self.labels.suggest(())
            self._buttons(False)
            return
        self._buttons(True)
        self.view.text = ""
        self.view.load(row["path"])
        self.labels.reset()
        self.labels.suggest(tuple(row["suggest"].split()) if row["suggest"] else ())
        self.title.setText(row["channel"] or t("без канала"))
        parts = []
        name = sources.NAMES.get(row["source"], row["source"])
        if row["page"]:
            parts.append(f'<a href="{html.escape(row["page"])}" style="color:#8a8f98;text-decoration:none">'
                         f'{html.escape(name)}</a>')
        else:
            parts.append(html.escape(name if row["source"] != "files" else Path(row["path"]).name))
        if row["width"]:
            parts.append(f"{row['width']}×{row['height']}")
        if row["duration"]:
            parts.append(seconds(row["duration"]))
        self.meta.setText("  ·  ".join(parts))

    def added(self):
        if self.current is None:
            self.next()
        else:
            self.refresh_count()

    def keep(self, labels):
        row = self.current
        if row is None:
            return
        if not row["channel"]:
            self.status.setText(t("Сначала канал"))
            self._pick_channel()
            return
        name = f"{(row['sha'] or str(row['id']))[:12]}.gif"
        dst = out_path(self.win.out_dir, row["channel"], labels, name)
        self.store.decide(row["id"], "kept", labels=" ".join(labels), out=str(dst))
        src = self.store.get(row["id"])["path"]
        self.win.converter.put(("keep", row["id"]), media.keep_as_gif, src, dst)
        self.status.setText(f"{row['channel']} / {actions.label_folder(labels)}")
        self._done(row["id"])

    def drop(self):
        if self.current is None:
            return
        self.store.decide(self.current["id"], "dropped")
        self.status.setText(t("выкинута"))
        self._done(self.current["id"])

    def skip(self):
        if self.current is None:
            return
        self.store.bump(self.current["id"])
        self.status.setText("")
        self.next()

    def cut(self):
        row = self.current
        if row is None:
            return
        self.store.decide(row["id"], "cut")
        path = self.store.get(row["id"])["path"]
        self._done(row["id"])
        self.toCut.emit(path, row["channel"] or "")

    def _done(self, item_id):
        self.done.append(item_id)
        self.done = self.done[-200:]
        self.b_undo.setEnabled(True)
        self.next()

    def undo(self):
        if not self.done:
            return
        # Кодирование могло ещё не дойти до этой гифки: дожидаемся очереди.
        self.win.converter.flush()
        item_id = self.done.pop()
        self.store.undo(item_id)
        self.current = self.store.get(item_id)
        self.status.setText(t("отменено"))
        self.b_undo.setEnabled(bool(self.done))
        self.show_current()

    def _pick_channel(self):
        if self.current is None:
            return
        m = channel_menu(self, self._set_channel)
        m.exec(self.b_move.mapToGlobal(self.b_move.rect().topLeft()) - QPoint(0, m.sizeHint().height()))

    def _set_channel(self, name):
        if self.current is None:
            return
        self.store.set_channel(self.current["id"], name)
        self.current = self.store.get(self.current["id"])
        self.show_current()
        self.status.setText(tf("перенесена в {name}", name=name))

    def _pick_queue(self):
        m = channel_menu(self, self._set_queue, self.store.waiting(), with_all=True)
        m.exec(self.queue_btn.mapToGlobal(self.queue_btn.rect().bottomLeft()))

    def _set_queue(self, name):
        self.filter = name
        self.queue_btn.setText(tf("Очередь: {name}", name=name) if name else t("Очередь: все каналы"))
        self.next()

    def keyPressEvent(self, e):
        key, at, n = e.key(), place(e), digit(e)
        command = bool(e.modifiers() & (Qt.ControlModifier | Qt.MetaModifier))
        if at == "z" and command:
            self.undo()
        elif key == Qt.Key_Right:
            self.skip()
        elif key == Qt.Key_Down:
            self.next_channel()
        elif key in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self.labels.commit()
        elif key in (Qt.Key_Backspace, Qt.Key_Delete) or at == "x":
            self.drop()
        elif at == "c" and not command:
            self.cut()
        elif n is not None and self.current is not None:
            if e.modifiers() & Qt.ShiftModifier:
                self.labels.toggle(n)
            else:
                self.labels.press(n)
        else:
            super().keyPressEvent(e)


def _format(height: int) -> str:
    # AV1 наш ffmpeg программно не декодирует, а YouTube отдаёт его первым: просим h264.
    return (f"bv*[height<={height}][vcodec^=avc1]/bv*[height<={height}][vcodec^=vp09]/"
            f"bv*[height<={height}][vcodec!^=av01]/b[height<={height}][vcodec!^=av01]/b")


YT_DIR = DATA / "youtube"
LINK_EXT = ("gif", "mp4", "webm", "mov", "m4v")


_RESOLVED: dict = {}


def resolve(page: str, fresh=False) -> dict:
    """Разбор страницы yt-dlp — 3–5 секунд; полчаса помним, ссылки живут дольше."""
    hit = _RESOLVED.get(page)
    if hit and not fresh and time.time() - hit[0] < 1800:
        return hit[1]
    info = _resolve(page)
    _RESOLVED[page] = (time.time(), info)
    return info


def _resolve(page: str) -> dict:
    from yt_dlp import YoutubeDL
    # Сначала цельный файл по https: его можно смотреть, не скачивая, и резать
    # с любого места — сервер отдаёт нужный кусок по Range.
    fmt = "bv*[height<=720][vcodec^=avc1][protocol=https]/" + _format(720)
    with YoutubeDL({"quiet": True, "no_warnings": True, "format": fmt, "noplaylist": True}) as y:
        return y.extract_info(page, download=False)


def stream_source(info: dict):
    """Поток вместо скачивания: {play, cut, headers} или None.

    play — что играет плеер, cut — откуда ffmpeg берёт нужные секунды. Ссылка,
    выданная под заголовки браузера (VK): ffmpeg передаёт их сам, а плееру Qt
    это не дано — ему местный посредник с теми же заголовками.
    """
    url, proto = info.get("url"), info.get("protocol") or ""
    headers = info.get("http_headers") or {}
    if not url:
        return None
    if proto.startswith("m3u8"):
        return {"play": url, "cut": url, "headers": headers}
    if proto not in ("http", "https"):
        return None
    # Без проверок заранее: через прокси каждая стоила секунды. Заголовки сайта
    # годятся и YouTube, и VK; поток всё же не откроется — нарезка скачает видео.
    return {"play": relay.add(url, headers) if headers else url, "cut": url, "headers": headers}


def download_page(url, progress, stop) -> str:
    """Скачать видео страницы: 480p хватает гифке, куски потока — параллельно."""
    from yt_dlp import YoutubeDL
    from yt_dlp.utils import DownloadCancelled

    def hook(d):
        if stop():
            raise DownloadCancelled()
        total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
        if total:
            progress(d.get("downloaded_bytes", 0) / total)

    YT_DIR.mkdir(parents=True, exist_ok=True)
    opts = {"quiet": True, "no_warnings": True, "noprogress": True, "format": _format(480),
            "concurrent_fragment_downloads": 8, "outtmpl": str(YT_DIR / "%(id)s.%(ext)s"),
            "progress_hooks": [hook], "noplaylist": True}
    with YoutubeDL(opts) as y:
        info = y.extract_info(url, download=True)
        return (info.get("requested_downloads") or [{}])[0].get("filepath") or y.prepare_filename(info)


def short_error(e) -> str:
    text = str(e).strip().splitlines()[-1] if str(e).strip() else e.__class__.__name__
    return text.replace("ERROR: ", "")[:160]


def cut_job(src, headers, page, dst, start, length, crop, side, fps):
    """Ссылка на поток живёт несколько часов: если истекла — берём новую по странице."""
    try:
        media.to_gif(src, dst, start, length, crop, side, fps, headers)
    except RuntimeError:
        fresh = stream_source(resolve(page, fresh=True)) if page else None
        if not fresh:
            raise
        media.to_gif(fresh["cut"], dst, start, length, crop, side, fps, fresh["headers"])


class YouTubeDialog(QDialog):
    """Видео по ссылке или поиск на YouTube. Итог — файл или поток для нарезки."""

    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.result = None
        self.cancelled = False
        self.gen = 0
        self.setWindowTitle(t("Видео по ссылке"))
        self.setObjectName("root")
        self.setStyleSheet(win.styleSheet())
        self.resize(720, 560)
        box = QVBoxLayout(self)
        box.setContentsMargins(20, 18, 20, 18)
        box.setSpacing(10)
        self.query = QLineEdit(win.settings.value("yt_query", ""))
        self.query.setPlaceholderText(t("ссылка: YouTube, VK Видео, Rutube, файл — или запрос для поиска на YouTube"))
        self.query.returnPressed.connect(self.go)
        box.addWidget(self.query)
        self.list = QListWidget()
        self.list.setObjectName("results")
        self.list.setWordWrap(True)
        self.list.itemActivated.connect(lambda item: self.fetch(item.data(Qt.UserRole)))
        box.addWidget(self.list, 1)
        row = QHBoxLayout()
        self.stage = QLabel(" ")
        self.stage.setObjectName("stage")
        row.addWidget(self.stage, 1)
        self.stop_btn = QPushButton(t("Отменить"))
        self.stop_btn.setObjectName("cardbtn")
        self.stop_btn.setVisible(False)
        self.stop_btn.clicked.connect(self.stop)
        row.addWidget(self.stop_btn)
        box.addLayout(row)
        self.bar = Bar()
        self.bar.setVisible(False)
        box.addWidget(self.bar)
        # Enter в поле запускает поиск, а потом доходит до окна, и Qt жмёт кнопку
        # «по умолчанию» — только что появившуюся «Отменить». Таких кнопок здесь нет.
        for b in self.findChildren(QPushButton):
            b.setAutoDefault(False)
            b.setDefault(False)

    def _busy(self, text, bar=False) -> int:
        self.gen += 1
        self.cancelled = False
        self.query.setEnabled(False)
        self.list.setEnabled(False)
        self.stage.setText(text)
        self.bar.set(0)
        self.bar.setVisible(bar)
        self.stop_btn.setVisible(True)
        return self.gen

    def _idle(self, text=""):
        self.query.setEnabled(True)
        self.list.setEnabled(True)
        self.bar.setVisible(False)
        self.stop_btn.setVisible(False)
        self.stage.setText(text)

    def stop(self):
        # Поток сам дойдёт до проверки и бросит работу; его события уже не нужны.
        self.cancelled = True
        self.gen += 1
        self._idle(t("Отменено"))

    def _run(self, fn):
        task = Task(fn)
        task.event.connect(self._event)
        # Ссылка до конца потока: окно могут закрыть раньше, чем он доработает.
        self.win.tasks.add(task)
        task.finished.connect(lambda t=task: self.win.tasks.discard(t))
        task.start()

    def go(self):
        text = self.query.text().strip()
        if not text:
            return
        self.win.settings.setValue("yt_query", text)
        if text.startswith(("http://", "https://")):
            self.fetch(text)
            return
        self.list.clear()
        g = self._busy(t("Поиск…"))

        def work(emit):
            try:
                from yt_dlp import YoutubeDL
                opts = {"quiet": True, "no_warnings": True, "extract_flat": "in_playlist",
                        "skip_download": True}
                with YoutubeDL(opts) as y:
                    info = y.extract_info(f"ytsearch20:{text}", download=False)
                for e in (info or {}).get("entries") or []:
                    emit("hit", g, e.get("url") or f"https://www.youtube.com/watch?v={e.get('id')}",
                         e.get("title") or "", e.get("channel") or e.get("uploader") or "",
                         e.get("duration") or 0)
                emit("searched", g)
            except Exception as e:
                emit("failed", g, short_error(e))

        self._run(work)

    def fetch(self, url):
        if not url:
            return
        YT_DIR.mkdir(parents=True, exist_ok=True)
        ext = Path(urllib.parse.urlparse(url).path).suffix.lower().lstrip(".")
        if ext in LINK_EXT:
            self._direct(url, ext)
            return
        g = self._busy(t("Открытие…"))

        def work(emit):
            try:
                info = resolve(url)
                title = info.get("title") or ""
                stream = stream_source(info)
                if stream:
                    emit("stream", g, stream, title, url, int((info.get("duration") or 0) * 1000))
                    return
                emit("downloading", g)
                path = download_page(url, lambda f: emit("progress", g, f),
                                     lambda: self.cancelled or g != self.gen)
                emit("file", g, path, title)
            except Exception as e:
                emit("failed", g, short_error(e))

        self._run(work)

    def _direct(self, url, ext):
        """Ссылка прямо на файл — качаем сами: yt-dlp представляется браузером, и
        сайты за защитой от ботов ему отказывают, а подписи Gifki — нет."""
        dst = YT_DIR / f"link-{hashlib.md5(url.encode()).hexdigest()[:16]}.{ext}"
        g = self._busy(t("Скачивание…"), bar=True)
        name = Path(urllib.parse.urlparse(url).path).name

        def work(emit):
            if dst.exists():
                emit("file", g, str(dst), name)
                return
            part = dst.with_suffix(dst.suffix + ".part")
            try:
                with sources._open(url, timeout=20) as r, open(part, "wb") as f:
                    total = int(r.headers.get("Content-Length") or 0)
                    got = 0
                    while block := r.read(1 << 16):
                        if self.cancelled or g != self.gen:
                            raise RuntimeError(t("отменено"))
                        f.write(block)
                        got += len(block)
                        if total:
                            emit("progress", g, got / total)
                part.replace(dst)
                emit("file", g, str(dst), name)
            except Exception as e:
                part.unlink(missing_ok=True)
                emit("failed", g, short_error(e))

        self._run(work)

    def _event(self, ev):
        kind, g = ev[0], ev[1] if len(ev) > 1 else None
        if g != self.gen:
            return
        if kind == "hit":
            _, _, url, title, channel, dur = ev
            m, sec = divmod(int(dur), 60)
            tail = "  ·  ".join(x for x in (channel, f"{m}:{sec:02d}" if dur else "") if x)
            item = QListWidgetItem(f"{title}\n{tail}" if tail else title)
            item.setData(Qt.UserRole, url)
            self.list.addItem(item)
        elif kind == "searched":
            self._idle("" if self.list.count() else t("Ничего не нашлось"))
            if self.list.count():
                self.list.setCurrentRow(0)
                self.list.setFocus()
        elif kind == "downloading":
            self.stage.setText(t("Скачивание…"))
            self.bar.setVisible(True)
        elif kind == "progress":
            self.bar.set(ev[2])
        elif kind == "stream":
            _, _, stream, title, page, dur = ev
            self.result = {"src": stream["play"], "cut": stream["cut"], "headers": stream["headers"],
                           "title": title, "page": page, "duration": dur}
            self.accept()
        elif kind == "file":
            self.result = {"src": ev[2], "title": ev[3]}
            self.accept()
        elif kind == "failed":
            self._idle(tf("Не вышло: {e}", e=ev[2]))

    def reject(self):
        self.cancelled = True
        self.gen += 1
        super().reject()


def purge_youtube(days=14):
    """Скачанное по ссылкам живёт две недели: целая серия весит сотни мегабайт."""
    if not YT_DIR.exists():
        return
    edge = time.time() - days * 86400
    for f in YT_DIR.iterdir():
        try:
            if f.stat().st_mtime < edge:
                f.unlink()
        except OSError:
            pass


class CutPage(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.setFocusPolicy(Qt.StrongFocus)
        self.src = None
        self.page = None
        self.cut_src, self.headers = None, {}
        self.title = ""
        self.fps = 24.0
        self.target = None
        self.pending = None
        self.saved = []
        self.loop = False

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(10)

        top = QHBoxLayout()
        top.setSpacing(8)
        self.name = ElideLabel()
        self.name.setObjectName("title")
        top.addWidget(self.name, 1)
        yt = QPushButton(t("Видео по ссылке…"))
        yt.setFocusPolicy(Qt.NoFocus)
        yt.setToolTip(t("YouTube, VK Видео, Rutube, Одноклассники, Дзен или ссылка прямо на файл"))
        yt.clicked.connect(self.youtube)
        top.addWidget(yt)
        open_btn = QPushButton(t("Открыть видео…"))
        open_btn.setFocusPolicy(Qt.NoFocus)
        open_btn.clicked.connect(self.choose)
        top.addWidget(open_btn)
        folder = QPushButton(t("Папка подборки"))
        folder.setFocusPolicy(Qt.NoFocus)
        folder.clicked.connect(win.open_out)
        top.addWidget(folder)
        v.addLayout(top)

        self.view = VideoView(cropping=True)
        self.view.text = t("Видео или гифка")
        self.view.setToolTip(t("Обведите мышью, чтобы обрезать кадр; двойной щелчок — сбросить"))
        self.view.cropChanged.connect(self._update)
        self.view.sized.connect(self._sized)
        self.view.player.positionChanged.connect(self._pos)
        self.view.player.durationChanged.connect(self._duration)
        self.view.player.errorOccurred.connect(self._player_error)
        self.falling_back = False
        self.remote = False
        # Сторож потока: позиция при воспроизведении стоит три секунды — переоткрыть
        # поток с того же места. Так ведёт себя плеер, получивший обрывок данных.
        self.watch = QTimer(self)
        self.watch.setInterval(1000)
        self.watch.timeout.connect(self._watch)
        self.stuck = (0, -1)
        self.reloaded = 0.0
        v.addWidget(self.view, 1)

        self.frames = Frames()
        self.frames.start()
        self.line = TrimBar(self.frames)
        self.line.seek.connect(self._scrub)
        self.line.changed.connect(self._update)
        self.line.changed.connect(self.view.hide_gif)
        v.addWidget(self.line)
        # Бегунок при воспроизведении — по таймеру: позиция от плеера приходит рывками.
        self.tick = QTimer(self)
        self.tick.setInterval(16)
        self.tick.timeout.connect(lambda: self._pos(self.view.player.position()))
        # Протяжка просит кадр не чаще раза в 30 мс: очередь перемоток не копится.
        self.seek_timer = QTimer(self)
        self.seek_timer.setSingleShot(True)
        self.seek_timer.setInterval(30)
        self.seek_timer.timeout.connect(self._do_seek)
        self.want = None

        row = QHBoxLayout()
        row.setSpacing(8)
        self.time = QLabel("00:00.0")
        self.time.setObjectName("dim")
        self.time.setMinimumWidth(70)
        row.addWidget(self.time)
        self.b_play = KeyButton(t("Пуск"), "␣")
        self.b_play.setToolTip(t("Пуск и пауза; стрелки — кадр, с Shift — секунда"))
        self.b_play.clicked.connect(self.play)
        row.addWidget(self.b_play)
        self.b_in = KeyButton(t("Начало"), "I")
        self.b_in.setToolTip(t("Начало отрезка — текущий кадр"))
        self.b_in.clicked.connect(self.mark_in)
        row.addWidget(self.b_in)
        self.b_out = KeyButton(t("Конец"), "O")
        self.b_out.setToolTip(t("Конец отрезка — текущий кадр"))
        self.b_out.clicked.connect(self.mark_out)
        row.addWidget(self.b_out)
        self.span = QLabel()
        self.span.setObjectName("dim")
        self.span.setMinimumWidth(130)
        row.addWidget(self.span)
        row.addStretch()
        self.b_preview = KeyButton(t("Предпросмотр"), "P")
        self.b_preview.setToolTip(t("Собрать гифку из отрезка и показать как есть — с размером и весом."
                                    " P или щелчок — закрыть"))
        self.b_preview.clicked.connect(self.preview)
        row.addWidget(self.b_preview)
        v.addLayout(row)
        self.pgen = 0

        cap = QLabel("Сохранить выделенный отрезок как гифку: канал и метка. Видео остаётся открытым —"
                     " следующий отрезок можно сразу в другой канал")
        cap.setObjectName("cap")
        v.addWidget(cap)
        save = QHBoxLayout()
        save.setSpacing(8)
        self.channel = QPushButton(t("Канал…"))
        self.channel.setObjectName("field")
        self.channel.setFocusPolicy(Qt.NoFocus)
        self.channel.setCursor(Qt.PointingHandCursor)
        self.channel.setMinimumWidth(200)
        self.channel.setFixedHeight(46)
        self.channel.setToolTip(t("Куда сохранить отрезок"))
        self.channel.clicked.connect(self._pick_channel)
        save.addWidget(self.channel)
        self.labels = Labels()
        self.labels.chosen.connect(self.save)
        save.addWidget(self.labels, 1)
        v.addLayout(save)
        done = QHBoxLayout()
        done.setSpacing(8)
        for text, attr, values, key, default, tip in (
                ("Ширина, px", "side_seg", ("320", "480", "640"), "cut_size", "480",
                 "Ширина гифки. Больше — чётче, но тяжелее; Discord берёт до 10 МБ"),
                ("Кадров/с", "rate_seg", ("15", "20", "25"), "cut_fps", "20",
                 "Плавность: больше кадров — плавнее и тяжелее")):
            cap = QLabel(t(text))
            cap.setObjectName("cap")
            done.addWidget(cap)
            seg = self._segment(values, key, default)
            seg.setToolTip(t(tip))
            setattr(self, attr, seg)
            done.addWidget(seg)
            done.addSpacing(8)
        self.dims = QLabel()
        self.dims.setObjectName("dim")
        self.dims.setMinimumWidth(78)
        self.dims.setToolTip(t("Размер будущей гифки в пикселях"))
        done.addWidget(self.dims)
        done.addSpacing(8)
        self.status = QLabel()
        self.status.setObjectName("saved")
        done.addWidget(self.status, 1)
        self.b_undo = KeyButton(t("Отменить"), UNDO)
        self.b_undo.setToolTip(t("Удалить последнюю сохранённую гифку"))
        self.b_undo.clicked.connect(self.undo)
        self.b_undo.setEnabled(False)
        done.addWidget(self.b_undo)
        v.addLayout(done)
        self._update()

    def _segment(self, values, key, default):
        box = QFrame()
        box.setObjectName("segment")
        lay = QHBoxLayout(box)
        lay.setContentsMargins(3, 3, 3, 3)
        lay.setSpacing(3)
        cur = str(self.win.settings.value(key, default))
        for val in values:
            b = QPushButton(val)
            b.setObjectName("seg")
            b.setCheckable(True)
            b.setAutoExclusive(True)
            b.setFocusPolicy(Qt.NoFocus)
            b.setCursor(Qt.PointingHandCursor)
            b.setChecked(val == cur)
            b.clicked.connect(lambda _=False, x=val: self._setting(key, x))
            lay.addWidget(b)
        box.value = lambda: int(next(b.text() for b in box.findChildren(QPushButton) if b.isChecked()))
        return box

    def _setting(self, key, value):
        self.win.settings.setValue(key, value)
        self._update()
        # Предпросмотр открыт — пересобираем: так и видно, что меняет ширина.
        if self.view.overlay is not None:
            self.preview(again=True)

    def _dims(self):
        img = self.view.image
        if img.isNull():
            return None
        W, H = img.width(), img.height()
        c = self.view.crop
        if not c.isEmpty():
            W, H = c.width() * W, c.height() * H
        side = self.side_seg.value()
        # Как в media.to_gif: длинная сторона не больше выбранной, вторая — чётная.
        if W >= H:
            w = min(side, W)
            return int(w) // 2 * 2, int(round(H * w / W / 2)) * 2
        h = min(side, H)
        return int(round(W * h / H / 2)) * 2, int(h) // 2 * 2

    def preview(self, again=False):
        if self.view.overlay is not None and not again:
            self.view.hide_gif()
            return
        a, b = self.line.a, self.line.b
        if self.src is None or a is None or b is None or b <= a:
            return
        self.pgen += 1
        g = self.pgen
        folder = DATA / "preview"
        folder.mkdir(parents=True, exist_ok=True)
        dst = folder / f"{g % 4}.gif"
        args = (self.cut_src, self.headers, self.page, dst, a / 1000, (b - a) / 1000, self._crop(),
                self.side_seg.value(), self.rate_seg.value())
        self.status.setText(t("Сборка предпросмотра…"))

        def work(emit):
            try:
                cut_job(*args)
                info = media.probe(dst)
                emit("preview", g, str(dst), info.width, info.height, dst.stat().st_size)
            except Exception as e:
                emit("preview_failed", g, short_error(e))

        task = Task(work)
        task.event.connect(self._preview_event)
        self.win.tasks.add(task)
        task.finished.connect(lambda t=task: self.win.tasks.discard(t))
        task.start()

    def _preview_event(self, ev):
        if ev[1] != self.pgen:
            return
        if ev[0] == "preview":
            _, _, path, w, h, size = ev
            mb = f"{size / 1024 / 1024:.1f}".replace(".", ",")
            self.view.show_gif(path, tf("{w}×{h} · {mb} МБ — так гифка будет выглядеть", w=w, h=h, mb=mb))
            self.status.setText("")
        else:
            self.status.setText(tf("Предпросмотр не собрался: {e}", e=ev[2]))

    def choose(self):
        path, _ = QFileDialog.getOpenFileName(
            self, t("Видео"), str(self.win.settings.value("cut_dir", QStandardPaths.writableLocation(QStandardPaths.MoviesLocation))),
            t("Видео и гифки") + " (*.mp4 *.mkv *.webm *.mov *.m4v *.avi *.gif)")
        if path:
            self.win.settings.setValue("cut_dir", str(Path(path).parent))
            self.open(path)

    def youtube(self):
        d = YouTubeDialog(self.win)
        if d.exec() == QDialog.Accepted and d.result:
            r = d.result
            self.open(r["src"], title=r.get("title"), page=r.get("page"), duration=r.get("duration", 0),
                      cut=r.get("cut"), headers=r.get("headers"))

    def youtube_and_show(self):
        self.win.show_page(1)
        self.youtube()

    def open(self, src, channel="", title=None, page=None, duration=0, cut=None, headers=None):
        src = str(src)
        remote = src.startswith(("http://", "https://"))
        self.src, self.page = src, page
        self.falling_back = False
        self.remote = remote
        self.reloaded = 0.0
        if remote:
            self.watch.start()
        else:
            self.watch.stop()
        # Откуда ffmpeg берёт кадры и отрезки: для VK — прямая ссылка с заголовками,
        # а плеер в это время играет через местного посредника.
        self.cut_src, self.headers = (cut or src), (headers or {})
        self.title = title or Path(src).name
        if remote:
            # Поток не пробуем ffprobe заранее: длину знает сайт, размер кадра — плеер.
            total, aspect, self.fps = int(duration), 0, 25.0
        else:
            info = media.probe(src)
            total = int(info.duration * 1000)
            aspect = info.width / info.height if info.height else 0
            self.fps = info.fps or 24.0
        self.name.set(self.title)
        self.view.hide_gif()
        short = 0 < total <= 15000
        self.line.set_source(src, total, aspect, self.cut_src, self.headers, remote)
        # Короткое — целиком, длинное — первые три секунды: дальше рамку тянут.
        self.line.a = 0 if total else None
        self.line.b = (total if short else min(total, 3000)) if total else None
        self.view.load(src, loop=False, play=short)
        self.loop = short
        self._playing(short)
        if channel:
            self._set_channel(channel)
        self._update()
        self.setFocus()

    def _watch(self):
        p = self.view.player
        if not self.remote or p.playbackState() != QMediaPlayer.PlayingState:
            self.stuck = (0, -1)
            return
        n, last = self.stuck
        pos = p.position()
        self.stuck = (n + 1, pos) if pos == last else (0, pos)
        if self.stuck[0] >= 3:
            self._reload()

    def _reload(self):
        """Переоткрыть поток с того же места — обычно этого хватает."""
        p = self.view.player
        pos, playing = p.position(), p.playbackState() == QMediaPlayer.PlayingState
        self.reloaded = time.time()
        self.stuck = (0, -1)
        p.setSource(QUrl(self.src))
        p.setPosition(pos)
        if playing:
            p.play()
        else:
            p.pause()

    def _player_error(self, err, text):
        if not err:
            return
        if self.remote and time.time() - self.reloaded > 10:
            self._reload()    # первая ошибка — переоткрыть; повторилась быстро — скачать
            return
        if not (self.page and self.src and self.src.startswith("http")) or self.falling_back:
            self.status.setText(tf("Видео не открылось: {e}", e=text))
            return
        # Поток не открылся — тогда скачать, как раньше, и открыть уже файл.
        self.falling_back = True
        page, title = self.page, self.title
        self.status.setText(t("Поток не открылся — скачивание…"))

        def work(emit):
            try:
                emit("done", download_page(page, lambda f: emit("progress", f), lambda: False))
            except Exception as e:
                emit("failed", short_error(e))

        def event(ev):
            if ev[0] == "progress":
                self.status.setText(t("Поток не открылся — скачивание…") + f" {int(ev[1] * 100)}%")
            elif ev[0] == "done":
                self.open(ev[1], title=title)
                self.status.setText("")
            elif ev[0] == "failed":
                self.status.setText(tf("Видео не открылось: {e}", e=ev[1]))

        task = Task(work)
        task.event.connect(event)
        self.win.tasks.add(task)
        task.finished.connect(lambda t=task: self.win.tasks.discard(t))
        task.start()

    def _playing(self, on):
        self.b_play.setText(t("Пауза") if on else t("Пуск"))
        if on:
            self.tick.start()
        else:
            self.tick.stop()

    def _sized(self, w, h):
        if h:
            self.line.aspect = w / h
            self.line._request()
            self.line.update()
        self._update()

    def _duration(self, ms):
        if ms > 0 and self.line.duration != ms and self.src is not None:
            a, b = self.line.a, self.line.b
            self.line.set_source(self.src, ms, self.line.aspect, self.cut_src, self.headers,
                                 self.src.startswith(("http://", "https://")))
            self.line.a = 0 if a is None else min(a, ms)
            self.line.b = min(ms, 3000) if b is None else min(b, ms)
            self._update()
        self.line.update()

    def _pos(self, ms):
        if self.line.drag:
            return      # пока тянут ленту, бегунок у мыши, а не у плеера
        a, b = self.line.a, self.line.b
        playing = self.view.player.playbackState() == QMediaPlayer.PlayingState
        if self.loop and playing and a is not None and b is not None and ms >= b:
            self.view.player.setPosition(a)
            return
        self.line.at = ms
        if playing:
            self.line.follow(ms)
        self.line.update()
        self.time.setText(clock(ms))

    def _seek(self, ms):
        self.view.player.setPosition(ms)
        self.line.at = ms
        self.time.setText(clock(ms))
        self.line.follow(ms)
        self.line.update()

    def _scrub(self, ms):
        """Протяжка по ленте, край или вся рамка: видео стоит и показывает кадр."""
        if self.view.player.playbackState() == QMediaPlayer.PlayingState:
            self.view.player.pause()
            self._playing(False)
        self.want = ms
        self.line.at = ms
        self.time.setText(clock(ms))
        self.line.update()
        if self.remote:
            # Поток: каждая перемотка — новое соединение с сайтом. Просим кадр,
            # когда мышь на миг остановилась, иначе сотни соединений рвут поток.
            self.seek_timer.start(150)
        elif not self.seek_timer.isActive():
            self.seek_timer.start(30)

    def _do_seek(self):
        if self.want is not None:
            self.view.player.setPosition(self.want)
            self.want = None

    def play(self):
        p = self.view.player
        if self.src is None:
            return
        if p.playbackState() == QMediaPlayer.PlayingState:
            p.pause()
            self._playing(False)
            return
        self.view.hide_gif()
        a, b = self.line.a, self.line.b
        pos = p.position()
        # Петля, только если пуск внутри отрезка: иначе листаем запись дальше.
        self.loop = a is not None and b is not None and a <= pos < b
        if p.mediaStatus() == QMediaPlayer.EndOfMedia:
            p.setPosition(a if self.loop else 0)
        p.play()
        self._playing(True)

    def step(self, ms):
        p = self.view.player
        p.pause()
        self._playing(False)
        self._seek(min(max(p.position() + ms, 0), max(p.duration(), 0)))

    def mark_in(self):
        if self.src is None:
            return
        at = self.view.player.position()
        if self.line.b is not None and self.line.b <= at:
            self.line.b = min(at + 3000, self.line.duration or at + 3000)
        self.line.a = at
        self._update()

    def mark_out(self):
        if self.src is None:
            return
        at = self.view.player.position()
        if self.line.a is not None and self.line.a >= at:
            self.line.a = max(at - 3000, 0)
        self.line.b = at
        self._update()

    def _update(self):
        a, b = self.line.a, self.line.b
        ready = self.src is not None and a is not None and b is not None and b > a
        self.labels.setEnabled(ready)
        parts = []
        if ready:
            parts.append(tf("отрезок {s}", s=seconds((b - a) / 1000)))
        if not self.view.crop.isEmpty():
            parts.append(t("кадр обрезан"))
        self.span.setText("  ·  ".join(parts))
        self.b_preview.setEnabled(ready)
        d = self._dims()
        self.dims.setText(f"→ {d[0]}×{d[1]}" if d else "")
        self.line.update()

    def _pick_channel(self):
        m = channel_menu(self, self._set_channel)
        m.exec(self.channel.mapToGlobal(self.channel.rect().topLeft()) - QPoint(0, m.sizeHint().height()))
        self.pending = None

    def _set_channel(self, name):
        self.target = name
        self.channel.setText(tf("Канал: {name}", name=name))
        self._update()
        if self.pending is not None:
            labels, self.pending = self.pending, None
            self.save(labels)

    def _crop(self) -> str:
        c = self.view.crop
        img = self.view.image
        if c.isEmpty() or img.isNull():
            return ""
        # Кадр плеера — в исходном размере, по нему и считаем.
        W, H = img.width(), img.height()
        w, h = int(c.width() * W) // 2 * 2, int(c.height() * H) // 2 * 2
        return f"crop={w}:{h}:{int(c.x() * W)}:{int(c.y() * H)}"

    def save(self, labels):
        a, b = self.line.a, self.line.b
        if self.src is None or a is None or b is None or b <= a:
            return
        if not self.target:
            # Канал ещё не выбран — спрашиваем и сохраняем с той же меткой.
            self.pending = labels
            m = channel_menu(self, self._set_channel)
            m.exec(self.channel.mapToGlobal(self.channel.rect().topLeft()) - QPoint(0, m.sizeHint().height()))
            return
        base = re.sub(r'[\\/:*?"<>|\s]+', " ", Path(self.title).stem if not self.page else self.title)
        name = f"{base.strip()[:48] or t('отрывок')} {clock(a).replace(':', '-')}.gif"
        dst = out_path(self.win.out_dir, self.target, labels, name)
        self.win.converter.put(("cut", str(dst)), cut_job, self.cut_src, self.headers, self.page, dst,
                               a / 1000, (b - a) / 1000, self._crop(),
                               self.side_seg.value(), self.rate_seg.value())
        self.saved.append(dst)
        self.b_undo.setEnabled(True)
        self.status.setText(tf("Сохранено: {target} / {labels} · {s}", target=self.target,
                               labels=t(actions.label_folder(labels)), s=seconds((b - a) / 1000)))

    def undo(self):
        if not self.saved:
            return
        self.win.converter.flush()
        dst = self.saved.pop()
        dst.unlink(missing_ok=True)
        self.status.setText(t("Последняя гифка удалена"))
        self.b_undo.setEnabled(bool(self.saved))

    def keyPressEvent(self, e):
        code, n = place(e), digit(e)
        mods = e.modifiers()
        shift = bool(mods & Qt.ShiftModifier)
        if code == "z" and mods & (Qt.ControlModifier | Qt.MetaModifier):
            self.undo()
        elif e.key() == Qt.Key_Space:
            self.play()
        elif e.key() == Qt.Key_Left:
            self.step(-1000 if shift else -1000 / self.fps)
        elif e.key() == Qt.Key_Right:
            self.step(1000 if shift else 1000 / self.fps)
        elif code == "i":
            self.mark_in()
        elif code == "o":
            self.mark_out()
        elif code == "p":
            self.preview()
        elif e.key() == Qt.Key_Escape and self.view.overlay is not None:
            self.view.hide_gif()
        elif n is not None and self.labels.buttons[0].isEnabled():
            if shift:
                self.labels.toggle(n)
            else:
                self.labels.press(n)
        elif e.key() in (Qt.Key_Return, Qt.Key_Enter):
            self.labels.commit()
        else:
            super().keyPressEvent(e)


class ChannelsDialog(QDialog):
    """Свои каналы и поиск у встроенных. Правки — в channels.json рядом с базой."""

    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.setWindowTitle(t("Каналы"))
        self.setObjectName("root")
        self.setStyleSheet(win.styleSheet())
        self.resize(900, 600)
        self.entries = {e["name"]: e for e in win.channel_entries}
        self.current = None    # имя выбранного канала; None — новый

        outer = QHBoxLayout(self)
        outer.setContentsMargins(20, 18, 20, 18)
        outer.setSpacing(16)

        left = QVBoxLayout()
        left.setSpacing(8)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setRootIsDecorated(False)
        self.tree.setIndentation(0)
        self.tree.currentItemChanged.connect(lambda item, _: self._pick(item))
        left.addWidget(self.tree, 1)
        new = QPushButton(t("Новый канал"))
        new.clicked.connect(self._new)
        left.addWidget(new)
        outer.addLayout(left, 2)

        card = QFrame()
        card.setObjectName("card")
        form = QVBoxLayout(card)
        form.setContentsMargins(16, 14, 16, 14)
        form.setSpacing(6)

        def field(caption, widget):
            cap = QLabel(caption)
            cap.setObjectName("cap")
            form.addWidget(cap)
            form.addWidget(widget)
            form.addSpacing(8)
            return widget

        self.name = field(t("Канал на гиф-сервере"), QLineEdit())
        seg = QFrame()
        seg.setObjectName("segment")
        sl = QHBoxLayout(seg)
        sl.setContentsMargins(3, 3, 3, 3)
        sl.setSpacing(3)
        self.group_btns = {}
        for g in GROUPS:
            b = QPushButton(g)
            b.setObjectName("seg")
            b.setCheckable(True)
            b.setAutoExclusive(True)
            b.setCursor(Qt.PointingHandCursor)
            sl.addWidget(b)
            self.group_btns[g] = b
        row = QHBoxLayout()
        row.addWidget(seg)
        row.addStretch()
        holder = QWidget()
        holder.setLayout(row)
        row.setContentsMargins(0, 0, 0, 0)
        field(t("Группа — папка в подборке"), holder)
        self.booru = field(t("Теги Danbooru и Safebooru"), QLineEdit())
        self.booru.setPlaceholderText("hug hug_from_behind")
        self.giphy = field(t("Запрос Giphy — ищется как «anime …» и «cartoon …»"), QLineEdit())
        self.giphy.setPlaceholderText("hug")
        self.apis = field(t("Аниме-API — реакция: у всех API или одного, otaku, purr, nekoslife,"
                            " nekosbest, waifu"), QLineEdit())
        self.apis.setPlaceholderText(t("hug  или  otaku:hug"))
        self.mutual = QCheckBox(t("Взаимное: пара «парень и девушка» — сразу МЖ и ЖМ"))
        form.addWidget(self.mutual)
        form.addSpacing(6)
        self.note = QLabel()
        self.note.setObjectName("meta")
        self.note.setWordWrap(True)
        form.addWidget(self.note)
        form.addStretch()

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self.remove = QPushButton()
        self.remove.setObjectName("cardbtn")
        self.remove.clicked.connect(self._remove)
        buttons.addWidget(self.remove)
        buttons.addStretch()
        self.ok = QPushButton(t("Сохранить"))
        self.ok.setObjectName("cardbtnAccent")
        self.ok.clicked.connect(self._store)
        buttons.addWidget(self.ok)
        form.addLayout(buttons)
        outer.addWidget(card, 3)
        # Enter в поле — «Сохранить», а не первая попавшаяся кнопка вроде «Удалить канал».
        for b in self.findChildren(QPushButton):
            b.setAutoDefault(False)
        self.ok.setDefault(True)

        self._fill()

    def _fill(self, select=None):
        self.tree.blockSignals(True)
        self.tree.clear()
        bold = QFont(self.tree.font())
        bold.setWeight(QFont.DemiBold)
        chosen = None
        for g in GROUPS:
            head = QTreeWidgetItem([g])
            head.setFont(0, bold)
            head.setForeground(0, tone("#8a8f98"))
            head.setFlags(Qt.ItemIsEnabled)
            self.tree.addTopLevelItem(head)
            for ch in CHANNELS:
                if ch.group != g:
                    continue
                mark = "" if ch.name in actions.DEFAULTS else t("  · свой")
                item = QTreeWidgetItem([ch.name + mark])
                item.setData(0, Qt.UserRole, ch.name)
                self.tree.addTopLevelItem(item)
                if ch.name == (select or CHANNELS[0].name):
                    chosen = item
        self.tree.blockSignals(False)
        if chosen is not None:
            self.tree.setCurrentItem(chosen)

    def _pick(self, item):
        name = item.data(0, Qt.UserRole) if item is not None else None
        if not name or name not in BY_NAME:
            return
        self._show(BY_NAME[name])

    def _show(self, ch):
        self.current = ch.name if ch else None
        builtin = bool(ch) and ch.name in actions.DEFAULTS
        self.name.setText(ch.name if ch else "")
        self.name.setReadOnly(builtin)
        self.group_btns[ch.group if ch else GROUPS[0]].setChecked(True)
        self.booru.setText(" ".join(ch.booru) if ch else "")
        self.giphy.setText(ch.en if ch else "")
        self.apis.setText(" ".join(ch.apis) if ch else "")
        self.mutual.setChecked(bool(ch) and ch.mutual)
        self.note.setText("")
        if not ch:
            self.remove.setVisible(False)
        elif builtin:
            self.remove.setText(t("Вернуть как было"))
            self.remove.setVisible(ch.name in self.entries)
        else:
            self.remove.setText(t("Удалить канал"))
            self.remove.setVisible(True)
        if not ch:
            self.name.setFocus()

    def _new(self):
        self.tree.clearSelection()
        self._show(None)

    def _form(self) -> dict:
        group = next(g for g, b in self.group_btns.items() if b.isChecked())
        return {"name": actions.clean_name(self.name.text()), "group": group,
                "booru": actions.clean_tags(self.booru.text()),
                "en": self.giphy.text().strip().lower(),
                "apis": actions.clean_apis(self.apis.text())[0],
                "mutual": self.mutual.isChecked()}

    def _store(self):
        e = self._form()
        name = e["name"]
        if not name:
            self.note.setText(t("Нужно название канала."))
            return
        old = self.current
        if name != old and name in BY_NAME:
            self.note.setText(tf("Канал «{name}» уже есть.", name=name))
            return
        if old in actions.DEFAULTS:
            # Без отличий от встроенного правку не храним: так «как было» не теряется.
            if e == actions.entry(actions.DEFAULTS[old]):
                self.entries.pop(old, None)
            else:
                self.entries[old] = e
        else:
            if old and old != name:
                self.entries.pop(old, None)
                self.win.store.rename_channel(old, name)
            self.entries[name] = e
            if old is None:
                # Новый канал сразу отмечен на «Сборе».
                picked = self.win.settings.value("channels", "")
                if picked:
                    self.win.settings.setValue("channels", picked + "|" + name)
        self._commit(name)

    def _remove(self):
        if self.current is None:
            return
        self.entries.pop(self.current, None)
        keep = self.current if self.current in actions.DEFAULTS else None
        self._commit(keep)

    def _commit(self, select):
        unknown = actions.clean_apis(self.apis.text())[1]
        entries = list(self.entries.values())
        actions.save(self.win.channel_file, entries)
        self.win.channel_entries = entries
        self.win.channels_changed()
        self._fill(select)
        if unknown:
            # Набор у API закрытый: незнакомое слово просто ничего не найдёт.
            self.note.setText(t("Таких реакций в аниме-API нет: ") + ", ".join(unknown))


class CollectPage(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.task = None
        self.collector = None
        # Ссылки на потоки до их конца: QThread без ссылки роняет процесс.
        self.alive = set()
        s = win.settings

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        scroll = QScrollArea()
        scroll.setObjectName("bare")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        inner = QWidget()
        inner.setObjectName("bare")
        scroll.setWidget(inner)
        outer.addWidget(scroll, 1)
        v = QVBoxLayout(inner)
        v.setContentsMargins(0, 0, 6, 0)
        v.setSpacing(0)

        head = QHBoxLayout()
        cap = QLabel(t("Источники"))
        cap.setObjectName("section")
        head.addWidget(cap)
        head.addStretch()
        link = QPushButton(t("Видео по ссылке…"))
        link.setObjectName("cardbtn")
        link.setCursor(Qt.PointingHandCursor)
        link.setToolTip(t("YouTube, VK Видео, Rutube, Одноклассники, Дзен или ссылка прямо на файл"))
        link.clicked.connect(win.cut.youtube_and_show)
        head.addWidget(link)
        v.addLayout(head)
        v.addSpacing(8)
        card = QFrame()
        card.setObjectName("card")
        grid = QGridLayout(card)
        grid.setContentsMargins(16, 14, 16, 14)
        grid.setHorizontalSpacing(24)
        grid.setVerticalSpacing(13)
        # nekos.best закрыл доступ нашему диапазону адресов, waifu.pics не отвечает —
        # включаются руками, если оживут.
        off = {"nekosbest", "waifu"}
        chosen = set(s.value("sources", " ".join(k for k in sources.ORDER if k not in off)).split())
        # Источник, появившийся после сохранения настроек, включён сразу.
        seen = s.value("sources_seen", None)
        if seen is not None:
            chosen |= {k for k in sources.ORDER if k not in seen.split() and k not in off}
        self.src_boxes = {}
        plain = [k for k in sources.ORDER if k not in sources.KEYED]
        for i, key in enumerate(sources.ORDER):
            cb = QCheckBox(sources.NAMES[key])
            cb.setChecked(key in chosen)
            cb.toggled.connect(self._save)
            self.src_boxes[key] = cb
        for i, key in enumerate(plain):
            grid.addWidget(self.src_boxes[key], i // 4, i % 4)
        rows = (len(plain) + 3) // 4

        def keyed(row, key, *fields):
            r = QHBoxLayout()
            r.setSpacing(12)
            box = self.src_boxes[key]
            box.setMinimumWidth(110)
            r.addWidget(box)
            for f in fields:
                r.addWidget(f)
            r.addStretch()
            grid.addLayout(r, row, 0, 1, 4)

        def secret(value, hint, width=260, hidden=True):
            f = QLineEdit(value)
            f.setPlaceholderText(hint)
            if hidden:
                f.setEchoMode(QLineEdit.Password)
            f.setFixedWidth(width)
            f.textChanged.connect(self._save)
            return f

        self.key = secret(s.value("giphy_key", ""), t("ключ API"))
        keyed(rows, "giphy", self.key)
        self.reddit_id = secret(s.value("reddit_id", ""), t("ID приложения"), 200, hidden=False)
        self.reddit_secret = secret(s.value("reddit_secret", ""), t("секрет"), 260)
        keyed(rows + 1, "reddit", self.reddit_id, self.reddit_secret)
        v.addWidget(card)
        v.addSpacing(20)

        head = QHBoxLayout()
        cap = QLabel(t("Каналы"))
        cap.setObjectName("section")
        head.addWidget(cap)
        head.addStretch()
        edit = QPushButton(t("Изменить…"))
        edit.setObjectName("cardbtn")
        edit.setCursor(Qt.PointingHandCursor)
        edit.clicked.connect(lambda: ChannelsDialog(self.win).exec())
        head.addWidget(edit)
        v.addLayout(head)
        v.addSpacing(8)
        self.vbox = v
        self.ch_boxes = {}
        self.ch_card = self._channel_card()
        v.addWidget(self.ch_card)
        v.addSpacing(20)

        r = QHBoxLayout()
        r.setSpacing(12)
        lab = QLabel(t("С каждого источника на канал"))
        r.addWidget(lab)
        seg = QFrame()
        seg.setObjectName("segment")
        sl = QHBoxLayout(seg)
        sl.setContentsMargins(3, 3, 3, 3)
        sl.setSpacing(3)
        want = str(s.value("want", "30"))
        self.want_btns = []
        for val in ("10", "30", "100", "300"):
            b = QPushButton(val)
            b.setObjectName("seg")
            b.setCheckable(True)
            b.setAutoExclusive(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setChecked(val == want)
            b.clicked.connect(self._save)
            sl.addWidget(b)
            self.want_btns.append(b)
        r.addWidget(seg)
        r.addStretch()
        v.addLayout(r)
        v.addStretch()

        bottom = QVBoxLayout()
        bottom.setContentsMargins(0, 14, 0, 0)
        bottom.setSpacing(8)
        self.go = QPushButton(t("Собрать"))
        self.go.setObjectName("primary")
        self.go.setFixedHeight(46)
        self.go.clicked.connect(self.toggle)
        bottom.addWidget(self.go)
        self.stage = QLabel(" ")
        self.stage.setObjectName("stage")
        bottom.addWidget(self.stage)
        self.bar = Bar()
        bottom.addWidget(self.bar)
        self.down = QLabel()
        self.down.setObjectName("meta")
        self.down.setWordWrap(True)
        bottom.addWidget(self.down)
        outer.addLayout(bottom)
        self.bar.setVisible(False)

    def _channel_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("card")
        grid = QGridLayout(card)
        grid.setContentsMargins(16, 14, 16, 14)
        grid.setHorizontalSpacing(20)
        grid.setVerticalSpacing(10)
        picked = self.win.settings.value("channels", None)
        picked = set(picked.split("|")) if picked else {c.name for c in CHANNELS}
        self.ch_boxes = {}
        per_row = 5
        row = 0
        for g in GROUPS:
            members = [c for c in CHANNELS if c.group == g and actions.searchable(c)]
            if not members:
                continue
            allbox = QCheckBox(g)
            allbox.setStyleSheet("font-weight: 600;")
            grid.addWidget(allbox, row, 0, 1, per_row)
            row += 1
            for n, ch in enumerate(members):
                cb = QCheckBox(ch.name)
                cb.setChecked(ch.name in picked)
                cb.toggled.connect(self._save)
                self.ch_boxes[ch.name] = cb
                grid.addWidget(cb, row + n // per_row, n % per_row)
            row += (len(members) + per_row - 1) // per_row
            allbox.setChecked(all(self.ch_boxes[c.name].isChecked() for c in members))
            allbox.clicked.connect(lambda on, m=members: self._group(m, on))
            grid.setRowMinimumHeight(row, 6)
            row += 1
        for col in range(per_row):
            grid.setColumnStretch(col, 1)
        return card

    def rebuild(self):
        """После правки каналов: сетка заново, отмеченное остаётся отмеченным."""
        old = self.ch_card
        self.ch_card = self._channel_card()
        self.vbox.replaceWidget(old, self.ch_card)
        old.deleteLater()

    def _group(self, members, on):
        for c in members:
            self.ch_boxes[c.name].setChecked(on)

    def _save(self):
        s = self.win.settings
        s.setValue("sources", " ".join(k for k, b in self.src_boxes.items() if b.isChecked()))
        s.setValue("channels", "|".join(k for k, b in self.ch_boxes.items() if b.isChecked()))
        s.setValue("want", next(b.text() for b in self.want_btns if b.isChecked()))
        s.setValue("giphy_key", self.key.text().strip())
        s.setValue("reddit_id", self.reddit_id.text().strip())
        s.setValue("reddit_secret", self.reddit_secret.text().strip())
        s.setValue("sources_seen", " ".join(sources.ORDER))

    def keys(self) -> dict:
        rid, secret = self.reddit_id.text().strip(), self.reddit_secret.text().strip()
        return {"giphy": self.key.text().strip(),
                "reddit": f"{rid}:{secret}" if rid and secret else ""}

    def toggle(self):
        if self.task is not None:
            # Поток может ещё ждать ответа сети — окно его не ждёт.
            self.collector.stop()
            self._ended(tf("Остановлено. Новых: {n}", n=self.added))
            return
        chans = [BY_NAME[n] for n, b in self.ch_boxes.items() if b.isChecked()]
        srcs = [k for k, b in self.src_boxes.items() if b.isChecked()]
        if not chans or not srcs:
            return
        want = int(next(b.text() for b in self.want_btns if b.isChecked()))
        self.collector = sources.Collector(self.win.store, chans, srcs, want, self.keys(), None)
        self.added = 0
        self.where = {}
        self.down.setText("")

        def work(emit):
            self.collector.emit = emit
            self.collector.run()

        task = Task(work)
        task.event.connect(lambda ev, t=task: self._event(ev, t))
        task.finished.connect(lambda t=task: self._finished(t))
        self.task = task
        self.alive.add(task)
        self.go.setText(t("Остановить"))
        self.bar.set(0)
        self.bar.setVisible(True)
        self.stage.setText(t("Сбор…"))
        self.task.start()

    def _event(self, ev, task):
        kind = ev[0]
        if task is not self.task:
            # Остановленный сбор успел дописать гифку — в очередь она уже попала.
            if kind == "added":
                self.win.sort.added()
            return
        if kind == "progress":
            _, src, i, n, ch = ev
            self.where[src] = (i, ch)
            self.bar.set(sum(x for x, _ in self.where.values()) / max(n * len(self.where), 1))
            self._stage()
        elif kind == "added":
            self.added += 1
            self.win.sort.added()
            self._stage()
        elif kind == "down":
            _, src, text, final = ev
            line = f"{sources.NAMES[src]}: {text}"
            if final and src in self.src_boxes and src not in sources.KEYED:
                # Закрытый доступ сам не откроется: незачем стучаться в следующий раз.
                # Источник с ключом не выключаем — ключ поправят.
                self.src_boxes[src].setChecked(False)
                line += t(", отключён")
            self.down.setText((self.down.text() + "\n" + line).strip())
        elif kind == "error":
            self.down.setText((self.down.text() + "\n" + ev[1]).strip())

    def _stage(self):
        now = sorted({ch for _, ch in self.where.values() if ch})
        self.stage.setText(tf("Новых: {n}", n=self.added) + (f"  ·  {', '.join(now[:4])}" if now else ""))

    def _finished(self, task):
        self.alive.discard(task)
        if task is self.task:
            self._ended(tf("Новых: {n}", n=self.added))

    def _ended(self, text):
        self.task = None
        self.go.setText(t("Собрать"))
        self.bar.setVisible(False)
        self.stage.setText(text)
        self.win.sort.refresh_count()

    def shutdown(self):
        if self.collector is not None:
            self.collector.stop()


class LibraryPage(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(10)

        top = QHBoxLayout()
        top.setSpacing(8)
        self.path = QPushButton()
        self.path.setObjectName("field")
        self.path.setCursor(Qt.PointingHandCursor)
        self.path.clicked.connect(self.change)
        top.addWidget(self.path, 1)
        reveal = QPushButton(t(FINDER))
        reveal.clicked.connect(lambda: self._open(self.win.out_dir))
        top.addWidget(reveal)
        v.addLayout(top)

        self.tree = QTreeWidget()
        cols = [t("Канал"), *LABELS, t(UNIVERSAL), t("Очередь")]
        self.tree.setColumnCount(len(cols))
        self.tree.setHeaderLabels(cols)
        self.tree.setRootIsDecorated(False)
        self.tree.setUniformRowHeights(True)
        self.tree.setIndentation(0)
        self.tree.setFocusPolicy(Qt.NoFocus)
        h = self.tree.header()
        h.setSectionResizeMode(0, QHeaderView.Stretch)
        for i in range(1, len(cols)):
            h.setSectionResizeMode(i, QHeaderView.Fixed)
            self.tree.setColumnWidth(i, 120 if cols[i] == UNIVERSAL else 64)
            self.tree.headerItem().setTextAlignment(i, Qt.AlignCenter)
        self.tree.itemDoubleClicked.connect(self._activated)
        v.addWidget(self.tree, 1)

    def refresh(self):
        root = self.win.out_dir
        self.path.setText(str(root).replace(str(Path.home()), "~"))
        counts = {}
        if root.exists():
            for gdir in root.iterdir():
                if not gdir.is_dir():
                    continue
                for cdir in gdir.iterdir():
                    if not cdir.is_dir():
                        continue
                    row = counts.setdefault(cdir.name, {})
                    for ldir in cdir.iterdir():
                        if ldir.is_dir():
                            n = sum(1 for f in ldir.iterdir() if f.suffix.lower() == ".gif")
                            for lab in (ldir.name.split() if ldir.name != UNIVERSAL else [UNIVERSAL]):
                                row[lab] = row.get(lab, 0) + n
        waiting = self.win.store.waiting()
        self.tree.clear()
        bold = QFont(self.tree.font())
        bold.setWeight(QFont.DemiBold)
        for g in GROUPS:
            head = QTreeWidgetItem([g])
            head.setFont(0, bold)
            head.setForeground(0, tone("#8a8f98"))
            head.setFlags(Qt.ItemIsEnabled)
            self.tree.addTopLevelItem(head)
            for ch in CHANNELS:
                if ch.group != g:
                    continue
                row = counts.get(ch.name, {})
                vals = [row.get(l, 0) for l in LABELS] + [row.get(UNIVERSAL, 0), waiting.get(ch.name, 0)]
                item = QTreeWidgetItem([ch.name] + [str(x) if x else "" for x in vals])
                item.setData(0, Qt.UserRole, str(root / g / ch.name))
                for i in range(1, len(vals) + 1):
                    item.setTextAlignment(i, Qt.AlignCenter)
                item.setForeground(len(vals), tone("#75797f"))
                self.tree.addTopLevelItem(item)

    def _activated(self, item, _col):
        path = item.data(0, Qt.UserRole)
        if path:
            Path(path).mkdir(parents=True, exist_ok=True)
            self._open(Path(path))

    def _open(self, path: Path):
        path.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def change(self):
        path = QFileDialog.getExistingDirectory(self, t("Папка подборки"), str(self.win.out_dir))
        if path:
            self.win.out_dir = Path(path)
            self.win.settings.setValue("out_dir", path)
            self.refresh()


class Window(QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("root")
        self.setWindowTitle(APP)
        self.setAcceptDrops(True)
        # GIFKI_SETTINGS — для проверок: QSettings.setDefaultFormat на такой вызов
        # не действует, и без своего имени проверка пишет в настройки пользователя.
        self.settings = QSettings("local", os.environ.get("GIFKI_SETTINGS", APP))
        self.out_dir = Path(self.settings.value("out_dir", str(default_out())))
        self.store = Store()
        self.channel_file = DATA / "channels.json"
        self.channel_entries = actions.load(self.channel_file)
        self.converter = Converter()
        self.converter.done.connect(self._converted)
        self.converter.start()
        self.importer = None
        self.tasks = set()
        purge_youtube()
        g = self.settings.value("geometry")
        if g is not None:
            self.restoreGeometry(g)
        else:
            self.resize(1120, 800)
        # 600 по высоте: ноутбук 1366×768 с масштабом 125% даёт около 614 точек.
        self.setMinimumSize(980, 600)
        self.apply_theme()
        if WINDOWS:
            # На macOS значок окна берётся из бандла, а свой раздувает значок в доке.
            self.setWindowIcon(app_icon())

        v = QVBoxLayout(self)
        v.setContentsMargins(24, 20, 24, 20)
        v.setSpacing(14)
        head = QHBoxLayout()
        tabs = QFrame()
        tabs.setObjectName("segment")
        tl = QHBoxLayout(tabs)
        tl.setContentsMargins(3, 3, 3, 3)
        tl.setSpacing(3)
        self.tab_btns = []
        for n, name in enumerate(("Разбор", "Нарезка", "Сбор", "Подборка")):
            b = QPushButton(t(name))
            b.setObjectName("seg")
            b.setCheckable(True)
            b.setAutoExclusive(True)
            b.setFocusPolicy(Qt.NoFocus)
            b.setCursor(Qt.PointingHandCursor)
            b.setMinimumWidth(96)
            b.clicked.connect(lambda _=False, i=n: self.show_page(i))
            tl.addWidget(b)
            self.tab_btns.append(b)
        head.addWidget(tabs)
        head.addStretch()
        self.busy = QLabel()
        self.busy.setObjectName("dim")
        head.addWidget(self.busy)
        v.addLayout(head)

        self.pages = QStackedWidget()
        self.sort = SortPage(self)
        self.cut = CutPage(self)
        self.collect = CollectPage(self)
        self.library = LibraryPage(self)
        for p in (self.sort, self.cut, self.collect, self.library):
            self.pages.addWidget(p)
        v.addWidget(self.pages, 1)
        self.sort.toCut.connect(self._to_cut)
        self._build_menu()
        self.show_page(int(self.settings.value("page", 0)))
        self.sort.next()

    def _build_menu(self):
        if getattr(self, "menubar", None) is not None:
            self.menubar.deleteLater()
        bar = self.menubar = QMenuBar(self)
        about = QAction(tf("О программе {name}", name=APP), self)
        about.setMenuRole(QAction.AboutRole)
        about.triggered.connect(self.show_about)
        bar.addMenu(APP).addAction(about)
        view = bar.addMenu(t("Вид"))
        for title, items, now, pick in (
                (t("Язык"), (("ru", "Русский"), ("en", "English")), i18n.current(), self.set_language),
                (t("Оформление"), zip(THEMES, (t("Как в системе"), t("Светлое"), t("Тёмное"))),
                 theme(), self.set_theme)):
            sub = view.addMenu(title)
            group = QActionGroup(sub)
            for key, label in items:
                act = sub.addAction(label)
                act.setMenuRole(QAction.NoRole)
                act.setCheckable(True)
                act.setChecked(key == now)
                act.triggered.connect(lambda _=False, k=key, f=pick: f(k))
                group.addAction(act)

    def set_theme(self, name):
        QSettings("local", i18n.SETTINGS).setValue("theme", name)
        self.apply_theme()

    def apply_theme(self):
        sheet = themed(STYLE + EXTRA + (WIN_EXTRA if WINDOWS else ""))
        self.setStyleSheet(sheet)
        for d in self.findChildren(QDialog):
            d.setStyleSheet(sheet)
        for w in self.findChildren(QWidget):
            w.update()
        if hasattr(self, "library"):
            self.library.refresh()

    def set_language(self, lang):
        if lang == i18n.current():
            return
        i18n.set_current(lang)
        for w in self.findChildren(QWidget):
            for get, put in (("text", "setText"), ("toolTip", "setToolTip"),
                             ("placeholderText", "setPlaceholderText")):
                if not (hasattr(w, get) and hasattr(w, put)):
                    continue
                try:
                    cur = getattr(w, get)()
                except TypeError:
                    continue
                key = i18n.key_of(cur) if isinstance(cur, str) and cur else None
                if key:
                    getattr(w, put)(t(key))
            # Надпись, которую виджет рисует сам, а не через setText.
            if isinstance(getattr(w, "text", None), str) and i18n.key_of(w.text):
                w.text = t(i18n.key_of(w.text))
        for lab in self.findChildren(Labels):
            lab.retranslate()
        self._build_menu()
        for w in self.findChildren(QWidget):
            w.update()

    def show_about(self):
        box = QMessageBox(self)
        box.setIconPixmap(app_icon().pixmap(72, 72))
        box.setTextFormat(Qt.RichText)
        box.setText(f"<b>{APP}</b>")
        import support
        box.setInformativeText(f'<nobr>{AUTHOR} · <a href="{URL}">{SITE}</a></nobr><br><br>'
                               f'{t("Поддержать")}<br><nobr>{support.links_html()}</nobr>')
        box.setTextInteractionFlags(Qt.TextBrowserInteraction)
        # Ссылки ведёт support.follow: адрес кошелька копируется, а не открывается.
        for lab in box.findChildren(QLabel):
            lab.setOpenExternalLinks(False)
            lab.linkActivated.connect(lambda url: support.follow(url, t("Скопировано")))
        box.addButton(t("Закрыть"), QMessageBox.AcceptRole)
        box.exec()

    def show_page(self, i):
        self.tab_btns[i].setChecked(True)
        self.pages.setCurrentIndex(i)
        self.settings.setValue("page", i)
        # Видео на невидимой вкладке не играет: незачем тратить на него процессор.
        for page in (self.sort, self.cut):
            if page is not self.pages.currentWidget():
                page.view.player.pause()
        if i == 0 and self.sort.current is not None:
            self.sort.view.player.play()
        if i == 3:
            self.library.refresh()
        self.pages.currentWidget().setFocus()

    def open_out(self):
        self.out_dir.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.out_dir)))

    def channels_changed(self):
        self.collect.rebuild()
        self.sort.refresh_count()
        if self.pages.currentWidget() is self.library:
            self.library.refresh()

    def _to_cut(self, path, channel):
        self.show_page(1)
        self.cut.open(path, channel)

    def _converted(self, key, err):
        if err:
            what = t("гифка") if key[0] == "keep" else t("отрывок")
            self.busy.setText(tf("{what} не сохранился: {e}", what=what, e=err[:120]))

    def choose_files(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, t("Гифки и видео"), str(Path.home()),
            t("Гифки и видео") + " (*.gif *.mp4 *.webm *.mov *.m4v *.mkv *.avi)")
        if paths:
            self.add_files(paths)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        paths = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        if not paths:
            return
        # Одно видео на вкладку нарезки — открыть его там, остальное — в очередь.
        if self.pages.currentWidget() is self.cut and len(paths) == 1 and Path(paths[0]).is_file():
            self.cut.open(paths[0])
            return
        self.add_files(paths)

    def add_files(self, paths):
        if self.importer is not None:
            return
        files = []
        for p in map(Path, paths):
            if p.is_dir():
                files += sorted(f for f in p.rglob("*")
                                if f.suffix.lower() in MEDIA_EXT and not f.name.startswith("."))
            elif p.suffix.lower() in MEDIA_EXT:
                files.append(p)
        if not files:
            return
        fallback = self.sort.filter
        store = self.store

        def work(emit):
            for n, f in enumerate(files):
                channel, labels = fallback, ()
                for parent in list(f.parents)[:4]:
                    name = parent.name
                    if name and (name == UNIVERSAL or all(x in LABELS for x in name.split())):
                        labels = () if name == UNIVERSAL else tuple(name.split())
                        continue
                    found = actions.channel_for_folder(name)
                    if found:
                        channel = found
                        break
                if store.known(ref=str(f), source="files"):
                    continue
                try:
                    status = sources.admit(store, f, channel, "files", ref=str(f), suggest=labels, own=0)
                except Exception:
                    status = "skip"
                if status == "new":
                    emit("added",)
                if n % 10 == 0:
                    emit("progress", n, len(files))

        self.importer = Task(work)
        self.importer.event.connect(self._import_event)
        self.importer.finished.connect(self._import_done)
        self.busy.setText(tf("Добавление: {n} из {total}", n=0, total=len(files)))
        self.importer.start()

    def _import_event(self, ev):
        if ev[0] == "added":
            self.sort.added()
        elif ev[0] == "progress":
            self.busy.setText(tf("Добавление: {n} из {total}", n=ev[1], total=ev[2]))

    def _import_done(self):
        self.importer = None
        self.busy.setText("")
        self.sort.refresh_count()

    def shutdown(self) -> bool:
        """Останавливает потоки. True — если какой-то ещё жив и выходить надо жёстко."""
        self.settings.setValue("geometry", self.saveGeometry())
        self.collect.shutdown()
        self.cut.frames.stop()
        self.converter.flush()
        self.converter.q.put(None)
        self.converter.wait(3000)
        alive = [t for t in (*self.collect.alive, self.importer) if t is not None and t.isRunning()]
        return bool(alive)

    def closeEvent(self, e):
        self.sort.view.player.stop()
        self.cut.view.player.stop()
        super().closeEvent(e)


def _windows_shell(w):
    """Тёмная полоса заголовка: системная светлая над тёмным окном режет глаз."""
    import ctypes
    try:
        on = ctypes.c_int(1)
        # 20 — DWMWA_USE_IMMERSIVE_DARK_MODE, Windows 10 20H1 и новее.
        ctypes.windll.dwmapi.DwmSetWindowAttribute(int(w.winId()), 20, ctypes.byref(on),
                                                   ctypes.sizeof(on))
    except (AttributeError, OSError):
        pass


def _windows_log():
    """Без консоли у pythonw stdout и stderr пусты: падение при запуске пропало бы
    без следа. На маке журнал ведёт оболочка запуска, здесь — сами."""
    import faulthandler
    from store import DATA
    DATA.mkdir(parents=True, exist_ok=True)
    path = DATA / "Gifki.log"
    if path.exists() and path.stat().st_size > 5_000_000:
        path.unlink()
    log = open(path, "a", encoding="utf-8", buffering=1)
    log.write(f"=== запуск {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
    sys.stdout = sys.stderr = log
    faulthandler.enable(log)


def _proxy_env():
    """Плеер Qt и ffmpeg берут прокси только из переменных окружения, а у
    приложения, запущенного из Finder, их нет. Переносим системные."""
    import urllib.request
    found = urllib.request.getproxies()
    for scheme in ("http", "https"):
        if found.get(scheme):
            os.environ.setdefault(f"{scheme}_proxy", found[scheme])
    # Местный посредник плеера — мимо прокси. В системных исключениях macOS
    # 127.0.0.1 обычно нет, и запрос к посреднику уходил наружу и обрывался.
    skip = [x for x in (os.environ.get("no_proxy") or found.get("no") or "").split(",") if x.strip()]
    os.environ["no_proxy"] = ",".join(dict.fromkeys(skip + ["localhost", "127.0.0.1", "::1"]))


def main():
    _proxy_env()
    if WINDOWS:
        _windows_log()
        import ctypes
        # Иначе панель задач считает окно питоном и показывает его значок.
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("DrTonix.Gifki")
    app = QApplication(sys.argv)
    app.setApplicationName(APP)
    app.setApplicationDisplayName(APP)
    w = Window()
    w.show()
    if WINDOWS:
        _windows_shell(w)
    code = app.exec()
    w.shutdown()
    w.settings.sync()
    # Брошенные сборщиком потоки могут висеть в рукопожатии с сервером: обычный
    # выход ждал бы их, а живой QThread при выходе роняет процесс. База пишется
    # сразу, кодирование дождались в shutdown — выходим жёстко.
    os._exit(code or 0)


if __name__ == "__main__":
    main()
