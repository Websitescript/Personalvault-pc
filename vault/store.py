"""Local storage: portable data folder next to the .exe, JSON index, backup/restore."""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
import uuid
import zipfile
from pathlib import Path

from . import pdfutil
from .models import Doc


def data_dir() -> Path:
    override = os.environ.get("PV_DATA_DIR")
    if override:
        d = Path(override)
        d.mkdir(parents=True, exist_ok=True)
        return d
    base = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent
    d = base / "PersonalVaultData"
    try:
        d.mkdir(parents=True, exist_ok=True)
        probe = d / ".write_test"
        probe.write_text("x")
        probe.unlink()
        return d
    except OSError:
        d = Path(os.environ.get("APPDATA", str(Path.home()))) / "PersonalVault"
        d.mkdir(parents=True, exist_ok=True)
        return d


class Store:
    def __init__(self):
        self.root = data_dir()
        self.docs_dir = self.root / "docs"
        self.thumb_dir = self.root / "thumbs"
        self.docs_dir.mkdir(exist_ok=True)
        self.thumb_dir.mkdir(exist_ok=True)
        self.index = self.root / "docs.json"
        self.settings_file = self.root / "settings.json"
        self.docs: list[Doc] = []
        self.settings: dict = {}
        self.load()

    # ---- persistence -------------------------------------------------
    def load(self) -> None:
        try:
            self.docs = [Doc.from_json(o) for o in json.loads(self.index.read_text("utf-8"))]
        except Exception:
            self.docs = []
        try:
            self.settings = json.loads(self.settings_file.read_text("utf-8"))
        except Exception:
            self.settings = {}

    def save(self) -> None:
        tmp = self.index.with_suffix(".tmp")
        tmp.write_text(json.dumps([d.to_json() for d in self.docs], indent=1), "utf-8")
        tmp.replace(self.index)

    def set_setting(self, key, value) -> None:
        self.settings[key] = value
        self.settings_file.write_text(json.dumps(self.settings, indent=1), "utf-8")

    def get_setting(self, key, default=None):
        return self.settings.get(key, default)

    # ---- documents ---------------------------------------------------
    def path_of(self, d: Doc) -> Path:
        return self.docs_dir / d.file_name

    def by_id(self, doc_id: str) -> Doc | None:
        return next((d for d in self.docs if d.id == doc_id), None)

    def import_file(self, src) -> str:
        """Copy a PDF in, or convert a photo to PDF. Returns the stored file name."""
        name = uuid.uuid4().hex + ".pdf"
        out = self.docs_dir / name
        if pdfutil.sniff_is_pdf(src):
            shutil.copyfile(src, out)
        else:
            pdfutil.image_to_pdf(src, out)
        return name

    def add(self, doc: Doc) -> None:
        self.docs.append(doc)
        self.save()

    def update(self, doc: Doc, old_file: str | None = None) -> None:
        for i, d in enumerate(self.docs):
            if d.id == doc.id:
                self.docs[i] = doc
        if old_file and old_file != doc.file_name:
            self.delete_files(old_file)
        self.save()

    def delete(self, doc: Doc) -> None:
        self.docs = [d for d in self.docs if d.id != doc.id]
        self.delete_files(doc.file_name)
        self.save()

    def delete_files(self, file_name: str) -> None:
        for p in (self.docs_dir / file_name, self.thumb_dir / (file_name + ".png")):
            try:
                p.unlink()
            except OSError:
                pass

    def move_relative(self, doc_id: str, visible_ids: list[str], delta: int) -> None:
        """Swap with the neighbour in the currently visible list (works when a filter is active)."""
        if doc_id not in visible_ids:
            return
        j = visible_ids.index(doc_id) + delta
        if not 0 <= j < len(visible_ids):
            return
        a = next(i for i, d in enumerate(self.docs) if d.id == doc_id)
        b = next(i for i, d in enumerate(self.docs) if d.id == visible_ids[j])
        self.docs[a], self.docs[b] = self.docs[b], self.docs[a]
        self.save()

    def move_to_edge(self, doc_id: str, top: bool) -> None:
        d = self.by_id(doc_id)
        if d:
            self.docs.remove(d)
            self.docs.insert(0 if top else len(self.docs), d)
            self.save()

    def apply_order(self, ids: list[str], visible_ids: list[str]) -> None:
        """Re-order the visible subset into `ids`, keeping hidden docs where they are."""
        pos = [i for i, d in enumerate(self.docs) if d.id in set(visible_ids)]
        lookup = {d.id: d for d in self.docs}
        for slot, doc_id in zip(pos, ids):
            self.docs[slot] = lookup[doc_id]
        self.save()

    # ---- backup / restore (same layout as the Android app) ------------
    def backup(self, zip_path) -> int:
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("docs.json", json.dumps([d.to_json() for d in self.docs], indent=1))
            for d in self.docs:
                p = self.path_of(d)
                if p.exists():
                    z.write(p, "files/" + d.file_name)
        return len(self.docs)

    def restore(self, zip_path) -> int:
        safe = re.compile(r"^[A-Za-z0-9._-]+\.pdf$")
        with zipfile.ZipFile(zip_path) as z:
            names = z.namelist()
            if "docs.json" not in names:
                raise ValueError("This isn't a Personal Vault backup.")
            incoming = [Doc.from_json(o) for o in json.loads(z.read("docs.json").decode("utf-8"))]
            for n in names:
                base = n.rsplit("/", 1)[-1]
                if n.startswith("files/") and safe.match(base):
                    (self.docs_dir / base).write_bytes(z.read(n))
        have = {d.id for d in self.docs}
        added = [d for d in incoming if d.id not in have and self.path_of(d).exists()]
        self.docs.extend(added)
        self.save()
        return len(added)
