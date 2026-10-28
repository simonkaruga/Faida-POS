"""Printer connections, chosen at install time by a spec string:

    file:prints              development: writes readable .txt files into a folder
    device:/dev/usb/lp0      USB printer on Linux
    device:\\\\localhost\\POS80   shared printer on Windows (raw)
    network:192.168.1.50     network printer, port 9100 unless given (host:port)
    none                     no printer here: everything shows as "Not printed"
    POS80                    just a name: the Windows printer shared as POS80 (\\localhost\POS80)

The paper width (80 or 58 mm) sets how many characters fit on a line.
"""

import logging
import re
import socket
from datetime import datetime
from pathlib import Path
from typing import Protocol

from app.printing.document import COLUMNS, OPEN_DRAWER, WIDTH, Row, text, to_escpos, to_text


class PrinterError(Exception):
    pass


class Printer(Protocol):
    def print(self, doc: list[Row]) -> None: ...
    def open_drawer(self) -> None: ...


class EscposPrinter:
    width = WIDTH

    def print(self, doc: list[Row]) -> None:
        self._send(to_escpos(doc, self.width))

    def open_drawer(self) -> None:
        self._send(OPEN_DRAWER)

    def _send(self, data: bytes) -> None:
        raise NotImplementedError


class DevicePrinter(EscposPrinter):
    def __init__(self, path: str):
        self.path = path

    def _send(self, data: bytes) -> None:
        try:
            with open(self.path, "wb") as device:
                device.write(data)
        except OSError as e:
            raise PrinterError(f"Printer not reachable ({e.strerror or e})") from e


class NetworkPrinter(EscposPrinter):
    def __init__(self, host: str, port: int = 9100, timeout: float = 4.0):
        self.host, self.port, self.timeout = host, port, timeout

    def _send(self, data: bytes) -> None:
        try:
            with socket.create_connection((self.host, self.port), timeout=self.timeout) as conn:
                conn.sendall(data)
        except OSError as e:
            raise PrinterError(f"Printer not reachable at {self.host}") from e


class FilePrinter:
    width = WIDTH

    def __init__(self, folder: str, name: str):
        self.folder, self.name = Path(folder), name

    def print(self, doc: list[Row]) -> None:
        self._write(to_text(doc, self.width))

    def open_drawer(self) -> None:
        self._write(to_text([text("[ cash drawer opened ]")]))

    def _write(self, content: str) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        (self.folder / f"{stamp}-{self.name}.txt").write_text(content + "\n", encoding="utf-8")


class NoPrinter:
    def print(self, doc: list[Row]) -> None:
        raise PrinterError("No printer set up")

    def open_drawer(self) -> None:
        pass


def make_printer(spec: str, name: str, paper_mm: int = 80) -> Printer:
    if paper_mm not in COLUMNS:
        raise ValueError(f"Paper width must be 80 or 58 mm, not {paper_mm}")
    kind, _, target = spec.partition(":")
    if kind == "file":
        printer = FilePrinter(target or "prints", name)
    elif kind == "device" and target:
        printer = DevicePrinter(target)
    elif kind == "network" and target:
        host, _, port = target.partition(":")
        printer = NetworkPrinter(host, int(port or 9100))
    elif kind == "none":
        return NoPrinter()
    elif re.fullmatch(r"[\w .-]+", spec):
        # A bare share name, as typed at install ("POS80").
        printer = DevicePrinter(rf"\\localhost\{spec}")
    else:
        raise ValueError(f"Unknown printer setting {spec!r}")
    printer.width = COLUMNS[paper_mm]
    return printer


def printer_or_none(spec: str, name: str, paper_mm: int = 80) -> Printer:
    """make_printer, but a setting it can't understand never stops the counter from
    starting: that printer then shows as offline, and the log says why."""
    try:
        return make_printer(spec, name, paper_mm)
    except ValueError as e:
        logging.getLogger("faida.printing").error("The %s printer is not set up: %s", name, e)
        return NoPrinter()
