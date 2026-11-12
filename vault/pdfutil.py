"""All PDF work: password handling, rendering, thumbnails, photo -> PDF, A4 merge."""
from __future__ import annotations

try:
    import pymupdf as fitz
except ImportError:  # older PyMuPDF
    import fitz  # type: ignore

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
from PySide6.QtGui import QImage, QImageReader

A4_W, A4_H = 595.0, 842.0


class NeedPassword(Exception):
    def __init__(self, wrong: bool = False, title: str = ""):
        super().__init__("password required")
        self.wrong = wrong
        self.title = title


def open_pdf(path, password: str = ""):
    d = fitz.open(str(path))
    if d.needs_pass:
        if not password or not d.authenticate(password):
            d.close()
            raise NeedPassword(bool(password))
    return d


def to_qimage(pix) -> QImage:
    fmt = QImage.Format_RGB888 if pix.n == 3 else QImage.Format_RGBA8888
    return QImage(pix.samples, pix.width, pix.height, pix.stride, fmt).copy()


def render_page(doc, index: int, zoom: float) -> QImage:
    pix = doc[index].get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
    return to_qimage(pix)


def page_size(doc, index: int = 0) -> tuple[float, float]:
    r = doc[index].rect
    return r.width, r.height


def thumbnail(path, password: str, width: int = 360) -> QImage | None:
    """First page as an image, or None if it can't be opened (e.g. needs a password)."""
    try:
        d = open_pdf(path, password)
    except Exception:
        return None
    try:
        if len(d) == 0:
            return None
        r = d[0].rect
        z = width / max(r.width, 1)
        return render_page(d, 0, z)
    except Exception:
        return None
    finally:
        d.close()


def info(path, password: str) -> tuple[int | None, bool]:
    """(page count or None, locked)"""
    try:
        d = open_pdf(path, password)
        n = len(d)
        d.close()
        return n, False
    except NeedPassword:
        return None, True
    except Exception:
        return None, False


def sniff_is_pdf(path) -> bool:
    try:
        with open(path, "rb") as f:
            return f.read(1024).find(b"%PDF") >= 0
    except OSError:
        return False


def image_to_pdf(src, out) -> None:
    """Photo -> single-page PDF, A4 wide, respecting EXIF rotation."""
    reader = QImageReader(str(src))
    reader.setAutoTransform(True)
    img = reader.read()
    if img.isNull():
        raise ValueError("Not an image")
    if max(img.width(), img.height()) > 2400:
        img = img.scaled(2400, 2400, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.WriteOnly)
    img.convertToFormat(QImage.Format_RGB888).save(buf, "JPG", 92)
    buf.close()
    pdf = fitz.open()
    ph = max(1.0, A4_W * img.height() / img.width())
    page = pdf.new_page(width=A4_W, height=ph)
    page.insert_image(fitz.Rect(0, 0, A4_W, ph), stream=bytes(ba))
    pdf.save(str(out), garbage=3, deflate=True)
    pdf.close()


def merge_to_a4(items: list[tuple[object, str, str]], out) -> None:
    """items = [(path, password, title)]. Every page lands on an A4 sheet, scaled to fit, centred."""
    dest = fitz.open()
    srcs = []
    try:
        for path, pw, title in items:
            try:
                s = open_pdf(path, pw)
            except NeedPassword:
                raise NeedPassword(True, title) from None
            srcs.append(s)
            for i in range(len(s)):
                r = s[i].rect
                w, h = max(r.width, 1), max(r.height, 1)
                k = min(A4_W / w, A4_H / h)
                tw, th = w * k, h * k
                x, y = (A4_W - tw) / 2, (A4_H - th) / 2
                page = dest.new_page(width=A4_W, height=A4_H)
                page.show_pdf_page(fitz.Rect(x, y, x + tw, y + th), s, i)
        dest.save(str(out), garbage=3, deflate=True)
    finally:
        for s in srcs:
            s.close()
        dest.close()
