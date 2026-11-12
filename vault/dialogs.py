from __future__ import annotations

import shutil
import tempfile
import uuid
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QMimeData, QPointF, QRectF, QSize, Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QGuiApplication, QPainter, QPixmap
from PySide6.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QDialog, QFileDialog, QFormLayout, QHBoxLayout,
                               QLabel, QLineEdit, QListWidget, QMessageBox, QPushButton, QScrollArea, QToolButton,
                               QVBoxLayout, QWidget, QGridLayout, QApplication)

from . import APP_NAME, VERSION, pdfutil
from .models import (GRADIENTS, TYPES, Doc, format_number, guess_type, rgb_to_argb)
from .theme import THEME, gradient_for, paint_card

FILE_FILTER = "Documents (*.pdf *.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff);;PDF (*.pdf);;Photos (*.png *.jpg *.jpeg *.webp *.bmp)"
ACCEPT_EXT = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}


def temp_dir() -> Path:
    global _TEMP
    try:
        return _TEMP
    except NameError:
        _TEMP = Path(tempfile.mkdtemp(prefix="PersonalVault_"))
        import atexit
        atexit.register(shutil.rmtree, _TEMP, True)
        return _TEMP


def readable_copy(src: Path, title: str) -> Path:
    """Copy to temp under a friendly name, so 'Open with' / clipboard show a proper file name."""
    clean = "".join(c for c in title if c.isalnum() or c in " _-").strip() or "document"
    d = temp_dir() / uuid.uuid4().hex[:6]
    d.mkdir(parents=True, exist_ok=True)
    out = d / f"{clean}.pdf"
    shutil.copyfile(src, out)
    return out


def copy_file_to_clipboard(path: Path) -> None:
    md = QMimeData()
    md.setUrls([QUrl.fromLocalFile(str(path))])
    QGuiApplication.clipboard().setMimeData(md)


# ----------------------------------------------------------------------
class CardPreview(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.doc = Doc(id="preview", title="Preview")
        self.reveal = False
        self.setMinimumHeight(210)

    def set_doc(self, d: Doc, reveal: bool = False):
        self.doc, self.reveal = d, reveal
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        w = min(self.width() - 40, 440 if self.reveal else 380)
        h = w * (0.58 if self.reveal else 0.5)
        r = QRectF((self.width() - w) / 2, (self.height() - h) / 2, w, h)
        paint_card(p, r, self.doc, reveal=self.reveal)


# ----------------------------------------------------------------------
class DocDialog(QDialog):
    """Add or edit one document."""

    def __init__(self, store, doc: Doc | None = None, src: str | None = None, parent=None, heading: str = ""):
        super().__init__(parent)
        self.store, self.existing = store, doc
        self.src = src
        self.result_doc: Doc | None = None
        self.setWindowTitle(heading or ("Edit document" if doc else "Add document"))
        self.setMinimumWidth(560)
        self.setAcceptDrops(True)
        base = Path(src).name if src else ""
        t = doc.type if doc else guess_type(base)
        self.d = Doc(
            id=doc.id if doc else uuid.uuid4().hex, title=doc.title if doc else TYPES[t][0], type=t,
            custom_type=doc.custom_type if doc else "", number=doc.number if doc else "",
            gradient=doc.gradient if doc else TYPES[t][1], custom_a=doc.custom_a if doc else 0,
            custom_b=doc.custom_b if doc else 0, file_name=doc.file_name if doc else "",
            password=doc.password if doc else "", added=doc.added if doc else datetime.now().timestamp())

        lay = QVBoxLayout(self)
        lay.setSpacing(12)
        self.preview = CardPreview()
        lay.addWidget(self.preview)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        self.type_box = QComboBox()
        for k, (label, _) in TYPES.items():
            self.type_box.addItem(label, k)
        self.type_box.setCurrentIndex(list(TYPES).index(self.d.type))
        self.type_box.currentIndexChanged.connect(self._type_changed)
        form.addRow("Type", self.type_box)

        self.custom_edit = QLineEdit(self.d.custom_type)
        self.custom_edit.setPlaceholderText("e.g. Gas connection")
        self.custom_edit.textChanged.connect(self._sync)
        self.custom_label = QLabel("Custom type")
        form.addRow(self.custom_label, self.custom_edit)

        self.title_edit = QLineEdit(self.d.title)
        self.title_edit.setPlaceholderText("e.g. Aadhaar – Mother")
        self.title_edit.textChanged.connect(self._sync)
        form.addRow("Card name", self.title_edit)

        self.number_edit = QLineEdit(self.d.number)
        self.number_edit.setPlaceholderText("Optional")
        self.number_edit.textChanged.connect(self._sync)
        form.addRow("ID number", self.number_edit)

        pw_row = QHBoxLayout()
        self.pw_edit = QLineEdit(self.d.password)
        self.pw_edit.setEchoMode(QLineEdit.Password)
        self.pw_edit.setPlaceholderText("Only if the PDF is locked")
        self.pw_edit.setToolTip("Aadhaar PDF: first 4 letters of your name in CAPITALS + birth year, e.g. FALA1999")
        show = QToolButton()
        show.setText("Show")
        show.setCheckable(True)
        show.toggled.connect(lambda on: self.pw_edit.setEchoMode(QLineEdit.Normal if on else QLineEdit.Password))
        pw_row.addWidget(self.pw_edit, 1)
        pw_row.addWidget(show)
        form.addRow("PDF password", pw_row)
        lay.addLayout(form)

        lay.addWidget(self._label("Card colour"))
        grid = QGridLayout()
        grid.setSpacing(6)
        self.swatches: list[QToolButton] = []
        for i, cols in enumerate(GRADIENTS):
            b = QToolButton()
            b.setFixedSize(30, 30)
            stops = ", ".join(f"stop:{j / max(1, len(cols) - 1):.2f} {c}" for j, c in enumerate(cols))
            b.setStyleSheet(f"QToolButton{{border-radius:15px;border:2px solid transparent;"
                            f"background:qlineargradient(x1:0,y1:0,x2:1,y2:1,{stops});}}"
                            f"QToolButton:hover{{border-color:{THEME.text};}}")
            b.clicked.connect(lambda _=False, k=i: self._pick(k))
            grid.addWidget(b, i // 12, i % 12)
            self.swatches.append(b)
        lay.addLayout(grid)
        custom_row = QHBoxLayout()
        cb = QPushButton("Custom colours…")
        cb.clicked.connect(self._custom)
        custom_row.addWidget(cb)
        custom_row.addStretch(1)
        lay.addLayout(custom_row)

        lay.addWidget(self._label("Document file (PDF or photo)"))
        file_row = QHBoxLayout()
        self.file_label = QLabel(Path(src).name if src else ("Current file kept" if doc else "No file chosen — drop one here or browse"))
        self.file_label.setStyleSheet(f"color:{THEME.muted};")
        self.file_label.setWordWrap(True)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse)
        file_row.addWidget(self.file_label, 1)
        file_row.addWidget(browse)
        lay.addLayout(file_row)

        btns = QHBoxLayout()
        btns.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        self.save_btn = QPushButton("Save")
        self.save_btn.setObjectName("primary")
        self.save_btn.setDefault(True)
        self.save_btn.clicked.connect(self._save)
        btns.addWidget(cancel)
        btns.addWidget(self.save_btn)
        lay.addLayout(btns)
        self._sync()

    def _label(self, text):
        l = QLabel(text)
        l.setStyleSheet(f"color:{THEME.muted};font-size:12px;")
        return l

    def _type_changed(self):
        old = self.d.type
        self.d.type = self.type_box.currentData()
        if self.existing is None:
            if not self.title_edit.text().strip() or self.title_edit.text() == TYPES[old][0]:
                self.title_edit.setText(TYPES[self.d.type][0])
            if self.d.custom_a == 0:
                self.d.gradient = TYPES[self.d.type][1]
        self._sync()

    def _pick(self, i):
        self.d.gradient, self.d.custom_a, self.d.custom_b = i, 0, 0
        self._sync()

    def _custom(self):
        a = QColorDialog.getColor(QColor(self.d.colors_hex()[0]), self, "Start colour")
        if not a.isValid():
            return
        b = QColorDialog.getColor(QColor(self.d.colors_hex()[-1]), self, "End colour")
        if not b.isValid():
            return
        self.d.custom_a = rgb_to_argb(a.red(), a.green(), a.blue())
        self.d.custom_b = rgb_to_argb(b.red(), b.green(), b.blue())
        self._sync()

    def _browse(self):
        f, _ = QFileDialog.getOpenFileName(self, "Choose a document", str(Path.home()), FILE_FILTER)
        if f:
            self._set_src(f)

    def _set_src(self, f: str):
        self.src = f
        self.file_label.setText(Path(f).name)
        if self.existing is None and self.title_edit.text() == TYPES[self.d.type][0]:
            t = guess_type(Path(f).name)
            self.type_box.setCurrentIndex(list(TYPES).index(t))
        self._sync()

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        for u in e.mimeData().urls():
            p = Path(u.toLocalFile())
            if p.suffix.lower() in ACCEPT_EXT:
                self._set_src(str(p))
                break

    def _sync(self):
        self.d.title = self.title_edit.text()
        self.d.number = self.number_edit.text()
        self.d.password = self.pw_edit.text()
        self.d.custom_type = self.custom_edit.text()
        self.custom_edit.setVisible(self.d.type == "OTHER")
        self.custom_label.setVisible(self.d.type == "OTHER")
        shown = Doc(**{**self.d.__dict__, "title": self.d.title.strip() or self.d.type_label})
        self.preview.set_doc(shown)
        ok = bool(self.d.title.strip()) and (self.existing is not None or bool(self.src))
        self.save_btn.setEnabled(ok)

    def _save(self):
        d = self.d
        d.title, d.number, d.custom_type = d.title.strip(), d.number.strip(), d.custom_type.strip()
        old = self.existing.file_name if self.existing else None
        try:
            if self.src:
                d.file_name = self.store.import_file(self.src)
        except Exception as ex:
            QMessageBox.warning(self, APP_NAME, f"Couldn't read that file.\n\n{ex}")
            return
        self.result_doc, self.old_file = d, old
        self.accept()


# ----------------------------------------------------------------------
class PasswordDialog(QDialog):
    def __init__(self, title: str, wrong: bool, parent=None):
        super().__init__(parent)
        self.setWindowTitle("PDF password")
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(f"“{title}” is password-protected."))
        if wrong:
            w = QLabel("That password didn't work. Try again.")
            w.setStyleSheet("color:#FF6B6B;")
            lay.addWidget(w)
        self.edit = QLineEdit()
        self.edit.setEchoMode(QLineEdit.Password)
        self.edit.setMinimumWidth(320)
        lay.addWidget(self.edit)
        hint = QLabel("Aadhaar PDF: first 4 letters of your name in CAPITALS + birth year (e.g. FALA1999).")
        hint.setStyleSheet(f"color:{THEME.muted};font-size:12px;")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        self.remember = QCheckBox("Remember for this card")
        self.remember.setChecked(True)
        lay.addWidget(self.remember)
        row = QHBoxLayout()
        row.addStretch(1)
        c = QPushButton("Cancel")
        c.clicked.connect(self.reject)
        ok = QPushButton("Unlock")
        ok.setObjectName("primary")
        ok.setDefault(True)
        ok.clicked.connect(self.accept)
        row.addWidget(c)
        row.addWidget(ok)
        lay.addLayout(row)


class ViewerDialog(QDialog):
    def __init__(self, store, doc: Doc, parent=None):
        super().__init__(parent)
        self.store, self.doc = store, doc
        self.setWindowTitle(doc.title)
        self.resize(900, 820)
        self.zoom_mul = 1.0
        self.pdf = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        bar = QHBoxLayout()
        bar.setContentsMargins(12, 8, 12, 8)
        for text, fn in (("−", lambda: self._zoom(0.8)), ("＋", lambda: self._zoom(1.25)), ("Fit width", self._fit)):
            b = QToolButton()
            b.setText(text)
            b.clicked.connect(fn)
            bar.addWidget(b)
        self.info = QLabel("")
        self.info.setStyleSheet(f"color:{THEME.muted};")
        bar.addWidget(self.info)
        bar.addStretch(1)
        for text, fn in (("Open with…", self._open), ("Copy file", self._copy), ("Save a copy…", self._save)):
            b = QToolButton()
            b.setText(text)
            b.clicked.connect(fn)
            bar.addWidget(b)
        lay.addLayout(bar)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setAlignment(Qt.AlignHCenter)
        self.holder = QWidget()
        self.holder.setObjectName("holder")
        self.holder.setStyleSheet(f"QWidget#holder{{background:{THEME.surface};}}")
        self.pages = QVBoxLayout(self.holder)
        self.pages.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        self.pages.setSpacing(12)
        self.pages.setContentsMargins(16, 12, 16, 24)
        self.scroll.setWidget(self.holder)
        lay.addWidget(self.scroll, 1)
        self.ok = self._open_pdf()

    def _open_pdf(self) -> bool:
        pw = self.doc.password
        while True:
            try:
                self.pdf = pdfutil.open_pdf(self.store.path_of(self.doc), pw)
                break
            except pdfutil.NeedPassword as e:
                dlg = PasswordDialog(self.doc.title, e.wrong, self)
                if dlg.exec() != QDialog.Accepted:
                    return False
                pw = dlg.edit.text()
                if dlg.remember.isChecked() and pw != self.doc.password:
                    self.doc.password = pw
                    self.store.update(self.doc)
            except Exception as ex:
                QMessageBox.warning(self, APP_NAME, f"Couldn't open this PDF.\n\n{ex}")
                return False
        self.info.setText(f"{len(self.pdf)} page(s)")
        self._fit()
        return True

    def _base_zoom(self) -> float:
        w, _ = pdfutil.page_size(self.pdf, 0)
        avail = self.scroll.viewport().width() - 60
        return max(0.3, avail / max(w, 1)) * (self.devicePixelRatioF())

    def _render(self):
        while self.pages.count():
            it = self.pages.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        z = self._base_zoom() * self.zoom_mul
        dpr = self.devicePixelRatioF()
        for i in range(min(len(self.pdf), 60)):
            img = pdfutil.render_page(self.pdf, i, z)
            pm = QPixmap.fromImage(img)
            pm.setDevicePixelRatio(dpr)
            lab = QLabel()
            lab.setPixmap(pm)
            lab.setStyleSheet("background:white;")
            self.pages.addWidget(lab, 0, Qt.AlignHCenter)

    def _fit(self):
        self.zoom_mul = 1.0
        self._render()

    def _zoom(self, f):
        self.zoom_mul = max(0.3, min(4.0, self.zoom_mul * f))
        self._render()

    def _open(self):
        p = readable_copy(self.store.path_of(self.doc), self.doc.title)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(p)))

    def _copy(self):
        copy_file_to_clipboard(readable_copy(self.store.path_of(self.doc), self.doc.title))
        QMessageBox.information(self, APP_NAME, "File copied. You can paste it into WhatsApp, Gmail or any folder.")

    def _save(self):
        save_copy(self, self.store.path_of(self.doc), self.doc.title)

    def done(self, r):
        if self.pdf:
            self.pdf.close()
        super().done(r)


def save_copy(parent, src: Path, title: str) -> None:
    clean = "".join(c for c in title if c.isalnum() or c in " _-").strip() or "document"
    start = str(Path.home() / "Downloads" / f"{clean}.pdf")
    dest, _ = QFileDialog.getSaveFileName(parent, "Save a copy", start, "PDF (*.pdf)")
    if dest:
        shutil.copyfile(src, dest)


# ----------------------------------------------------------------------
class RevealDialog(QDialog):
    def __init__(self, store, doc: Doc, parent=None):
        super().__init__(parent)
        self.store, self.doc = store, doc
        self.want_view = False
        self.setWindowTitle(doc.title)
        self.setMinimumWidth(540)
        lay = QVBoxLayout(self)
        pv = CardPreview()
        pv.setMinimumHeight(280)
        pv.set_doc(doc, reveal=True)
        lay.addWidget(pv)
        t = QLabel(doc.type_label)
        t.setAlignment(Qt.AlignCenter)
        t.setStyleSheet("font-size:17px;font-weight:600;")
        lay.addWidget(t)
        if doc.number:
            n = QLabel("ID: " + format_number(doc.number))
            n.setAlignment(Qt.AlignCenter)
            n.setStyleSheet(f"color:{THEME.muted};font-size:15px;")
            lay.addWidget(n)
        row = QHBoxLayout()
        row.addStretch(1)
        if doc.number:
            c = QPushButton("Copy number")
            c.clicked.connect(lambda: QGuiApplication.clipboard().setText(doc.number))
            row.addWidget(c)
        v = QPushButton("View PDF")
        v.setObjectName("primary")
        v.clicked.connect(self._view)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        row.addWidget(v)
        row.addWidget(close)
        row.addStretch(1)
        lay.addLayout(row)

    def _view(self):
        self.want_view = True
        self.accept()


# ----------------------------------------------------------------------
class MergeDialog(QDialog):
    def __init__(self, docs: list[Doc], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Merge & share")
        self.setMinimumWidth(460)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("Pages are added in this order. Every page is placed on an A4 sheet.\n"
                             "The merged file is only for sharing — it is not stored in the vault."))
        self.list = QListWidget()
        for d in docs:
            self.list.addItem(d.title)
            self.list.item(self.list.count() - 1).setData(Qt.UserRole, d.id)
        self.list.setCurrentRow(0)
        lay.addWidget(self.list)
        row = QHBoxLayout()
        up = QPushButton("Move up")
        up.clicked.connect(lambda: self._move(-1))
        dn = QPushButton("Move down")
        dn.clicked.connect(lambda: self._move(1))
        row.addWidget(up)
        row.addWidget(dn)
        row.addStretch(1)
        c = QPushButton("Cancel")
        c.clicked.connect(self.reject)
        ok = QPushButton("Merge")
        ok.setObjectName("primary")
        ok.clicked.connect(self.accept)
        row.addWidget(c)
        row.addWidget(ok)
        lay.addLayout(row)

    def _move(self, d):
        r = self.list.currentRow()
        n = r + d
        if 0 <= n < self.list.count():
            it = self.list.takeItem(r)
            self.list.insertItem(n, it)
            self.list.setCurrentRow(n)

    def ordered_ids(self) -> list[str]:
        return [self.list.item(i).data(Qt.UserRole) for i in range(self.list.count())]


class MergeResultDialog(QDialog):
    def __init__(self, path: Path, parent=None):
        super().__init__(parent)
        self.path = path
        self.setWindowTitle("Merged document ready")
        self.setMinimumWidth(440)
        lay = QVBoxLayout(self)
        l = QLabel(f"<b>{path.stem}</b><br><span style='color:{THEME.muted}'>Choose how to share it:</span>")
        lay.addWidget(l)
        for text, fn in (("Copy file (paste into WhatsApp, Gmail, Explorer)", self._copy),
                         ("Save as…", self._save), ("Open", self._open), ("Show in folder", self._show)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            lay.addWidget(b)
        close = QPushButton("Done")
        close.setObjectName("primary")
        close.clicked.connect(self.accept)
        lay.addWidget(close)

    def _copy(self):
        copy_file_to_clipboard(self.path)
        QMessageBox.information(self, APP_NAME, "Copied. Paste it where you want to share it.")

    def _save(self):
        dest, _ = QFileDialog.getSaveFileName(self, "Save merged PDF", str(Path.home() / "Downloads" / self.path.name), "PDF (*.pdf)")
        if dest:
            shutil.copyfile(self.path, dest)

    def _open(self):
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.path)))

    def _show(self):
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.path.parent)))


# ----------------------------------------------------------------------
class SettingsDialog(QDialog):
    def __init__(self, win, parent=None):
        super().__init__(parent)
        self.win, store = win, win.store
        self.setWindowTitle("Settings")
        self.setMinimumWidth(500)
        lay = QVBoxLayout(self)
        lay.setSpacing(12)

        form = QFormLayout()
        self.theme = QComboBox()
        for label, v in (("Follow Windows", "system"), ("Light", "light"), ("Dark", "dark")):
            self.theme.addItem(label, v)
        self.theme.setCurrentIndex(self.theme.findData(store.get_setting("theme", "system")))
        self.theme.currentIndexChanged.connect(lambda: win.set_theme(self.theme.currentData()))
        form.addRow("Theme", self.theme)
        self.default_view = QComboBox()
        from .views import VIEW_MODES
        for k, label in VIEW_MODES:
            self.default_view.addItem(label, k)
        self.default_view.setCurrentIndex(self.default_view.findData(store.get_setting("view", "stack")))
        self.default_view.currentIndexChanged.connect(lambda: win.set_view(self.default_view.currentData()))
        form.addRow("View", self.default_view)
        lay.addLayout(form)

        self.nums = QCheckBox("Show full ID numbers in List, Tiles and Details views")
        self.nums.setChecked(bool(store.get_setting("show_numbers", False)))
        self.nums.toggled.connect(win.set_show_numbers)
        lay.addWidget(self.nums)
        self.shots = QCheckBox("Block screenshots and screen recording of this window")
        self.shots.setChecked(bool(store.get_setting("block_capture", False)))
        self.shots.toggled.connect(win.set_block_capture)
        lay.addWidget(self.shots)

        lay.addWidget(self._h("Backup"))
        t = QLabel("One .zip with all documents and card details (including saved PDF passwords). "
                   "It is compatible with the Android app. Keep it somewhere safe.")
        t.setWordWrap(True)
        t.setStyleSheet(f"color:{THEME.muted};font-size:12px;")
        lay.addWidget(t)
        row = QHBoxLayout()
        b1 = QPushButton("Create backup…")
        b1.clicked.connect(win.do_backup)
        b2 = QPushButton("Restore from backup…")
        b2.clicked.connect(win.do_restore)
        row.addWidget(b1)
        row.addWidget(b2)
        lay.addLayout(row)

        lay.addWidget(self._h("Storage"))
        loc = QLabel(f"Portable data folder:<br><span style='color:{THEME.muted}'>{store.root}</span>")
        loc.setWordWrap(True)
        loc.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(loc)
        o = QPushButton("Open data folder")
        o.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(store.root))))
        lay.addWidget(o)

        lay.addWidget(self._h("About"))
        lay.addWidget(QLabel(f"{APP_NAME} for Windows  V{VERSION}"))
        tips = QLabel("Tip: drag PDFs or photos onto the window or the .exe to add them. "
                      "Put a shortcut to the .exe in the Windows <i>SendTo</i> folder to add files from the right-click menu.")
        tips.setWordWrap(True)
        tips.setStyleSheet(f"color:{THEME.muted};font-size:12px;")
        lay.addWidget(tips)
        close = QPushButton("Close")
        close.setObjectName("primary")
        close.clicked.connect(self.accept)
        lay.addWidget(close, 0, Qt.AlignRight)

    def _h(self, text):
        l = QLabel(text)
        l.setStyleSheet(f"color:{THEME.accent};font-weight:600;margin-top:6px;")
        return l
