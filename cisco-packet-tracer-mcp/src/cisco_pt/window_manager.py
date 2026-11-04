"""Localización e inspección de la ventana de Cisco Packet Tracer.

Fase 0: solo lectura. Este módulo nunca mueve el ratón, no hace clic ni
escribe, y no activa la ventana.
"""

from __future__ import annotations

import glob
import os
from dataclasses import dataclass, asdict
from typing import Any

import win32api
import win32con
import win32gui
import win32process

import config

DWMWA_EXTENDED_FRAME_BOUNDS = 9


@dataclass
class WindowInfo:
    hwnd: int
    pid: int
    title: str
    exe: str
    left: int
    top: int
    right: int
    bottom: int
    width: int
    height: int
    visible: bool
    minimized: bool
    foreground: bool

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _process_path(pid: int) -> str:
    try:
        handle = win32api.OpenProcess(
            win32con.PROCESS_QUERY_INFORMATION | win32con.PROCESS_VM_READ, False, pid
        )
        try:
            return win32process.GetModuleFileNameEx(handle, 0)
        finally:
            win32api.CloseHandle(handle)
    except Exception:
        return ""


def _window_rect(hwnd: int) -> tuple[int, int, int, int]:
    """Rectángulo real del frame (excluye sombras de DWM si es posible)."""
    try:
        import ctypes
        from ctypes import wintypes

        rect = wintypes.RECT()
        ctypes.windll.dwmapi.DwmGetWindowAttribute(
            wintypes.HWND(hwnd),
            ctypes.c_uint(DWMWA_EXTENDED_FRAME_BOUNDS),
            ctypes.byref(rect),
            ctypes.sizeof(rect),
        )
        if rect.right > rect.left and rect.bottom > rect.top:
            return rect.left, rect.top, rect.right, rect.bottom
    except Exception:
        pass
    return win32gui.GetWindowRect(hwnd)


def _matches(title: str) -> bool:
    low = title.lower()
    return any(hint in low for hint in config.PT_TITLE_HINTS)


def _build(hwnd: int) -> WindowInfo:
    _, pid = win32process.GetWindowThreadProcessId(hwnd)
    left, top, right, bottom = _window_rect(hwnd)
    return WindowInfo(
        hwnd=hwnd,
        pid=pid,
        title=win32gui.GetWindowText(hwnd),
        exe=_process_path(pid),
        left=left,
        top=top,
        right=right,
        bottom=bottom,
        width=max(0, right - left),
        height=max(0, bottom - top),
        visible=bool(win32gui.IsWindowVisible(hwnd)),
        minimized=bool(win32gui.IsIconic(hwnd)),
        foreground=win32gui.GetForegroundWindow() == hwnd,
    )


def list_windows() -> list[WindowInfo]:
    """Todas las ventanas visibles cuyo proceso sea PacketTracer y el título coincida."""
    found: list[WindowInfo] = []

    def _cb(hwnd: int, _param: Any) -> bool:
        if not win32gui.IsWindowVisible(hwnd):
            return True
        title = win32gui.GetWindowText(hwnd)
        if not _matches(title):
            return True
        info = _build(hwnd)
        if os.path.basename(info.exe).lower().startswith(config.PT_PROCESS_NAME.lower()):
            found.append(info)
        return True

    win32gui.EnumWindows(_cb, None)
    found.sort(key=lambda w: w.width * w.height, reverse=True)
    return found


def find_main_window() -> WindowInfo | None:
    windows = list_windows()
    return windows[0] if windows else None


def detect_install() -> dict[str, Any]:
    """Versión y ruta del ejecutable instalado (sin abrir ni interactuar con PT)."""
    result: dict[str, Any] = {"found": False, "path": "", "version": "", "product": ""}
    candidates: list[str] = []
    for pattern in config.PT_INSTALL_GLOBS:
        for root in glob.glob(pattern):
            for rel in config.PT_EXE_RELATIVE:
                path = os.path.join(root, rel)
                if os.path.isfile(path):
                    candidates.append(path)
    # Fallback: ruta del proceso en ejecución.
    for win in list_windows():
        if win.exe and os.path.isfile(win.exe):
            candidates.append(win.exe)
    if not candidates:
        return result

    path = candidates[0]
    result.update(found=True, path=path)
    try:
        info = win32api.GetFileVersionInfo(path, "\\")
        ms, ls = info["FileVersionMS"], info["FileVersionLS"]
        result["version"] = f"{ms >> 16}.{ms & 0xFFFF}.{ls >> 16}.{ls & 0xFFFF}"
        for key in ("ProductName", "FileDescription"):
            try:
                result.setdefault("product", "")
                value = win32api.GetFileVersionInfo(path, f"\\StringFileInfo\\040904B0\\{key}")
                if value and not result["product"]:
                    result["product"] = value.strip("\x00").strip()
            except Exception:
                continue
    except Exception:
        pass
    return result


def status() -> dict[str, Any]:
    """Resumen compacto para `pt_status` / diagnóstico."""
    install = detect_install()
    windows = list_windows()
    return {
        "running": bool(windows),
        "install": install,
        "windows": [w.as_dict() for w in windows],
        "read_only": config.READ_ONLY,
    }


def image_to_client(hwnd: int, x: int, y: int) -> tuple[int, int]:
    """Convierte coordenadas de una captura de ventana a coordenadas de cliente.

    La captura usa el rectángulo DWM (sin bordes invisibles), que no coincide
    con el origen del cliente (barra de título). Sin esta conversión los clics
    caen desplazados.
    """
    dl, dt, _, _ = _window_rect(hwnd)
    cl, ct = win32gui.ClientToScreen(hwnd, (0, 0))
    return int(x - (cl - dl)), int(y - (ct - dt))


def modal_dialogs(hwnd: int) -> list[dict[str, Any]]:
    """Diálogos modales visibles del mismo proceso (p. ej. 'Open File')."""
    _, pid = win32process.GetWindowThreadProcessId(hwnd)
    found: list[dict[str, Any]] = []

    def _cb(h: int, _p: Any) -> bool:
        if h == hwnd or not win32gui.IsWindowVisible(h):
            return True
        _, wpid = win32process.GetWindowThreadProcessId(h)
        if wpid != pid:
            return True
        cls = win32gui.GetClassName(h)
        # Solo diálogos nativos; los tooltips de Qt también tienen owner.
        if cls in ("#32770", "#32769"):
            found.append({"hwnd": h, "class": cls, "title": win32gui.GetWindowText(h)})
        return True

    win32gui.EnumWindows(_cb, None)
    return found
