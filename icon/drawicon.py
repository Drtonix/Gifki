"""Значок: стопка карточек с гифкой на розовом — разбор по одной.

Рисуем в край — macOS обрежет по своей маске. Всё на сетке с шагом 16,
поэтому фигура читается и в 32 точки, и в 1024.
"""
import sys
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QBrush, QColor, QGuiApplication, QImage, QLinearGradient,
                           QPainter, QPainterPath, QPolygonF, QTransform)

S = 1024
U = 16
TOP, LOW = QColor("#f39ec0"), QColor("#e46f9e")
CARD, BACK, PLAY = QColor("#f7f4f6"), QColor(255, 255, 255, 120), QColor("#e06a98")


def rounded(rect, radius):
    path = QPainterPath()
    path.addRoundedRect(rect, radius, radius)
    return path


def draw(path, layer=False):
    """layer=True — только карточки на прозрачном фоне: подложку и тень macOS
    рисует сама, по своим правилам для светлой и тёмной темы."""
    QGuiApplication.instance() or QGuiApplication([])
    img = QImage(S, S, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)

    if not layer:
        back = QLinearGradient(0, 0, 0, S)
        back.setColorAt(0.0, TOP)
        back.setColorAt(1.0, LOW)
        p.fillRect(QRectF(0, 0, S, S), QBrush(back))

    card = QRectF(15 * U, 12 * U, 34 * U, 40 * U)
    radius = 4 * U
    c = card.center()

    # Задняя карточка — повёрнута, полупрозрачная: следующая в очереди.
    turn = QTransform().translate(c.x(), c.y()).rotate(-12).translate(-c.x(), -c.y())
    p.setPen(Qt.NoPen)
    p.setBrush(BACK)
    p.drawPath(turn.map(rounded(card.translated(-3 * U, 1 * U), radius)))

    if not layer:
        for step in range(1, 7):
            p.setBrush(QColor(0, 0, 0, 12))
            p.drawPath(rounded(card.adjusted(-step * 2, step * 3, step * 2, step * 4),
                               radius + step * 2))

    p.setBrush(CARD)
    p.drawPath(rounded(card, radius))

    # Знак воспроизведения: оптический центр треугольника правее геометрического.
    h = 14 * U
    tri = QPolygonF([QPointF(c.x() - h * 0.38, c.y() - h / 2),
                     QPointF(c.x() - h * 0.38, c.y() + h / 2),
                     QPointF(c.x() + h * 0.5, c.y())])
    shape = QPainterPath()
    shape.addPolygon(tri)
    p.setBrush(PLAY)
    p.setPen(Qt.NoPen)
    p.drawPath(shape)
    p.end()
    img.save(path)


if __name__ == "__main__":
    draw(sys.argv[1] if len(sys.argv) > 1 else "icon/AppIcon-1024.png",
         len(sys.argv) > 2 and sys.argv[2] == "layer")
