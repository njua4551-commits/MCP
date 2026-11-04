"""Cisco Packet Tracer MCP - servidor (Fase 1).

Herramientas: pt_status, pt_find_window, pt_capture.
Modo read_only: no hace clic, no escribe y no activa la ventana.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from mcp.server.mcpserver import Image, MCPServer

import config
from cisco_pt import capture, gui, window_manager as wm

server = MCPServer(
    name="cisco-packet-tracer-mcp",
    version="0.1.0",
    instructions=(
        "Automatiza Cisco Packet Tracer en Windows. Modo read_only por defecto: "
        "solo observa. Prefiere llamadas compuestas y evita pedir capturas si un "
        "resumen basta."
    ),
)


def _no_window() -> dict:
    return {
        "ok": False,
        "running": False,
        "error": "Packet Tracer no está abierto o su ventana no es visible",
        "next_action": "abrir Packet Tracer",
    }


@server.tool()
def pt_status() -> dict:
    """Versión instalada, proceso, ventana, resolución y modo de operación."""
    install = wm.detect_install()
    windows = wm.list_windows()
    main = windows[0] if windows else None
    return {
        "ok": True,
        "running": bool(main),
        "version": install.get("version", ""),
        "exe": install.get("path", ""),
        "window": None
        if main is None
        else {
            "hwnd": main.hwnd,
            "pid": main.pid,
            "title": main.title,
            "rect": [main.left, main.top, main.width, main.height],
            "minimized": main.minimized,
            "foreground": main.foreground,
        },
        "windows_found": len(windows),
        "read_only": config.READ_ONLY,
    }


@server.tool()
def pt_find_window() -> dict:
    """Localiza la ventana principal de Packet Tracer sin modificarla."""
    windows = wm.list_windows()
    if not windows:
        return _no_window()
    main = windows[0]
    return {
        "ok": True,
        "hwnd": main.hwnd,
        "pid": main.pid,
        "title": main.title,
        "exe": main.exe,
        "rect": [main.left, main.top, main.width, main.height],
        "visible": main.visible,
        "minimized": main.minimized,
        "foreground": main.foreground,
        "others": len(windows) - 1,
    }


def _parse_region(region: str | None, width: int, height: int) -> dict:
    """Región relativa a la ventana. 'topology' excluye barras y paleta."""
    if not region:
        return {"name": "full", "box": (0, 0, width, height)}
    key = region.strip().lower()
    if key == "topology":
        box = (int(width * 0.18), int(height * 0.12), int(width * 0.78), int(height * 0.78))
    elif key == "cli":
        box = (int(width * 0.30), int(height * 0.15), int(width * 0.65), int(height * 0.80))
    else:
        try:
            x, y, w, h = (int(v) for v in region.replace(" ", "").split(","))
            box = (x, y, w, h)
        except Exception:
            return {"name": "full", "box": (0, 0, width, height), "warning": "región inválida"}
    x, y, w, h = box
    x = max(0, min(x, width - 1))
    y = max(0, min(y, height - 1))
    return {"name": key, "box": (x, y, max(1, min(w, width - x)), max(1, min(h, height - y)))}


@server.tool()
def pt_capture(
    region: str | None = None,
    return_image: bool = False,
    save: bool = False,
) -> object:
    """Captura la ventana. Devuelve solo metadatos salvo return_image=True.

    region: None | 'topology' | 'cli' | 'x,y,w,h' (relativo a la ventana).
    """
    main = wm.find_main_window()
    if main is None:
        return _no_window()
    if main.minimized:
        return {
            "ok": False,
            "hwnd": main.hwnd,
            "error": "ventana minimizada",
            "next_action": "restaurar la ventana",
        }

    save_path = config.EVIDENCE_DIR / "capture-latest.png" if save else None
    shot = capture.capture_window(main.hwnd, save_path=save_path)
    if not shot.get("ok"):
        return {
            "ok": False,
            "hwnd": main.hwnd,
            "attempts": shot.get("attempts"),
            "error": "ningún método de captura devolvió un frame válido",
        }

    img = shot["image"]
    reg = _parse_region(region, img.width, img.height)
    x, y, w, h = reg["box"]
    cropped = img.crop((x, y, x + w, y + h)) if reg["name"] != "full" else img
    st = capture.stats(cropped)

    meta = {
        "ok": True,
        "hwnd": main.hwnd,
        "method": shot["method"],
        "region": reg["name"],
        "box": [x, y, w, h],
        "saved": shot.get("saved", ""),
        **st,
    }
    if reg.get("warning"):
        meta["warning"] = reg["warning"]
    if not return_image:
        return meta

    import io

    buf = io.BytesIO()
    cropped.save(buf, "PNG")
    return [meta, Image(data=buf.getvalue(), format="png")]


@server.tool()
def pt_open_file(path: str, confirm: bool = False) -> dict:
    """Abre un .pkt/.pka en Packet Tracer (Ctrl+O). Requiere confirm=True."""
    main = wm.find_main_window()
    if main is None:
        return _no_window()
    try:
        return gui.open_file(main.hwnd, path, confirm=confirm)
    except gui.InputBlocked as exc:
        return {"ok": False, "hwnd": main.hwnd, "blocked": True, "error": str(exc)}


@server.tool()
def pt_point_here() -> dict:
    """Coordenadas del cursor actual, relativas al cliente de Packet Tracer.

    Útil para calibrar posiciones sin capturas: el usuario coloca el ratón sobre
    el elemento y esta tool traduce a coordenadas de ventana.
    """
    main = wm.find_main_window()
    if main is None:
        return _no_window()
    import win32api
    import win32gui

    sx, sy = win32api.GetCursorPos()
    ox, oy = gui.client_origin(main.hwnd)
    return {
        "ok": True,
        "hwnd": main.hwnd,
        "client_xy": [int(sx - ox), int(sy - oy)],
        "screen_xy": [int(sx), int(sy)],
        "client_origin": [ox, oy],
    }


@server.tool()
def pt_focus_window() -> dict:
    """Activa Packet Tracer y verifica que quedó al frente (no hace clic)."""
    main = wm.find_main_window()
    if main is None:
        return _no_window()
    try:
        result = gui.focus_window(main.hwnd)
    except gui.InputBlocked as exc:
        return {"ok": False, "hwnd": main.hwnd, "error": str(exc)}
    return {"ok": result["ok"], "hwnd": main.hwnd, **result}


@server.tool()
def pt_click(x: int, y: int, double: bool = False, confirm: bool = False) -> dict:
    """Clic relativo al cliente de la ventana. Requiere confirm=True (acción real)."""
    main = wm.find_main_window()
    if main is None:
        return _no_window()
    try:
        return gui.click(main.hwnd, x, y, double=double, confirm=confirm)
    except gui.InputBlocked as exc:
        return {"ok": False, "hwnd": main.hwnd, "blocked": True, "error": str(exc)}


@server.tool()
def pt_type(text: str, enter: bool = False, confirm: bool = False) -> dict:
    """Escribe texto en Packet Tracer. Requiere confirm=True (acción real)."""
    main = wm.find_main_window()
    if main is None:
        return _no_window()
    try:
        return gui.type_text(main.hwnd, text, confirm=confirm, enter=enter)
    except gui.InputBlocked as exc:
        return {"ok": False, "hwnd": main.hwnd, "blocked": True, "error": str(exc)}


@server.tool()
def pt_wait(ms: int) -> dict:
    """Espera sin capturar ni interactuar."""
    return gui.wait(ms)


@server.tool()
def pt_open_device_cli(x: int, y: int, confirm: bool = False, wait_ms: int = 1500) -> dict:
    """Doble clic en (x,y) del lienzo y verifica localmente que la vista cambió.

    No escribe configuración. confirm=True es obligatorio (acción real).
    """
    main = wm.find_main_window()
    if main is None:
        return _no_window()
    before = capture.capture_window(main.hwnd)
    if not before.get("ok"):
        return {"ok": False, "hwnd": main.hwnd, "error": "captura previa no válida"}
    try:
        click_info = gui.click(main.hwnd, x, y, double=True, confirm=confirm)
    except gui.InputBlocked as exc:
        return {"ok": False, "hwnd": main.hwnd, "blocked": True, "error": str(exc)}
    gui.wait(wait_ms)
    after = capture.capture_window(main.hwnd)
    if not after.get("ok"):
        return {"ok": False, "hwnd": main.hwnd, "error": "captura posterior no válida"}

    ratio = capture.changed_ratio(before["image"], after["image"])
    opened = ratio > 0.02
    result = {
        "ok": opened,
        "hwnd": main.hwnd,
        "client_xy": [x, y],
        "changed_ratio": ratio,
        "still_foreground": click_info["still_foreground"],
        "step": "double_click+verify_view",
    }
    if not opened:
        result["error"] = "la vista no cambió: el doble clic no abrió ninguna ventana de dispositivo"
        result["next_action"] = "ajustar coordenadas o verificar que el lienzo está en primer plano"
    return result


if __name__ == "__main__":
    server.run()