"""Plain data model. Field names in JSON match the Android app so backups are interchangeable."""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

# key -> (label, default gradient index)
TYPES = {
    "AADHAAR": ("Aadhaar Card", 0),
    "PAN": ("PAN Card", 1),
    "VOTER": ("Voter ID", 2),
    "DL": ("Driving Licence", 3),
    "LL": ("Learner's Licence", 4),
    "PASSPORT": ("Passport", 6),
    "RATION": ("Ration Card", 8),
    "RC": ("Vehicle RC", 10),
    "INSURANCE": ("Insurance", 12),
    "PASSBOOK": ("Bank Passbook", 14),
    "CERT": ("Certificate", 16),
    "OTHER": ("Other / Custom", 5),
}

GRADIENTS = [
    ["#FF6A00", "#EE8A4A", "#1B9E3E"], ["#1E3AFF", "#3B1F9E", "#E91EE6"], ["#0F766E", "#14B8A6"],
    ["#F28B6B", "#E5546B"], ["#6A5ACD", "#9D8CFF"], ["#232526", "#414345"],
    ["#0F2027", "#203A43", "#2C5364"], ["#8A6A00", "#E6B422"], ["#11998E", "#38EF7D"],
    ["#C31432", "#240B36"], ["#134E5E", "#71B280"], ["#FF512F", "#DD2476"],
    ["#4776E6", "#8E54E9"], ["#00B4DB", "#0083B0"], ["#41295A", "#2F0743"],
    ["#FDC830", "#F37335"], ["#D31027", "#EA384D"], ["#1D976C", "#93F9B9"],
    ["#667EEA", "#764BA2"], ["#FF9966", "#FF5E62"], ["#2193B0", "#6DD5ED"],
    ["#373B44", "#4286F4"], ["#B24592", "#F15F79"], ["#0F0C29", "#302B63", "#24243E"],
]


def argb_to_hex(v: int) -> str:
    return "#%06X" % ((v & 0xFFFFFFFF) & 0xFFFFFF)


def rgb_to_argb(r: int, g: int, b: int) -> int:
    v = 0xFF000000 | (r << 16) | (g << 8) | b
    return v - (1 << 32) if v >= (1 << 31) else v


@dataclass
class Doc:
    id: str
    title: str
    type: str = "OTHER"
    custom_type: str = ""
    number: str = ""
    gradient: int = 0
    custom_a: int = 0
    custom_b: int = 0
    file_name: str = ""
    password: str = ""
    added: float = field(default_factory=time.time)

    @property
    def type_label(self) -> str:
        if self.type == "OTHER" and self.custom_type.strip():
            return self.custom_type.strip()
        return TYPES.get(self.type, TYPES["OTHER"])[0]

    def colors_hex(self) -> list[str]:
        if self.custom_a != 0:
            return [argb_to_hex(self.custom_a), argb_to_hex(self.custom_b)]
        return GRADIENTS[self.gradient % len(GRADIENTS)]

    def to_json(self) -> dict:
        return {
            "id": self.id, "title": self.title, "type": self.type, "ctype": self.custom_type,
            "number": self.number, "gradient": self.gradient, "ca": self.custom_a, "cb": self.custom_b,
            "file": self.file_name, "pw": self.password, "added": self.added,
        }

    @staticmethod
    def from_json(o: dict) -> "Doc":
        t = o.get("type", "OTHER")
        return Doc(
            id=o["id"], title=o.get("title", "Untitled"), type=t if t in TYPES else "OTHER",
            custom_type=o.get("ctype", ""), number=o.get("number", ""), gradient=int(o.get("gradient", 0)),
            custom_a=int(o.get("ca", 0)), custom_b=int(o.get("cb", 0)), file_name=o["file"],
            password=o.get("pw", ""), added=float(o.get("added", time.time())),
        )


def mask_number(n: str) -> str:
    c = "".join(ch for ch in n if ch.isalnum())
    return "•••• " + c[-4:] if c else ""


def format_number(n: str) -> str:
    t = n.strip()
    if len(t) == 12 and t.isdigit():
        return " ".join(t[i:i + 4] for i in range(0, 12, 4))
    return t


def matches(d: Doc, q: str) -> bool:
    s = q.strip().lower()
    if not s:
        return True
    sq = s.replace(" ", "")
    return (s in d.title.lower() or s in d.type_label.lower()
            or sq in d.number.lower().replace(" ", ""))


def guess_type(name: str) -> str:
    n = name.lower()
    word = lambda w: re.search(r"(^|[^a-z])" + w + r"([^a-z]|$)", n) is not None
    if "aadhaar" in n or "aadhar" in n:
        return "AADHAAR"
    if "passport" in n:
        return "PASSPORT"
    if "voter" in n or word("epic"):
        return "VOTER"
    if "learner" in n:
        return "LL"
    if "licen" in n or word("dl"):
        return "DL"
    if word("pan"):
        return "PAN"
    if "ration" in n:
        return "RATION"
    if "insurance" in n or "policy" in n:
        return "INSURANCE"
    return "AADHAAR"
