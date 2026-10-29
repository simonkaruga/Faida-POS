"""Printer connections, chosen at install time by a spec string:

    file:prints              development: writes readable .txt files into a folder
    device:/dev/usb/lp0      USB printer on Linux
    windows:XP-80C           Windows: the printer of that name (or share name) in Windows'
                             list, through the print spooler (raw ESC/POS)
    device:\\\\localhost\\POS80   Windows: the same, by its share name
    network:192.168.1.50     network printer, port 9100 unless given (host:port)
    none                     no printer here: everything shows as "Not printed"
    POS80                    just a name: on Windows, as windows:POS80

The paper width (80 or 58 mm) sets how many characters fit on a line.
"""

import logging
import os
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


PRINTER_ATTRIBUTE_WORK_OFFLINE = 0x400
PRINTER_STATUS_OFFLINE = 0x80


def windows_printers() -> list[dict]:
    """Windows' printers (name, share name, port, status), through pywin32."""
    import win32print

    flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
    return list(win32print.EnumPrinters(flags, None, 2))


def find_windows_printer(wanted: str, printers: list[dict]) -> dict:
    """The printer named `wanted` (its name or its share name). If none is, and there is
    exactly one printer on a USB port, that one: the counter's receipt printer."""
    for p in printers:
        if wanted.lower() in ((p.get("pPrinterName") or "").lower(), (p.get("pShareName") or "").lower()):
            return p
    usb = [p for p in printers if (p.get("pPortName") or "").upper().startswith("USB")]
    if len(usb) == 1:
        logging.getLogger("faida.printing").warning("No printer called %s: using the USB printer %s", wanted, usb[0]["pPrinterName"])
        return usb[0]
    names = ", ".join(p["pPrinterName"] for p in printers) or "none"
    raise PrinterError(f"No printer called {wanted} in Windows (printers: {names})")


class WindowsPrinter(EscposPrinter):
    """A printer in Windows' own list: raw ESC/POS through the print spooler. Works for the
    SYSTEM account the counter runs as, without sharing the printer on the network."""

    def __init__(self, name: str):
        self.name = name

    def _send(self, data: bytes) -> None:
        import pywintypes
        import win32print

        try:
            p = find_windows_printer(self.name, windows_printers())
            if p.get("Attributes", 0) & PRINTER_ATTRIBUTE_WORK_OFFLINE:
                raise PrinterError(f"Windows has {p['pPrinterName']} set to 'Use Printer Offline': open its print queue "
                                   "(Settings > Printers & scanners > Open queue) and untick it in the Printer menu")
            if p.get("Status", 0) & PRINTER_STATUS_OFFLINE:
                raise PrinterError(f"{p['pPrinterName']} is offline: check power, paper and the USB cable")
            handle = win32print.OpenPrinter(p["pPrinterName"])
            try:
                win32print.StartDocPrinter(handle, 1, ("Faida", None, "RAW"))
                try:
                    win32print.StartPagePrinter(handle)
                    win32print.WritePrinter(handle, data)
                    win32print.EndPagePrinter(handle)
                finally:
                    win32print.EndDocPrinter(handle)
            finally:
                win32print.ClosePrinter(handle)
        except pywintypes.error as e:
            raise PrinterError(f"Printer {self.name} not reachable ({e.strerror})") from e


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


def make_printer(spec: str, name: str, paper_mm: int = 80, windows: bool = os.name == "nt") -> Printer:
    if paper_mm not in COLUMNS:
        raise ValueError(f"Paper width must be 80 or 58 mm, not {paper_mm}")
    kind, _, target = spec.partition(":")
    local_share = re.fullmatch(r"(?i)\\\\(?:localhost|127\.0\.0\.1)\\(.+)", target) if kind == "device" else None
    if kind == "file":
        printer = FilePrinter(target or "prints", name)
    elif kind == "windows" and target:
        printer = WindowsPrinter(target)
    elif windows and local_share:
        # Installs up to 0.3.3 wrote device:\\localhost\POS80: the spooler, not the share.
        printer = WindowsPrinter(local_share.group(1))
    elif kind == "device" and target:
        printer = DevicePrinter(target)
    elif kind == "network" and target:
        host, _, port = target.partition(":")
        printer = NetworkPrinter(host, int(port or 9100))
    elif kind == "none":
        return NoPrinter()
    elif re.fullmatch(r"[\w .-]+", spec):
        # A bare name, as typed at install ("POS80").
        printer = WindowsPrinter(spec) if windows else DevicePrinter(rf"\\localhost\{spec}")
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
