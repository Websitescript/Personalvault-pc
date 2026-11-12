"""The six ways to look at the documents: Card stack, Cards, List, Tiles, Large icons, Details."""
from __future__ import annotations

import math
import os
from datetime import datetime

from PySide6.QtCore import (QElapsedTimer, QItemSelection, QItemSelectionModel, QPoint, QPointF, QRectF, QSize, Qt,
                            QTimer, Signal)
from PySide6.QtGui import (QBrush, QColor, QFont, QFontMetrics, QIcon, QPainter, QPainterPath, QPen, QPixmap,
                           QStandardItem, QStandardItemModel)
from PySide6.QtWidgets import (QAbstractItemView, QHeaderView, QListView, QScrollArea, QStyle, QStyledItemDelegate,
                               QTreeWidget, QTreeWidgetItem, QWidget)

from . import pdfutil
from .models import Doc, format_number, mask_number
from .theme import THEME, chip_pixmap, gradient_for, paint_card

VIEW_MODES = [
    ("stack", "Card stack"),
    ("grid", "Cards"),
    ("list", "List"),
    ("tiles", "Tiles"),
    ("thumbs", "Large icons"),
    ("details", "Details"),
]

CARD_H = 190
STACK_STEP = 92
GRID_W, GRID_H, GAP = 330, 190, 24


class ThumbCache:
    def __init__(self, store):
        self.store = store
        self.mem: dict = {}

    def get(self, doc: Doc):
        key = (doc.file_name, doc.password)
        if key in self.mem:
            return self.mem[key]
        pm = None
        disk = self.store.thumb_dir / (doc.file_name + ".png")
        try:
            if disk.exists():
                pm = QPixmap(str(disk))
            else:
                img = pdfutil.thumbnail(self.store.path_of(doc), doc.password, 360)
                if img is not None:
                    img.save(str(disk))
                    pm = QPixmap.fromImage(img)
        except Exception:
            pm = None
        if pm is not None and pm.isNull():
            pm = None
        self.mem[key] = pm
        return pm

    def invalidate(self, file_name: str) -> None:
        for k in [k for k in self.mem if k[0] == file_name]:
            del self.mem[k]
        try:
            (self.store.thumb_dir / (file_name + ".png")).unlink()
        except OSError:
            pass


class ViewHost:
    """What the views need from the main window."""
    def __init__(self, store, thumbs, show_numbers):
        self.store, self.thumbs, self.show_numbers = store, thumbs, show_numbers


def _num_text(host: ViewHost, d: Doc) -> str:
    if not d.number:
        return ""
    return format_number(d.number) if host.show_numbers() else mask_number(d.number)


# ======================================================================
# Card views (custom painted)
# ======================================================================
class CardsCanvas(QWidget):
    selectionChanged = Signal(list)
    opened = Signal(str)
    menuRequested = Signal(str, QPoint)
    reordered = Signal(list)
    keyAction = Signal(str)

    def __init__(self, mode: str, parent=None):
        super().__init__(parent)
        self.mode = mode
        self.docs: list[Doc] = []
        self.sel: list[str] = []
        self.anchor = -1
        self.hover = -1
        self.hv: list[float] = []
        self.press_idx = -1
        self.press_pos = QPointF()
        self.dragging = False
        self.drag_pos = QPointF()
        self.drag_off = QPointF()
        self.drag_target = -1
        self.scroll: QScrollArea | None = None
        self.t0 = QElapsedTimer()
        self.t0.start()
        self.timer = QTimer(self)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self._tick)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)

    # ---- geometry ----
    def _cols(self) -> int:
        return max(1, int((max(self.width(), 200) - 48 + GAP) // (GRID_W + GAP)))

    def _slot(self, k: int) -> QRectF:
        W = max(self.width(), 200)
        if self.mode == "stack":
            cw = min(640, W - 48)
            return QRectF((W - cw) / 2, 18 + k * STACK_STEP, cw, CARD_H)
        cols = self._cols()
        gw = cols * GRID_W + (cols - 1) * GAP
        x0 = (W - gw) / 2
        return QRectF(x0 + (k % cols) * (GRID_W + GAP), 24 + (k // cols) * (GRID_H + GAP), GRID_W, GRID_H)

    def _content_height(self) -> int:
        n = len(self.docs)
        if self.mode == "stack":
            return 18 + max(0, n - 1) * STACK_STEP + CARD_H + 28
        rows = math.ceil(n / self._cols()) if n else 0
        return 24 + rows * (GRID_H + GAP) + 8

    def _relayout(self) -> None:
        self.setMinimumHeight(self._content_height())
        self.update()

    def resizeEvent(self, e):
        self._relayout()
        super().resizeEvent(e)

    def _order(self) -> list[int]:
        order = list(range(len(self.docs)))
        if self.dragging and self.drag_target >= 0 and self.drag_target != self.press_idx:
            order.remove(self.press_idx)
            order.insert(self.drag_target, self.press_idx)
        return order

    def _hit(self, pos: QPointF) -> int:
        order = self._order()
        for k in reversed(range(len(order))):
            if self._slot(k).contains(pos):
                return order[k]
        return -1

    # ---- data ----
    def set_docs(self, docs: list[Doc], replay: bool = False) -> None:
        self.docs = list(docs)
        self.hv = [0.0] * len(docs)
        ids = {d.id for d in docs}
        self.sel = [i for i in self.sel if i in ids]
        self.hover = -1
        if replay:
            self.t0.restart()
        self._relayout()
        self.timer.start()

    def set_selected(self, ids: list[str]) -> None:
        self.sel = [i for i in ids if any(d.id == i for d in self.docs)]
        self.update()
        self.timer.start()

    # ---- animation ----
    def _tick(self) -> None:
        moving = False
        for i, d in enumerate(self.docs):
            target = 1.0 if i == self.hover else (0.65 if d.id in self.sel else 0.0)
            cur = self.hv[i]
            if abs(cur - target) > 0.01:
                self.hv[i] = cur + (target - cur) * 0.28
                moving = True
            else:
                self.hv[i] = target
        entering = self.t0.elapsed() < len(self.docs) * 55 + 420
        self.update()
        if not moving and not entering and not self.dragging:
            self.timer.stop()

    # ---- painting ----
    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(THEME.bg))
        order = self._order()
        elapsed = self.t0.elapsed()
        lift_px = 8 if self.mode == "stack" else 6
        multi = len(self.sel) > 1
        for k, di in enumerate(order):
            if self.dragging and di == self.press_idx:
                continue
            d = self.docs[di]
            r = self._slot(k)
            ap = max(0.0, min(1.0, (elapsed - di * 55) / 380.0))
            ap = 1 - (1 - ap) ** 3
            r = r.translated(0, -self.hv[di] * lift_px + (1 - ap) * 50)
            badge = self.sel.index(d.id) + 1 if multi and d.id in self.sel else None
            paint_card(p, r, d, hover=self.hv[di], selected=d.id in self.sel, badge=badge, opacity=ap)
        if self.dragging and 0 <= self.press_idx < len(self.docs):
            base = self._slot(0)
            r = QRectF(self.drag_pos.x() - self.drag_off.x(), self.drag_pos.y() - self.drag_off.y(),
                       base.width(), base.height())
            paint_card(p, r, self.docs[self.press_idx], hover=1.0, selected=True, opacity=0.93)

    # ---- mouse ----
    def mousePressEvent(self, e) -> None:
        self.setFocus()
        pos = e.position()
        idx = self._hit(pos)
        if e.button() == Qt.RightButton:
            if idx >= 0:
                if self.docs[idx].id not in self.sel:
                    self.sel = [self.docs[idx].id]
                    self.selectionChanged.emit(list(self.sel))
                    self.update()
                self.menuRequested.emit(self.docs[idx].id, e.globalPosition().toPoint())
            return
        if e.button() == Qt.LeftButton:
            self.press_idx, self.press_pos = idx, pos
            if idx < 0 and not (e.modifiers() & Qt.ControlModifier):
                self.sel = []
                self.selectionChanged.emit([])
                self.update()

    def mouseMoveEvent(self, e) -> None:
        pos = e.position()
        if (e.buttons() & Qt.LeftButton) and self.press_idx >= 0:
            if not self.dragging and (pos - self.press_pos).manhattanLength() > 12:
                self.dragging = True
                self.drag_off = self.press_pos - self._slot(self.press_idx).topLeft()
                self.timer.start()
            if self.dragging:
                self.drag_pos = pos
                self.drag_target = self._target_slot(pos)
                self.setCursor(Qt.ClosedHandCursor)
                self.update()
                return
        h = self._hit(pos)
        if h != self.hover:
            self.hover = h
            self.setCursor(Qt.PointingHandCursor if h >= 0 else Qt.ArrowCursor)
            self.timer.start()

    def _target_slot(self, pos: QPointF) -> int:
        n = len(self.docs)
        c = QPointF(pos.x() - self.drag_off.x(), pos.y() - self.drag_off.y())
        base = self._slot(0)
        c = QPointF(c.x() + base.width() / 2, c.y() + base.height() / 2)
        if self.mode == "stack":
            k = int((c.y() - 18) // STACK_STEP)
        else:
            cols = self._cols()
            x0 = self._slot(0).x()
            col = max(0, min(cols - 1, int((c.x() - x0) // (GRID_W + GAP))))
            row = max(0, int((c.y() - 24) // (GRID_H + GAP)))
            k = row * cols + col
        return max(0, min(n - 1, k))

    def mouseReleaseEvent(self, e) -> None:
        if e.button() != Qt.LeftButton:
            return
        if self.dragging:
            self.dragging = False
            self.unsetCursor()
            if self.drag_target >= 0 and self.drag_target != self.press_idx:
                ids = [self.docs[i].id for i in self._order_for_drop()]
                self.press_idx = -1
                self.reordered.emit(ids)
            self.press_idx = -1
            self.drag_target = -1
            self.update()
            return
        idx = self._hit(e.position())
        if idx >= 0 and idx == self.press_idx:
            self._click(idx, e.modifiers())
        self.press_idx = -1

    def _order_for_drop(self) -> list[int]:
        order = list(range(len(self.docs)))
        order.remove(self.press_idx)
        order.insert(self.drag_target, self.press_idx)
        return order

    def _click(self, idx: int, mods) -> None:
        did = self.docs[idx].id
        if mods & Qt.ControlModifier:
            if did in self.sel:
                self.sel.remove(did)
            else:
                self.sel.append(did)
            self.anchor = idx
        elif (mods & Qt.ShiftModifier) and self.anchor >= 0:
            a, b = sorted((self.anchor, idx))
            self.sel = [self.docs[i].id for i in range(a, b + 1)]
        else:
            self.sel = [did]
            self.anchor = idx
        self.selectionChanged.emit(list(self.sel))
        self.timer.start()
        self.update()

    def mouseDoubleClickEvent(self, e) -> None:
        idx = self._hit(e.position())
        if idx >= 0 and e.button() == Qt.LeftButton:
            self.opened.emit(self.docs[idx].id)

    def leaveEvent(self, _e) -> None:
        self.hover = -1
        self.timer.start()

    # ---- keyboard ----
    def keyPressEvent(self, e) -> None:
        n = len(self.docs)
        if not n:
            return
        cur = next((i for i, d in enumerate(self.docs) if self.sel and d.id == self.sel[-1]), -1)
        cols = self._cols() if self.mode == "grid" else 1
        step = {Qt.Key_Down: cols, Qt.Key_Up: -cols, Qt.Key_Right: 1 if self.mode == "grid" else cols,
                Qt.Key_Left: -1 if self.mode == "grid" else -cols}.get(e.key())
        if step is not None:
            nxt = max(0, min(n - 1, (cur if cur >= 0 else (0 if step > 0 else n - 1)) + (step if cur >= 0 else 0)))
            self.sel = [self.docs[nxt].id]
            self.anchor = nxt
            self.selectionChanged.emit(list(self.sel))
            if self.scroll:
                r = self._slot(nxt)
                self.scroll.ensureVisible(int(r.center().x()), int(r.center().y()), 40, int(r.height() / 2) + 24)
            self.timer.start()
            self.update()
        elif e.key() in (Qt.Key_Return, Qt.Key_Enter):
            self.keyAction.emit("open")
        elif e.key() == Qt.Key_Space:
            self.keyAction.emit("reveal")
        elif e.key() == Qt.Key_Delete:
            self.keyAction.emit("delete")
        elif e.key() == Qt.Key_A and (e.modifiers() & Qt.ControlModifier):
            self.sel = [d.id for d in self.docs]
            self.selectionChanged.emit(list(self.sel))
            self.update()
        else:
            super().keyPressEvent(e)


class CardsView(QScrollArea):
    selectionChanged = Signal(list)
    opened = Signal(str)
    menuRequested = Signal(str, QPoint)
    reordered = Signal(list)
    keyAction = Signal(str)

    def __init__(self, mode: str, host: ViewHost, parent=None):
        super().__init__(parent)
        self.canvas = CardsCanvas(mode)
        self.canvas.scroll = self
        self.setWidget(self.canvas)
        self.setWidgetResizable(True)
        self.setFrameShape(QScrollArea.NoFrame)
        for name in ("selectionChanged", "opened", "menuRequested", "reordered", "keyAction"):
            getattr(self.canvas, name).connect(getattr(self, name))

    def set_docs(self, docs, replay=False):
        self.canvas.set_docs(docs, replay)

    def set_selected(self, ids):
        self.canvas.set_selected(ids)

    def refresh_look(self):
        self.canvas.update()


# ======================================================================
# List / Tiles / Large icons  (Explorer-style)
# ======================================================================
def _draw_page(p: QPainter, rect: QRectF, doc: Doc, pm: QPixmap | None) -> None:
    p.save()
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    if pm is not None:
        scaled = pm.scaled(int(rect.width()), int(rect.height()), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        w, h = scaled.width(), scaled.height()
        pr = QRectF(rect.x() + (rect.width() - w) / 2, rect.y() + (rect.height() - h) / 2, w, h)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 40))
        p.drawRoundedRect(pr.adjusted(1, 2, 1, 3), 4, 4)
        path = QPainterPath()
        path.addRoundedRect(pr, 4, 4)
        p.setClipPath(path)
        p.drawPixmap(pr.toRect(), scaled)
        p.setClipping(False)
        p.setPen(QPen(QColor(0, 0, 0, 50), 1))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(pr, 4, 4)
    else:
        path = QPainterPath()
        path.addRoundedRect(rect, 10, 10)
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(gradient_for(rect, doc)))
        p.drawPath(path)
        p.setPen(QColor(255, 255, 255, 230))
        f = QFont("Segoe UI")
        f.setPixelSize(max(10, int(rect.height() * 0.16)))
        f.setBold(True)
        p.setFont(f)
        p.drawText(rect, Qt.AlignCenter, "PDF\nLOCKED" if doc.password == "" else "PDF")
    p.restore()


class DocDelegate(QStyledItemDelegate):
    def __init__(self, view: "ItemsView", mode: str):
        super().__init__(view)
        self.view, self.mode = view, mode

    def sizeHint(self, option, index) -> QSize:
        return {"list": QSize(200, 64), "tiles": QSize(310, 100), "thumbs": QSize(196, 256)}[self.mode]

    def paint(self, p: QPainter, option, index) -> None:
        d = self.view.host.store.by_id(index.data(Qt.UserRole))
        if d is None:
            return
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(option.rect).adjusted(3, 2, -3, -2)
        selected = bool(option.state & QStyle.State_Selected)
        hovered = bool(option.state & QStyle.State_MouseOver)
        if selected:
            bg = QColor(THEME.accent)
            bg.setAlpha(70 if THEME.dark else 55)
            p.setBrush(bg)
            p.setPen(QPen(QColor(THEME.accent), 1.5))
        elif hovered:
            p.setBrush(QColor(THEME.surface))
            p.setPen(Qt.NoPen)
        else:
            p.setBrush(Qt.NoBrush)
            p.setPen(Qt.NoPen)
        p.drawRoundedRect(r, 12, 12)

        text, muted = QColor(THEME.text), QColor(THEME.muted)
        num = _num_text(self.view.host, d)
        f = QFont("Segoe UI")

        if self.mode == "list":
            p.drawPixmap(int(r.x() + 12), int(r.center().y() - 15), chip_pixmap(d, 52, 34, 9))
            f.setPixelSize(15); f.setBold(True); p.setFont(f); p.setPen(text)
            p.drawText(QPointF(r.x() + 78, r.center().y() - 3), d.title)
            f.setPixelSize(12); f.setBold(False); p.setFont(f); p.setPen(muted)
            sub = d.type_label + (("   •   " + num) if num else "")
            p.drawText(QPointF(r.x() + 78, r.center().y() + 15), sub)
            added = datetime.fromtimestamp(d.added).strftime("%d %b %Y")
            fm = QFontMetrics(f)
            p.drawText(QPointF(r.right() - 14 - fm.horizontalAdvance(added), r.center().y() + 5), added)

        elif self.mode == "tiles":
            pm = self.view.host.thumbs.get(d)
            _draw_page(p, QRectF(r.x() + 12, r.y() + 10, 62, r.height() - 20), d, pm)
            x = r.x() + 88
            f.setPixelSize(15); f.setBold(True); p.setFont(f); p.setPen(text)
            fm = QFontMetrics(f)
            p.drawText(QPointF(x, r.y() + 34), fm.elidedText(d.title, Qt.ElideRight, int(r.right() - x - 10)))
            f.setPixelSize(12); f.setBold(False); p.setFont(f); p.setPen(muted)
            p.drawText(QPointF(x, r.y() + 55), d.type_label)
            if num:
                p.drawText(QPointF(x, r.y() + 74), num)

        else:  # thumbs
            pm = self.view.host.thumbs.get(d)
            _draw_page(p, QRectF(r.x() + 14, r.y() + 12, r.width() - 28, r.height() - 76), d, pm)
            f.setPixelSize(14); f.setBold(True); p.setFont(f); p.setPen(text)
            fm = QFontMetrics(f)
            p.drawText(QRectF(r.x() + 8, r.bottom() - 58, r.width() - 16, 22), Qt.AlignCenter,
                       fm.elidedText(d.title, Qt.ElideRight, int(r.width() - 20)))
            f.setPixelSize(12); f.setBold(False); p.setFont(f); p.setPen(muted)
            p.drawText(QRectF(r.x() + 8, r.bottom() - 36, r.width() - 16, 20), Qt.AlignCenter, d.type_label)
        p.restore()


class ItemsView(QListView):
    selectionChanged = Signal(list)
    opened = Signal(str)
    menuRequested = Signal(str, QPoint)
    reordered = Signal(list)
    keyAction = Signal(str)

    def __init__(self, mode: str, host: ViewHost, parent=None):
        super().__init__(parent)
        self.mode, self.host = mode, host
        self.model_ = QStandardItemModel(self)
        self.setModel(self.model_)
        self.setItemDelegate(DocDelegate(self, mode))
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setMouseTracking(True)
        self.setFrameShape(QListView.NoFrame)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        if mode == "list":
            self.setViewMode(QListView.ListMode)
            self.setUniformItemSizes(True)
            self.setSpacing(2)
        else:
            self.setViewMode(QListView.IconMode)
            self.setResizeMode(QListView.Adjust)
            self.setMovement(QListView.Static)
            self.setWrapping(True)
            self.setSpacing(8)
            self.setUniformItemSizes(True)
        self.customContextMenuRequested.connect(self._menu)
        self.doubleClicked.connect(lambda i: self.opened.emit(i.data(Qt.UserRole)))
        self.selectionModel().selectionChanged.connect(self._sel)
        self._quiet = False

    def set_docs(self, docs, replay=False):
        keep = self.selected_ids()
        self._quiet = True
        self.model_.clear()
        for d in docs:
            it = QStandardItem(d.title)
            it.setData(d.id, Qt.UserRole)
            it.setEditable(False)
            self.model_.appendRow(it)
        self._quiet = False
        self.set_selected(keep)

    def selected_ids(self) -> list[str]:
        rows = sorted(i.row() for i in self.selectionModel().selectedIndexes())
        return [self.model_.item(r).data(Qt.UserRole) for r in rows]

    def set_selected(self, ids):
        self._quiet = True
        sm = self.selectionModel()
        sm.clearSelection()
        sel = QItemSelection()
        for r in range(self.model_.rowCount()):
            if self.model_.item(r).data(Qt.UserRole) in ids:
                ix = self.model_.index(r, 0)
                sel.select(ix, ix)
        sm.select(sel, QItemSelectionModel.ClearAndSelect)
        self._quiet = False

    def refresh_look(self):
        self.viewport().update()

    def _sel(self, *_):
        if not self._quiet:
            self.selectionChanged.emit(self.selected_ids())

    def _menu(self, pos):
        ix = self.indexAt(pos)
        if ix.isValid():
            did = ix.data(Qt.UserRole)
            if did not in self.selected_ids():
                self.set_selected([did])
                self.selectionChanged.emit([did])
            self.menuRequested.emit(did, self.viewport().mapToGlobal(pos))

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Return, Qt.Key_Enter):
            self.keyAction.emit("open")
        elif e.key() == Qt.Key_Space:
            self.keyAction.emit("reveal")
        elif e.key() == Qt.Key_Delete:
            self.keyAction.emit("delete")
        else:
            super().keyPressEvent(e)


# ======================================================================
# Details (sortable table)
# ======================================================================
class _Item(QTreeWidgetItem):
    def __init__(self, texts, keys):
        super().__init__(texts)
        self.keys = keys

    def __lt__(self, other):
        c = self.treeWidget().sortColumn()
        return self.keys[c] < other.keys[c]


def human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return ""


class DetailsView(QTreeWidget):
    selectionChanged = Signal(list)
    opened = Signal(str)
    menuRequested = Signal(str, QPoint)
    reordered = Signal(list)
    keyAction = Signal(str)

    def __init__(self, host: ViewHost, parent=None):
        super().__init__(parent)
        self.host = host
        self.setColumnCount(6)
        self.setHeaderLabels(["Name", "Type", "ID number", "Pages", "Size", "Added"])
        self.setRootIsDecorated(False)
        self.setAlternatingRowColors(False)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setIconSize(QSize(40, 26))
        self.setUniformRowHeights(True)
        self.header().setSortIndicator(-1, Qt.AscendingOrder)   # start in manual order
        self.setSortingEnabled(True)
        self.header().setSortIndicatorShown(True)
        self.header().setStretchLastSection(False)
        self.header().setSectionResizeMode(0, QHeaderView.Stretch)
        for c, w in ((1, 150), (2, 170), (3, 70), (4, 90), (5, 120)):
            self.header().setSectionResizeMode(c, QHeaderView.Interactive)
            self.setColumnWidth(c, w)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)
        self.itemDoubleClicked.connect(lambda it, _c: self.opened.emit(it.data(0, Qt.UserRole)))
        self.itemSelectionChanged.connect(self._sel)
        self._quiet = False
        self._pages: dict = {}

    def _pages_of(self, d: Doc):
        key = (d.file_name, d.password)
        if key not in self._pages:
            self._pages[key] = pdfutil.info(self.host.store.path_of(d), d.password)
        return self._pages[key]

    def set_docs(self, docs, replay=False):
        keep = self.selected_ids()
        self._quiet = True
        order = (self.header().sortIndicatorSection(), self.header().sortIndicatorOrder())
        self.setSortingEnabled(False)
        self.clear()
        for i, d in enumerate(docs):
            pages, locked = self._pages_of(d)
            try:
                size = os.path.getsize(self.host.store.path_of(d))
            except OSError:
                size = 0
            added = datetime.fromtimestamp(d.added)
            texts = [d.title, d.type_label, _num_text(self.host, d),
                     "Locked" if locked else (str(pages) if pages else "—"), human_size(size),
                     added.strftime("%d %b %Y")]
            keys = [d.title.lower(), d.type_label.lower(), d.number.lower(),
                    -1 if pages is None else pages, size, d.added]
            it = _Item(texts, keys)
            it.setData(0, Qt.UserRole, d.id)
            it.setIcon(0, QIcon(chip_pixmap(d, 40, 26, 7)))
            self.addTopLevelItem(it)
        self.header().setSortIndicator(order[0], order[1])
        self.setSortingEnabled(True)
        self._quiet = False
        self.set_selected(keep)

    def selected_ids(self) -> list[str]:
        return [self.topLevelItem(i).data(0, Qt.UserRole) for i in range(self.topLevelItemCount())
                if self.topLevelItem(i).isSelected()]

    def set_selected(self, ids):
        self._quiet = True
        for i in range(self.topLevelItemCount()):
            it = self.topLevelItem(i)
            it.setSelected(it.data(0, Qt.UserRole) in ids)
        self._quiet = False

    def refresh_look(self):
        self.viewport().update()

    def _sel(self):
        if not self._quiet:
            self.selectionChanged.emit(self.selected_ids())

    def _menu(self, pos):
        it = self.itemAt(pos)
        if it is not None:
            did = it.data(0, Qt.UserRole)
            if did not in self.selected_ids():
                self.set_selected([did])
                self.selectionChanged.emit([did])
            self.menuRequested.emit(did, self.viewport().mapToGlobal(pos))

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Return, Qt.Key_Enter):
            self.keyAction.emit("open")
        elif e.key() == Qt.Key_Space:
            self.keyAction.emit("reveal")
        elif e.key() == Qt.Key_Delete:
            self.keyAction.emit("delete")
        else:
            super().keyPressEvent(e)


def make_view(mode: str, host: ViewHost):
    if mode in ("stack", "grid"):
        return CardsView(mode, host)
    if mode == "details":
        return DetailsView(host)
    return ItemsView(mode, host)
