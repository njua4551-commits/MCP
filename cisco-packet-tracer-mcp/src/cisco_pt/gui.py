"""Control visual seguro de la ventana de Packet Tracer.

Reglas (secciones 1, 6 y 8 del .md):
  * Nunca se escribe ni se hace clic si Packet Tracer no es la ventana activa.
  * Las coordenadas son relativas al cliente de la ventana, no absolutas.
  * Toda entrada está bloqueada salvo habilitación explícita (`ALLOW_INPUT`).
  * Máximo un reintento y solo en acciones idempotentes.
"""

from __future__ import annotations

import time
from typing import Any

import pyautogui
import win32api
import win32con
import win32gui
import win32process

import config
from . import window_manager as wm

pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.03


class InputBlocked(RuntimeError):
    """Se intentó una entrada sin permiso o sobre la ventana equivocada."""


def _assert_pt(hwnd: int) -> None:
    if not win32gui.IsWindow(hwnd):
        raise InputBlocked(f"hwnd {hwnd} no existe")
    _, pid = win32process.GetWindowThreadProcessId(hwnd)
    try:
        exe = win32process.GetModuleFileNameEx(
            win32api.OpenProcess(win32con.PROCESS_QUERY_INFORMATION | win32con.PROCESS_VM_READ, False, pid),
            0,
        )
    except Exception:
        exe = ""
    if exe and not exe.lower().endswith(config.PT_PROCESS_NAME.lower() + ".exe"):
        raise InputBlocked(f"el proceso de hwnd {hwnd} no es Packet Tracer ({exe})")


def foreground_is(hwnd: int) -> bool:
    return win32gui.GetForegroundWindow() == hwnd


def focus_window(hwnd: int) -> dict[str, Any]:
    """Activa la ventana y verifica que quedó al frente. No hace clic."""
    _assert_pt(hwnd)
    was_foreground = foreground_is(hwnd)
    ok = _force_foreground(hwnd)
    time.sleep(0.2)
    return {
        "ok": ok,
        "hwnd": hwnd,
        "was_foreground": was_foreground,
        "foreground": win32gui.GetWindowText(win32gui.GetForegroundWindow()),
        "minimized": bool(win32gui.IsIconic(hwnd)),
    }


def _force_foreground(hwnd: int) -> bool:
    if win32gui.IsIconic(hwnd):
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        time.sleep(0.4)
    win32gui.SetForegroundWindow(hwnd)
    if foreground_is(hwnd):
        return True
    # Fallback clásico: adjuntar el hilo del foreground actual.
    fg = win32gui.GetForegroundWindow()
    target_thread = win32process.GetWindowThreadProcessId(hwnd)[0]
    current_thread = win32api.GetCurrentThreadId()
    fg_thread = win32process.GetWindowThreadProcessId(fg)[0] if fg else 0
    try:
        if fg_thread:
            win32process.AttachThreadInput(fg_thread, current_thread, True)
        win32process.AttachThreadInput(target_thread, current_thread, True)
        win32gui.BringWindowToTop(hwnd)
        win32gui.SetForegroundWindow(hwnd)
    finally:
        if fg_thread:
            win32process.AttachThreadInput(fg_thread, current_thread, False)
        win32process.AttachThreadInput(target_thread, current_thread, False)
    return foreground_is(hwnd)


def client_origin(hwnd: int) -> tuple[int, int]:
    left, top = win32gui.ClientToScreen(hwnd, (0, 0))
    return int(left), int(top)


def click(hwnd: int, x: int, y: int, double: bool = False, confirm: bool = False) -> dict[str, Any]:
    """Clic relativo al cliente de la ventana. Requiere confirm=True."""
    if config.READ_ONLY and not confirm:
        raise InputBlocked("modo read_only: se requiere confirm=True para hacer clic")
    _assert_pt(hwnd)
    dialogs = wm.modal_dialogs(hwnd)
    if dialogs:
        raise InputBlocked(
            "hay un diálogo modal abierto "
            f"({dialogs[0]['title']}); ciérralo antes de hacer clic"
        )
    if not focus_window(hwnd)["ok"]:
        raise InputBlocked("Packet Tracer no pudo quedar en primer plano; no se hace clic")

    ox, oy = client_origin(hwnd)
    ax, ay = ox + int(x), oy + int(y)
    if double:
        pyautogui.click(ax, ay, clicks=2, interval=0.12)
    else:
        pyautogui.click(ax, ay)
    time.sleep(0.3)
    return {
        "ok": True,
        "action": "double_click" if double else "click",
        "client_xy": [int(x), int(y)],
        "screen_xy": [ax, ay],
        "still_foreground": foreground_is(hwnd),
    }


def type_text(hwnd: int, text: str, confirm: bool = False, enter: bool = False) -> dict[str, Any]:
    """Escribe texto ASCII en la ventana activa. Requiere confirm=True."""
    if config.READ_ONLY and not confirm:
        raise InputBlocked("modo read_only: se requiere confirm=True para escribir")
    _assert_pt(hwnd)
    if not foreground_is(hwnd):
        raise InputBlocked("Packet Tracer no está en primer plano; no se escribe")
    if len(text) > config.MAX_CLI_OUTPUT_CHARS:
        raise InputBlocked("texto demasiado largo")
    pyautogui.write(text, interval=0.02)
    if enter:
        pyautogui.press("enter")
    return {"ok": True, "chars": len(text), "enter": enter, "still_foreground": foreground_is(hwnd)}


def press(hwnd: int, key: str, confirm: bool = False) -> dict[str, Any]:
    if config.READ_ONLY and not confirm:
        raise InputBlocked("modo read_only: se requiere confirm=True para pulsar teclas")
    _assert_pt(hwnd)
    if not foreground_is(hwnd):
        raise InputBlocked("Packet Tracer no está en primer plano; no se pulsa nada")
    pyautogui.press(key)
    return {"ok": True, "key": key, "still_foreground": foreground_is(hwnd)}


def wait(ms: int) -> dict[str, Any]:
    ms = max(0, min(int(ms), 120_000))
    time.sleep(ms / 1000.0)
    return {"ok": True, "waited_ms": ms}


def open_file(hwnd: int, path: str, confirm: bool = False) -> dict[str, Any]:
    """Abre un .pkt/.pka usando Ctrl+O y el diálogo nativo de Windows.

    Solo escribe la ruta en el diálogo, nunca guarda ni sobrescribe.
    """
    import os

    if config.READ_ONLY and not confirm:
        raise InputBlocked("modo read_only: se requiere confirm=True para abrir un archivo")
    _assert_pt(hwnd)
    path = os.path.abspath(path)
    if not os.path.isfile(path):
        raise InputBlocked(f"no existe el archivo: {path}")
    if not path.lower().endswith((".pkt", ".pka")):
        raise InputBlocked("solo se aceptan archivos .pkt o .pka")

    if not focus_window(hwnd)["ok"]:
        raise InputBlocked("Packet Tracer no está en primer plano")

    title_before = win32gui.GetWindowText(hwnd)
    pyautogui.hotkey("ctrl", "o")

    dialog = None
    for _ in range(30):
        time.sleep(0.1)
        dialogs = wm.modal_dialogs(hwnd)
        if dialogs:
            dialog = dialogs[0]["hwnd"]
            break
    if dialog is None:
        raise InputBlocked("no apareció el diálogo de abrir archivo")

    _force_foreground(dialog)
    time.sleep(0.2)
    pyautogui.write(path, interval=0.01)
    time.sleep(0.2)
    pyautogui.press("enter")

    for _ in range(120):
        time.sleep(0.1)
        if not win32gui.IsWindow(dialog) or not win32gui.IsWindowVisible(dialog):
            break
    closed = not (win32gui.IsWindow(dialog) and win32gui.IsWindowVisible(dialog))
    time.sleep(0.8)
    title_after = win32gui.GetWindowText(hwnd)
    return {
        "ok": closed,
        "path": path,
        "dialog_closed": closed,
        "title_before": title_before,
        "title_after": title_after,
        "title_changed": title_before != title_after,
        "foreground": win32gui.GetWindowText(win32gui.GetForegroundWindow()),
    }
