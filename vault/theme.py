from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QBrush, QColor, QFont, QFontMetrics, QLinearGradient, QPainter, QPainterPath,
                           QPen, QPixmap)

from .models import Doc, format_number, mask_number


class Theme:
    dark = True
    bg = "#0E0E10"
    panel = "#17171A"
    surface = "#1F1F23"
    border = "#2C2C32"
    text = "#F2F2F4"
    muted = "#9A9AA2"
    accent = "#2DD4BF"
    on_accent = "#04201C"

    def set(self, dark: bool) -> None:
        self.dark = dark
        if dark:
            self.bg, self.panel, self.surface, self.border = "#0E0E10", "#17171A", "#1F1F23", "#2C2C32"
            self.text, self.muted, self.accent, self.on_accent = "#F2F2F4", "#9A9AA2", "#2DD4BF", "#04201C"
        else:
            self.bg, self.panel, self.surface, self.border = "#F4F5F7", "#FFFFFF", "#E9EBEF", "#D6D9DF"
            self.text, self.muted, self.accent, self.on_accent = "#15161A", "#5F6368", "#0F766E", "#FFFFFF"

    def qss(self) -> str:
        t = self
        return f"""
* {{ font-family: "Segoe UI", "Inter", "Noto Sans", sans-serif; font-size: 13px; }}
QMainWindow, QDialog, QWidget#root {{ background: {t.bg}; color: {t.text}; }}
QWidget {{ color: {t.text}; }}
QLabel {{ background: transparent; }}
QToolBar {{ background: {t.panel}; border: none; border-bottom: 1px solid {t.border}; spacing: 6px; padding: 6px 10px; }}
QToolButton {{ background: transparent; border: 1px solid transparent; border-radius: 8px; padding: 6px 12px; color: {t.text}; }}
QToolButton:hover {{ background: {t.surface}; }}
QToolButton:checked {{ background: {t.surface}; border-color: {t.accent}; }}
QToolButton::menu-indicator {{ image: none; }}
QPushButton {{ background: {t.surface}; border: 1px solid {t.border}; border-radius: 8px; padding: 7px 16px; color: {t.text}; }}
QPushButton:hover {{ border-color: {t.accent}; }}
QPushButton:disabled {{ color: {t.muted}; }}
QPushButton#primary {{ background: {t.accent}; color: {t.on_accent}; border: none; font-weight: 600; }}
QPushButton#primary:disabled {{ background: {t.surface}; color: {t.muted}; }}
QPushButton#danger {{ color: #FF6B6B; }}
QLineEdit, QComboBox, QSpinBox {{ background: {t.panel}; border: 1px solid {t.border}; border-radius: 8px; padding: 7px 10px; color: {t.text}; selection-background-color: {t.accent}; selection-color: {t.on_accent}; }}
QLineEdit:focus, QComboBox:focus {{ border-color: {t.accent}; }}
QComboBox QAbstractItemView {{ background: {t.panel}; color: {t.text}; border: 1px solid {t.border}; selection-background-color: {t.accent}; selection-color: {t.on_accent}; }}
QListWidget#sidebar {{ background: {t.panel}; border: none; border-right: 1px solid {t.border}; padding: 8px 6px; outline: 0; }}
QListWidget#sidebar::item {{ padding: 8px 12px; border-radius: 8px; margin: 1px 0; color: {t.text}; }}
QListWidget#sidebar::item:hover {{ background: {t.surface}; }}
QListWidget#sidebar::item:selected {{ background: {t.accent}; color: {t.on_accent}; }}
QListView, QTreeWidget, QTableWidget {{ background: {t.bg}; border: none; outline: 0; color: {t.text}; }}
QTreeWidget::item {{ padding: 6px 4px; }}
QTreeWidget::item:selected {{ background: {t.accent}; color: {t.on_accent}; }}
QTreeWidget::item:hover:!selected {{ background: {t.surface}; }}
QHeaderView::section {{ background: {t.panel}; color: {t.muted}; border: none; border-bottom: 1px solid {t.border}; padding: 8px 6px; font-weight: 600; }}
QScrollArea {{ background: {t.bg}; border: none; }}
QScrollBar:vertical {{ background: transparent; width: 12px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {t.border}; border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {t.muted}; }}
QScrollBar:horizontal {{ background: transparent; height: 12px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {t.border}; border-radius: 4px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QStatusBar {{ background: {t.panel}; color: {t.muted}; border-top: 1px solid {t.border}; }}
QMenu {{ background: {t.panel}; color: {t.text}; border: 1px solid {t.border}; padding: 6px; }}
QMenu::item {{ padding: 7px 26px 7px 14px; border-radius: 6px; }}
QMenu::item:selected {{ background: {t.accent}; color: {t.on_accent}; }}
QMenu::separator {{ height: 1px; background: {t.border}; margin: 5px 8px; }}
QCheckBox {{ spacing: 8px; }}
QToolTip {{ background: {t.panel}; color: {t.text}; border: 1px solid {t.border}; }}
QMessageBox {{ background: {t.bg}; }}
"""


THEME = Theme()


def _font(px: float, weight=QFont.Normal) -> QFont:
    f = QFont("Segoe UI")
    f.setPixelSize(max(8, int(px)))
    f.setWeight(weight)
    return f


def gradient_for(rect: QRectF, doc: Doc) -> QLinearGradient:
    cols = [QColor(c) for c in doc.colors_hex()]
    g = QLinearGradient(rect.topLeft(), rect.bottomRight())
    n = len(cols)
    for i, c in enumerate(cols):
        g.setColorAt(0.0 if n == 1 else i / (n - 1), c)
    return g


def _text_shadowed(p: QPainter, x: float, y: float, text: str, color=QColor(255, 255, 255)) -> None:
    p.setPen(QColor(0, 0, 0, 95))
    p.drawText(QPointF(x + 0.5, y + 1.8), text)
    p.setPen(color)
    p.drawText(QPointF(x, y), text)


def paint_card(p: QPainter, r: QRectF, doc: Doc, *, reveal: bool = False, hover: float = 0.0,
               selected: bool = False, badge: int | None = None, opacity: float = 1.0,
               shadow: bool = True) -> None:
    """The gradient 'wallet' card used by every card view."""
    p.save()
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.TextAntialiasing)
    p.setOpacity(opacity)
    s = max(0.7, min(1.7, r.height() / 190.0))
    radius = 22 * s
    cols = [QColor(c) for c in doc.colors_hex()]

    if shadow:
        glow = QColor(cols[-1])
        p.setPen(Qt.NoPen)
        for i in range(9, 0, -1):
            glow.setAlpha(int((7 + 9 * hover) * (1 - i / 10.0)) + 1)
            p.setBrush(glow)
            p.drawRoundedRect(r.adjusted(-i * 1.2, -i * 0.3 + 3, i * 1.2, i * 1.8 + 2), radius + i, radius + i)

    path = QPainterPath()
    path.addRoundedRect(r, radius, radius)
    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(gradient_for(r, doc)))
    p.drawPath(path)

    p.save()
    p.setClipPath(path)
    p.setBrush(QColor(255, 255, 255, 18))
    p.drawEllipse(QPointF(r.right() - r.width() * 0.05, r.bottom() - r.height() * 0.1), r.height() * 0.8, r.height() * 0.8)
    p.setBrush(QColor(255, 255, 255, 15))
    p.drawEllipse(QPointF(r.right() - r.width() * 0.15, r.bottom() - r.height() * 0.25), r.height() * 0.5, r.height() * 0.5)
    sheen = QLinearGradient(r.topLeft(), r.bottomRight())
    sheen.setColorAt(0.0, QColor(255, 255, 255, 80))
    sheen.setColorAt(0.45, QColor(255, 255, 255, 0))
    sheen.setColorAt(1.0, QColor(0, 0, 0, 52))
    p.setBrush(QBrush(sheen))
    p.drawPath(path)
    p.restore()

    rim = QLinearGradient(r.topLeft(), r.bottomLeft())
    rim.setColorAt(0, QColor(255, 255, 255, 140))
    rim.setColorAt(1, QColor(255, 255, 255, 14))
    p.setBrush(Qt.NoBrush)
    p.setPen(QPen(QBrush(rim), 1.3))
    p.drawPath(path)
    if selected:
        p.setPen(QPen(QColor(THEME.accent), 3))
        p.drawRoundedRect(r.adjusted(-2.5, -2.5, 2.5, 2.5), radius + 2, radius + 2)

    # text
    pad = 22 * s
    title_font = _font(18 * s, QFont.Bold)
    label_font = _font(14 * s, QFont.DemiBold)
    right_w = 0.0
    p.setFont(label_font)
    lm = QFontMetrics(label_font)
    if badge is not None:
        d = 28 * s
        br = QRectF(r.right() - pad - d, r.top() + 14 * s, d, d)
        right_w = d + 10 * s
        if badge > 0:
            p.setBrush(QColor("white"))
            p.setPen(Qt.NoPen)
            p.drawEllipse(br)
            p.setPen(QColor("#111111"))
            p.setFont(_font(14 * s, QFont.Bold))
            p.drawText(br, Qt.AlignCenter, str(badge))
        else:
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(QColor("white"), 2))
            p.drawEllipse(br.adjusted(1, 1, -1, -1))
    elif doc.title != doc.type_label:
        lw = lm.horizontalAdvance(doc.type_label)
        right_w = lw + 10 * s
        _text_shadowed(p, r.right() - pad - lw, r.top() + 16 * s + lm.ascent(), doc.type_label, QColor(255, 255, 255, 230))

    p.setFont(title_font)
    tm = QFontMetrics(title_font)
    title = tm.elidedText(doc.title, Qt.ElideRight, int(r.width() - 2 * pad - right_w))
    _text_shadowed(p, r.left() + pad, r.top() + 14 * s + tm.ascent(), title)

    num = format_number(doc.number) if reveal else mask_number(doc.number)
    if num:
        nf = _font((26 if reveal else 20) * s, QFont.Medium)
        nf.setLetterSpacing(QFont.AbsoluteSpacing, 2)
        p.setFont(nf)
        _text_shadowed(p, r.left() + pad, r.bottom() - 20 * s, num)

    # little "PDF" mark
    p.setPen(QPen(QColor(255, 255, 255, 215), 1.6))
    p.setBrush(Qt.NoBrush)
    mw, mh = 30 * s, 22 * s
    mr = QRectF(r.right() - pad - mw + 4 * s, r.bottom() - 18 * s - mh, mw, mh)
    p.drawRoundedRect(mr, 4 * s, 4 * s)
    p.setFont(_font(10 * s, QFont.Bold))
    p.drawText(mr, Qt.AlignCenter, "PDF")
    p.restore()


def chip_pixmap(doc: Doc, w: int = 44, h: int = 30, radius: int = 8) -> QPixmap:
    pm = QPixmap(w, h)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    r = QRectF(0, 0, w, h)
    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(gradient_for(r, doc)))
    p.drawRoundedRect(r, radius, radius)
    p.end()
    return pm
