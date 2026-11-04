"""Fase 0 - Descubrimiento: versión, ventana y captura válida de Packet Tracer.

No mueve el ratón, no hace clic y no escribe en Packet Tracer.
Uso:  .venv\\Scripts\\python.exe tests\\fase0_check.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

import win32api
import win32gui

import config
from cisco_pt import capture, window_manager as wm


def main() -> int:
    cursor_before = win32api.GetCursorPos()
    foreground_before = win32gui.GetForegroundWindow()

    report: dict = {"phase": 0, "read_only": config.READ_ONLY}
    install = wm.detect_install()
    report["install"] = install

    win = wm.find_main_window()
    if win is None:
        report.update(
            ok=False,
            error="Packet Tracer no está abierto (o no se detectó su ventana)",
            next_action="abrir Packet Tracer y reintentar",
        )
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1

    report["window"] = {
        "hwnd": win.hwnd,
        "pid": win.pid,
        "title": win.title,
        "rect": [win.left, win.top, win.width, win.height],
        "visible": win.visible,
        "minimized": win.minimized,
        "foreground": win.foreground,
    }

    if win.minimized:
        report.update(
            ok=False,
            error="la ventana está minimizada; no se captura sin interactuar",
            next_action="restaurar la ventana manualmente",
        )
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1

    shot = capture.capture_window(
        win.hwnd, save_path=config.EVIDENCE_DIR / "001-topologia-inicial.png"
    )
    report["capture"] = {k: v for k, v in shot.items() if k != "image"}

    # Comprobación de no-intrusión: el script no debe alterar foco ni cursor.
    report["no_side_effects"] = {
        "cursor_moved": win32api.GetCursorPos() != cursor_before,
        "foreground_changed": win32gui.GetForegroundWindow() != foreground_before,
    }

    report["ok"] = bool(shot.get("ok")) and not any(report["no_side_effects"].values())
    if not report["ok"] and "error" not in report:
        report["error"] = "ningún método de captura devolvió un frame válido"
        report["next_action"] = "revisar attempts y probar captura manual"

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
