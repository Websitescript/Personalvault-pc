from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtGui import QAction, QActionGroup, QGuiApplication, QIcon, QKeySequence
from PySide6.QtWidgets import (QApplication, QFileDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow,
                               QMenu, QMessageBox, QStackedWidget, QToolBar, QToolButton, QWidget, QHBoxLayout,
                               QVBoxLayout, QSizePolicy)

from . import APP_NAME, VERSION, pdfutil
from .dialogs import (ACCEPT_EXT, DocDialog, ImagesResultDialog, MergeDialog, MergeResultDialog, RevealDialog, SettingsDialog,
                      ViewerDialog, copy_file_to_clipboard, readable_copy, save_copy, temp_dir)
from .models import TYPES, Doc, matches
from .theme import THEME
from .views import VIEW_MODES, ThumbCache, ViewHost, make_view


def asset(name: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base / "assets" / name


class MainWindow(QMainWindow):
    def __init__(self, store):
        super().__init__()
        self.store = store
        self.thumbs = ThumbCache(store)
        self.host = ViewHost(store, self.thumbs, lambda: bool(store.get_setting("show_numbers", False)))
        mode = store.get_setting("view", "stack")
        self.mode = mode if mode in dict(VIEW_MODES) else "stack"
        self.type_filter: str | None = None
        self.query = ""
        self.sel: list[str] = []
        self.views: dict = {}
        self.setWindowTitle(APP_NAME)
        self.resize(1180, 780)
        self.setMinimumSize(820, 540)
        self.setAcceptDrops(True)
        ico = asset("icon.png")
        if ico.exists():
            self.setWindowIcon(QIcon(str(ico)))

        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        h = QHBoxLayout(root)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)
        self.sidebar = QListWidget()
        self.sidebar.setObjectName("sidebar")
        self.sidebar.setFixedWidth(220)
        self.sidebar.currentRowChanged.connect(self._sidebar_changed)
        h.addWidget(self.sidebar)
        self.stack = QStackedWidget()
        h.addWidget(self.stack, 1)
        self.empty = QLabel()
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.setWordWrap(True)
        self.empty.setStyleSheet("font-size:15px;padding:40px;")
        self.stack.addWidget(self.empty)

        self._build_toolbar()
        self.statusBar().showMessage("")
        self.apply_theme()
        QGuiApplication.styleHints().colorSchemeChanged.connect(lambda *_: self.apply_theme())
        self.apply_capture(bool(store.get_setting("block_capture", False)))
        self.refresh(replay=True)

    # ------------------------------------------------------------ toolbar
    def _build_toolbar(self):
        tb = QToolBar("Main")
        tb.setMovable(False)
        tb.setFloatable(False)
        self.addToolBar(tb)
        self.act_add = QAction("＋  Add document", self)
        self.act_add.setShortcut(QKeySequence.New)
        self.act_add.triggered.connect(self.add_dialog)
        self.act_merge = QAction("Merge selected into one PDF…", self)
        self.act_merge.setShortcut("Ctrl+M")
        self.act_merge.triggered.connect(self.merge_selected)
        self.act_images = QAction("Selected as images (JPG)…", self)
        self.act_images.setShortcut("Ctrl+Shift+I")
        self.act_images.triggered.connect(lambda: self.share_as_images([d for d in (self.doc(i) for i in self.sel) if d]))
        tb.addAction(self.act_add)
        share_btn = QToolButton()
        share_btn.setText("Share  ▾")
        share_btn.setPopupMode(QToolButton.InstantPopup)
        share_menu = QMenu(share_btn)
        share_menu.addAction(self.act_merge)
        share_menu.addAction(self.act_images)
        share_btn.setMenu(share_menu)
        tb.addWidget(share_btn)
        sp = QWidget()
        sp.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        tb.addWidget(sp)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search name or ID number   (Ctrl+F)")
        self.search.setClearButtonEnabled(True)
        self.search.setFixedWidth(300)
        self.search.textChanged.connect(self._search_changed)
        tb.addWidget(self.search)
        self.act_find = QAction(self)
        self.act_find.setShortcut(QKeySequence.Find)
        self.act_find.triggered.connect(lambda: (self.search.setFocus(), self.search.selectAll()))
        self.addAction(self.act_find)

        self.view_btn = QToolButton()
        self.view_btn.setPopupMode(QToolButton.InstantPopup)
        menu = QMenu(self.view_btn)
        grp = QActionGroup(self)
        grp.setExclusive(True)
        self.view_actions = {}
        for i, (k, label) in enumerate(VIEW_MODES):
            a = QAction(label, self, checkable=True)
            a.setShortcut(f"Ctrl+{i + 1}")
            a.triggered.connect(lambda _=False, key=k: self.set_view(key))
            grp.addAction(a)
            menu.addAction(a)
            self.view_actions[k] = a
        self.view_btn.setMenu(menu)
        tb.addWidget(self.view_btn)
        self.act_settings = QAction("⚙  Settings", self)
        self.act_settings.setShortcut("Ctrl+,")
        self.act_settings.triggered.connect(lambda: SettingsDialog(self, self).exec())
        tb.addAction(self.act_settings)
        self._update_view_btn()

    def _update_view_btn(self):
        self.view_btn.setText("View:  " + dict(VIEW_MODES)[self.mode] + "  ▾")
        self.view_actions[self.mode].setChecked(True)

    # ------------------------------------------------------------ settings
    def apply_theme(self):
        pref = self.store.get_setting("theme", "system")
        if pref == "system":
            dark = QGuiApplication.styleHints().colorScheme() != Qt.ColorScheme.Light
        else:
            dark = pref == "dark"
        THEME.set(dark)
        QApplication.instance().setStyleSheet(THEME.qss())
        for v in self.views.values():
            v.refresh_look()
        self.empty.setStyleSheet(f"font-size:15px;padding:40px;color:{THEME.muted};")

    def set_theme(self, name: str):
        self.store.set_setting("theme", name)
        self.apply_theme()

    def set_view(self, mode: str):
        if mode not in dict(VIEW_MODES):
            return
        self.mode = mode
        self.store.set_setting("view", mode)
        self._update_view_btn()
        self.refresh(replay=True)

    def set_show_numbers(self, on: bool):
        self.store.set_setting("show_numbers", bool(on))
        self.refresh()

    def set_block_capture(self, on: bool):
        self.store.set_setting("block_capture", bool(on))
        self.apply_capture(bool(on))

    def apply_capture(self, on: bool):
        if sys.platform != "win32":
            return
        try:
            import ctypes
            ctypes.windll.user32.SetWindowDisplayAffinity(int(self.winId()), 0x11 if on else 0)
        except Exception:
            pass

    # ------------------------------------------------------------ data / views
    def visible_docs(self) -> list[Doc]:
        return [d for d in self.store.docs
                if (self.type_filter is None or d.type == self.type_filter) and matches(d, self.query)]

    def current_view(self):
        if self.mode not in self.views:
            v = make_view(self.mode, self.host)
            v.selectionChanged.connect(self._selection_changed)
            v.opened.connect(self.open_doc)
            v.menuRequested.connect(self.show_menu)
            v.reordered.connect(self._reordered)
            v.keyAction.connect(self._key_action)
            self.views[self.mode] = v
            self.stack.addWidget(v)
        return self.views[self.mode]

    def refresh(self, replay: bool = False):
        docs = self.visible_docs()
        self._rebuild_sidebar()
        if not docs:
            if self.store.docs:
                self.empty.setText("No matching documents.")
            else:
                self.empty.setText("<b style='font-size:20px'>Your vault is empty</b><br><br>"
                                   "Click <b>＋ Add document</b>, or drag PDFs / photos onto this window.<br>"
                                   "You can also drop files on the .exe, or use SendTo → Personal Vault.")
            self.stack.setCurrentWidget(self.empty)
        else:
            v = self.current_view()
            ids = {d.id for d in docs}
            self.sel = [i for i in self.sel if i in ids]
            v.set_docs(docs, replay)
            v.set_selected(self.sel)
            self.stack.setCurrentWidget(v)
        self._status()

    def _rebuild_sidebar(self):
        self.sidebar.blockSignals(True)
        self.sidebar.clear()
        counts: dict = {}
        for d in self.store.docs:
            counts[d.type] = counts.get(d.type, 0) + 1
        it = QListWidgetItem(f"All documents   ({len(self.store.docs)})")
        it.setData(Qt.UserRole, None)
        self.sidebar.addItem(it)
        row = 0
        for k, (label, _) in TYPES.items():
            if counts.get(k):
                it = QListWidgetItem(f"{label}   ({counts[k]})")
                it.setData(Qt.UserRole, k)
                self.sidebar.addItem(it)
                if k == self.type_filter:
                    row = self.sidebar.count() - 1
        if self.type_filter and row == 0:
            self.type_filter = None
        self.sidebar.setCurrentRow(row)
        self.sidebar.blockSignals(False)

    def _sidebar_changed(self, row: int):
        if row < 0:
            return
        self.type_filter = self.sidebar.item(row).data(Qt.UserRole)
        self.refresh(replay=True)

    def _search_changed(self, text: str):
        self.query = text
        self.refresh()

    def _selection_changed(self, ids: list):
        self.sel = list(ids)
        self._status()

    def _status(self):
        n, total = len(self.visible_docs()), len(self.store.docs)
        msg = f"{n} of {total} document(s)" if n != total else f"{total} document(s)"
        if self.sel:
            msg += f"   •   {len(self.sel)} selected"
            if len(self.sel) > 1:
                msg += "   •   Share ▾ to merge or send as images"
        else:
            msg += "   •   double-click to open, right-click for more, Ctrl+click to select several"
        self.statusBar().showMessage(msg)

    def _reordered(self, ids: list):
        visible = [d.id for d in self.visible_docs()]
        self.store.apply_order(ids, visible)
        self.refresh()

    def _key_action(self, name: str):
        if not self.sel:
            return
        if name == "open":
            self.open_doc(self.sel[0])
        elif name == "reveal":
            self.reveal_doc(self.sel[0])
        elif name == "delete":
            self.delete_selected()

    # ------------------------------------------------------------ actions
    def doc(self, doc_id: str) -> Doc | None:
        return self.store.by_id(doc_id)

    def open_doc(self, doc_id: str):
        d = self.doc(doc_id)
        if not d:
            return
        dlg = ViewerDialog(self.store, d, self)
        if dlg.ok:
            dlg.exec()
            self.refresh()

    def reveal_doc(self, doc_id: str):
        d = self.doc(doc_id)
        if not d:
            return
        dlg = RevealDialog(self.store, d, self)
        dlg.exec()
        if dlg.want_view:
            self.open_doc(doc_id)

    def add_dialog(self):
        dlg = DocDialog(self.store, None, None, self)
        if dlg.exec() == DocDialog.Accepted:
            self._added(dlg.result_doc)

    def add_files(self, paths: list):
        paths = [p for p in paths if Path(p).suffix.lower() in ACCEPT_EXT and Path(p).is_file()]
        for i, p in enumerate(paths):
            head = "Add document" if len(paths) == 1 else f"Add document ({i + 1} of {len(paths)})"
            dlg = DocDialog(self.store, None, p, self, heading=head)
            if dlg.exec() == DocDialog.Accepted:
                self._added(dlg.result_doc)

    def _added(self, d: Doc):
        self.store.add(d)
        self.sel = [d.id]
        self.type_filter = None
        self.search.blockSignals(True)
        self.search.clear()
        self.search.blockSignals(False)
        self.query = ""
        self.refresh()

    def edit_doc(self, doc_id: str):
        d = self.doc(doc_id)
        if not d:
            return
        dlg = DocDialog(self.store, d, None, self)
        if dlg.exec() == DocDialog.Accepted:
            self.store.update(dlg.result_doc, dlg.old_file)
            self.thumbs.invalidate(d.file_name)
            self.refresh()

    def delete_selected(self):
        docs = [d for d in (self.doc(i) for i in self.sel) if d]
        if not docs:
            return
        what = f"“{docs[0].title}”" if len(docs) == 1 else f"{len(docs)} documents"
        r = QMessageBox.question(self, APP_NAME, f"Delete {what}?\nThe stored PDF will be removed from the vault. This can't be undone.",
                                 QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Cancel)
        if r == QMessageBox.Yes:
            for d in docs:
                self.store.delete(d)
                self.thumbs.invalidate(d.file_name)
            self.sel = []
            self.refresh()

    def move(self, doc_id: str, delta: int):
        self.store.move_relative(doc_id, [d.id for d in self.visible_docs()], delta)
        self.refresh()

    def move_edge(self, doc_id: str, top: bool):
        self.store.move_to_edge(doc_id, top)
        self.refresh()

    def merge_selected(self):
        docs = [d for d in (self.doc(i) for i in self.sel) if d]
        if len(docs) < 2:
            QMessageBox.information(self, APP_NAME, "Select 2 or more documents first.\n"
                                    "Ctrl+click to pick several (the numbers on the cards show the order).")
            return
        dlg = MergeDialog(docs, self)
        if dlg.exec() != MergeDialog.Accepted:
            return
        by = {d.id: d for d in docs}
        ordered = [by[i] for i in dlg.ordered_ids()]
        out = temp_dir() / f"Docs {datetime.now().strftime('%d-%m-%Y %H.%M')}.pdf"
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            pdfutil.merge_to_a4([(self.store.path_of(d), d.password, d.title) for d in ordered], out)
        except pdfutil.NeedPassword as e:
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self, APP_NAME, f"“{e.title}” is password-protected.\nOpen it once and enter its password "
                                "(tick “Remember for this card”), then try again.")
            return
        except Exception as ex:
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self, APP_NAME, f"Couldn't merge these documents.\n\n{ex}")
            return
        QApplication.restoreOverrideCursor()
        MergeResultDialog(out, self).exec()

    def share_as_images(self, docs: list):
        docs = [d for d in docs if d]
        if not docs:
            QMessageBox.information(self, APP_NAME, "Select one or more documents first.")
            return
        out_dir = temp_dir() / ("images_" + datetime.now().strftime("%H%M%S%f"))
        files: list = []
        used: set = set()
        current = docs[0]
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            for d in docs:
                current = d
                if len(files) >= 40:
                    break
                base = "".join(c for c in d.title if c.isalnum() or c in " _-").strip() or "document"
                name, k = base, 2
                while name.lower() in used:
                    name, k = f"{base} ({k})", k + 1
                used.add(name.lower())
                files += pdfutil.export_jpegs(self.store.path_of(d), d.password, name, out_dir, 1600, 40 - len(files))
        except pdfutil.NeedPassword:
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self, APP_NAME, f"“{current.title}” is password-protected.\nOpen it once and enter its password "
                                "(tick “Remember for this card”), then try again.")
            return
        except Exception as ex:
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self, APP_NAME, f"Couldn't turn the documents into images.\n\n{ex}")
            return
        QApplication.restoreOverrideCursor()
        if not files:
            QMessageBox.information(self, APP_NAME, "Nothing to share.")
            return
        ImagesResultDialog(files, self).exec()

    def do_backup(self):
        name = f"PersonalVault-backup-{datetime.now().strftime('%Y%m%d')}.zip"
        f, _ = QFileDialog.getSaveFileName(self, "Create backup", str(Path.home() / "Downloads" / name), "Backup (*.zip)")
        if f:
            n = self.store.backup(f)
            QMessageBox.information(self, APP_NAME, f"Backup saved ({n} documents).")

    def do_restore(self):
        f, _ = QFileDialog.getOpenFileName(self, "Restore from backup", str(Path.home() / "Downloads"), "Backup (*.zip)")
        if not f:
            return
        try:
            n = self.store.restore(f)
        except Exception as ex:
            QMessageBox.warning(self, APP_NAME, f"That isn't a valid backup file.\n\n{ex}")
            return
        self.refresh()
        QMessageBox.information(self, APP_NAME, "Nothing new to restore." if n == 0 else f"Restored {n} documents.")

    # ------------------------------------------------------------ menu
    def show_menu(self, doc_id: str, pos: QPoint):
        d = self.doc(doc_id)
        if not d:
            return
        m = QMenu(self)
        m.addAction("View", lambda: self.open_doc(doc_id))
        m.addAction("Reveal card   (Space)", lambda: self.reveal_doc(doc_id))
        m.addSeparator()
        m.addAction("Open with default app", lambda: self._open_ext(d))
        m.addAction("Copy file", lambda: self._copy_file(d))
        m.addAction("Save a copy…", lambda: save_copy(self, self.store.path_of(d), d.title))
        m.addAction("Show in folder", lambda: self._show_folder(d))
        if d.number:
            m.addAction("Copy ID number", lambda: QGuiApplication.clipboard().setText(d.number))
        m.addSeparator()
        if len(self.sel) > 1:
            m.addAction(f"Merge {len(self.sel)} documents into one PDF…", self.merge_selected)
            m.addAction(f"Share {len(self.sel)} documents as images…", self.act_images.trigger)
        else:
            m.addAction("Share as images (JPG)…", lambda: self.share_as_images([d]))
        m.addAction("Edit…", lambda: self.edit_doc(doc_id))
        sub = m.addMenu("Move")
        sub.addAction("Up", lambda: self.move(doc_id, -1))
        sub.addAction("Down", lambda: self.move(doc_id, 1))
        sub.addAction("To top", lambda: self.move_edge(doc_id, True))
        sub.addAction("To bottom", lambda: self.move_edge(doc_id, False))
        m.addSeparator()
        m.addAction("Delete…", self.delete_selected)
        m.exec(pos)

    def _open_ext(self, d: Doc):
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(readable_copy(self.store.path_of(d), d.title))))

    def _copy_file(self, d: Doc):
        copy_file_to_clipboard(readable_copy(self.store.path_of(d), d.title))
        self.statusBar().showMessage("File copied — paste it into WhatsApp, Gmail or a folder.", 5000)

    def _show_folder(self, d: Doc):
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(readable_copy(self.store.path_of(d), d.title).parent)))

    # ------------------------------------------------------------ drag & drop
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        paths = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        e.acceptProposedAction()
        QTimer.singleShot(0, lambda: self.add_files(paths))
