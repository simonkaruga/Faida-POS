"""A printout as data, and how to turn it into ESC/POS bytes or plain text.

A document is a list of rows, stored with the ticket so reprints match the original:

    {"text": "TABLE 2", "size": 2, "bold": True, "align": "center"}
    {"cols": ["2x Tusker", "600"]}      left and right aligned on one line
    {"rule": True}                       a dashed line
"""

from typing import Any

Row = dict[str, Any]

WIDTH = 48  # characters per line on an 80 mm printer (font A)

ESC, GS = b"\x1b", b"\x1d"
INIT = ESC + b"@"
CUT = b"\n\n\n" + GS + b"VB\x03"
OPEN_DRAWER = ESC + b"p\x00\x19\xfa"
ALIGN = {"left": 0, "center": 1, "right": 2}


def text(value: str, *, size: int = 1, bold: bool = False, align: str = "left") -> Row:
    return {"text": value, "size": size, "bold": bold, "align": align}


def cols(left: str, right: str, *, size: int = 1, bold: bool = False) -> Row:
    return {"cols": [left, right], "size": size, "bold": bold}


def rule() -> Row:
    return {"rule": True}


def _wrap(value: str, width: int) -> list[str]:
    if len(value) <= width:
        return [value]
    indent = value[: len(value) - len(value.lstrip())]
    words, lines, line = value.split(), [], indent
    for word in words:
        while len(word) > width:
            if line:
                lines.append(line)
                line = ""
            lines.append(word[:width])
            word = word[width:]
        if not line:
            line = word
        elif len(line) + 1 + len(word) <= width:
            line += " " + word
        else:
            lines.append(line)
            line = word
    lines.append(line)
    return lines


def _lines(row: Row) -> list[str]:
    width = WIDTH // row.get("size", 1)
    if row.get("rule"):
        return ["-" * WIDTH]
    if "cols" in row:
        left, right = row["cols"]
        wrapped = _wrap(left, width - len(right) - 1)
        wrapped[-1] = wrapped[-1].ljust(width - len(right)) + right
        return wrapped
    return _wrap(row["text"], width)


def to_text(doc: list[Row]) -> str:
    out = []
    for row in doc:
        width = WIDTH // row.get("size", 1)
        for line in _lines(row):
            align = row.get("align", "left")
            out.append(line.center(width) if align == "center" else line.rjust(width) if align == "right" else line)
    return "\n".join(out)


def to_escpos(doc: list[Row]) -> bytes:
    out = bytearray(INIT)
    for row in doc:
        size = row.get("size", 1)
        out += ESC + b"a" + bytes([ALIGN[row.get("align", "left")]])
        out += ESC + b"E" + bytes([1 if row.get("bold") else 0])
        out += GS + b"!" + bytes([0x11 if size == 2 else 0x00])
        for line in _lines(row):
            out += line.encode("cp437", errors="replace") + b"\n"
    out += CUT
    return bytes(out)
