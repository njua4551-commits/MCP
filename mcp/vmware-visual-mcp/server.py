import ctypes
import json
import os
import re
import subprocess
import time
from datetime import datetime
from pathlib import Path

import pyautogui
import pyperclip
import win32com.client
import win32con
import win32gui
import win32ui
from mcp.server.fastmcp import FastMCP, Image
from PIL import Image as PILImage

mcp = FastMCP("vmware-visual-mcp")

EVIDENCE = Path(__file__).parent / "evidence"
EVIDENCE.mkdir(exist_ok=True)

VMRUN = Path(
    os.environ.get(
        "VMRUN_PATH",
        r"C:\Program Files\VMware\VMware Workstation\vmrun.exe",
    )
)

pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.3

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    pass


def _find_window(title_part: str):
    """Ventanas visibles cuyo título contiene title_part (sin distinguir mayúsculas), la más grande primero."""
    found = []

    def callback(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return
        title = win32gui.GetWindowText(hwnd)
        if title and title_part.lower() in title.lower():
            left, top, right, bottom = win32gui.GetWindowRect(hwnd)
            found.append((hwnd, title, (right - left) * (bottom - top)))

    win32gui.EnumWindows(callback, None)
    found.sort(key=lambda item: item[2], reverse=True)
    return found


def _window_rect(hwnd):
    """Devuelve (izquierda, arriba, ancho, alto) de la ventana en coordenadas de pantalla."""
    left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    return left, top, right - left, bottom - top


def _visible_rect(hwnd):
    """Rectángulo visible de la ventana en pantalla, recortado a los bordes."""
    left, top, width, height = _window_rect(hwnd)
    screen_width = ctypes.windll.user32.GetSystemMetrics(0)
    screen_height = ctypes.windll.user32.GetSystemMetrics(1)

    left = max(left, 0)
    top = max(top, 0)
    width = min(width, screen_width - left)
    height = min(height, screen_height - top)
    return left, top, width, height


def _activate_window(hwnd) -> bool:
    """Restaura la ventana si está minimizada y la trae al frente. Devuelve si quedó activa."""
    if win32gui.IsIconic(hwnd):
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)

    if win32gui.GetForegroundWindow() == hwnd:
        time.sleep(0.1)
        return True

    # Windows puede rechazar SetForegroundWindow si otra app tiene el foco.
    for attempt in (
        lambda: win32gui.SetForegroundWindow(hwnd),
        lambda: win32gui.BringWindowToTop(hwnd),
        lambda: ctypes.windll.user32.SwitchToThisWindow(hwnd, True),
        lambda: win32com.client.Dispatch("WScript.Shell").AppActivate(
            win32gui.GetWindowText(hwnd)
        ),
    ):
        try:
            attempt()
        except Exception:
            continue
        time.sleep(0.25)
        if win32gui.GetForegroundWindow() == hwnd:
            return True

    time.sleep(0.25)
    return win32gui.GetForegroundWindow() == hwnd


def _is_mostly_black(img: PILImage.Image, threshold: float = 0.85) -> bool:
    """True si casi toda la imagen es negra (síntoma típico de PrintWindow sin contenido)."""
    histogram = img.convert("L").histogram()
    total = sum(histogram)
    return total > 0 and sum(histogram[:15]) / total >= threshold


def _screen_capture(hwnd) -> PILImage.Image:
    """Captura la ventana desde la pantalla real. Necesario para ver el escritorio del invitado."""
    if not _activate_window(hwnd):
        title = win32gui.GetWindowText(hwnd)
        raise RuntimeError(
            f"No se pudo traer '{title}' al frente para capturarla. "
            "Haz clic en la ventana y vuelve a intentarlo."
        )

    left, top, width, height = _visible_rect(hwnd)
    if width <= 0 or height <= 0:
        raise RuntimeError("La ventana está fuera de la pantalla y no se puede capturar.")

    return pyautogui.screenshot(region=(left, top, width, height))


def _capture_window(window_title: str) -> PILImage.Image:
    """Captura una ventana. Para VMware usa la pantalla real, porque PrintWindow devuelve el invitado en negro."""
    matches = _find_window(window_title)
    if not matches:
        raise RuntimeError(
            f"No se encontró ninguna ventana visible con '{window_title}'. Usa list_windows."
        )

    hwnd, title, _ = matches[0]

    # VMware dibuja el escritorio del invitado con aceleración GPU: PrintWindow solo
    # captura los bordes de la aplicación. Capturar la pantalla sí muestra el invitado.
    if "vmware" in title.lower():
        return _screen_capture(hwnd)

    if win32gui.IsIconic(hwnd):
        raise RuntimeError(
            f"La ventana '{title}' está minimizada y no se puede capturar. "
            "Puede estar tapada por otras, pero no minimizada."
        )

    left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    width, height = right - left, bottom - top
    if width <= 0 or height <= 0:
        raise RuntimeError(f"La ventana '{title}' tiene tamaño no válido ({width}x{height}).")

    hwnd_dc = win32gui.GetWindowDC(hwnd)
    mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
    save_dc = mfc_dc.CreateCompatibleDC()
    bitmap = win32ui.CreateBitmap()
    img = None
    ok = False
    try:
        bitmap.CreateCompatibleBitmap(mfc_dc, width, height)
        save_dc.SelectObject(bitmap)
        # Flag 2 = PW_RENDERFULLCONTENT (incluye contenido acelerado por GPU)
        ok = ctypes.windll.user32.PrintWindow(hwnd, save_dc.GetSafeHdc(), 2)
        info = bitmap.GetInfo()
        bits = bitmap.GetBitmapBits(True)
        img = PILImage.frombuffer(
            "RGB", (info["bmWidth"], info["bmHeight"]), bits, "raw", "BGRX", 0, 1
        )
    finally:
        win32gui.DeleteObject(bitmap.GetHandle())
        save_dc.DeleteDC()
        mfc_dc.DeleteDC()
        win32gui.ReleaseDC(hwnd, hwnd_dc)

    if not ok or img is None or _is_mostly_black(img):
        # Fallback: traer la ventana al frente y capturar la pantalla.
        return _screen_capture(hwnd)
    return img


def _grab(window_title: str = ""):
    """Ventana concreta si se indica título; pantalla completa si no."""
    if window_title.strip():
        return _capture_window(window_title)
    return pyautogui.screenshot()


def _target_window(window_title: str):
    """Encuentra, activa y devuelve la ventana junto con su rectángulo visible en pantalla."""
    matches = _find_window(window_title)
    if not matches:
        raise RuntimeError(
            f"No se encontró ninguna ventana visible con '{window_title}'. Usa list_windows."
        )

    hwnd, title, _ = matches[0]
    if not _activate_window(hwnd):
        raise RuntimeError(
            f"No se pudo activar la ventana '{title}'. Haz clic en ella y vuelve a intentarlo."
        )
    return hwnd, title, _visible_rect(hwnd)


def _release_mouse_grab(hwnd):
    """Saca el cursor a la barra de título para que VMware libere el ratón del invitado."""
    left, top, width, _ = _window_rect(hwnd)
    ctypes.windll.user32.SetCursorPos(left + width // 2, max(top + 8, 8))
    time.sleep(0.35)


def _check_point(x: int, y: int, width: int, height: int):
    if not (0 <= x < width and 0 <= y < height):
        raise RuntimeError(
            f"Coordenadas ({x}, {y}) fuera de la ventana ({width}x{height}). "
            "Usa take_screenshot para ver la imagen y calcula sobre ella."
        )


@mcp.tool()
def list_windows() -> str:
    """Lista las ventanas visibles (título, si están minimizadas y su posición/tamaño)."""
    windows = []

    def callback(hwnd, _):
        title = win32gui.GetWindowText(hwnd)
        if win32gui.IsWindowVisible(hwnd) and title:
            left, top, width, height = _window_rect(hwnd)
            windows.append(
                {
                    "title": title,
                    "minimized": bool(win32gui.IsIconic(hwnd)),
                    "rect": {
                        "left": left,
                        "top": top,
                        "width": width,
                        "height": height,
                    },
                }
            )

    win32gui.EnumWindows(callback, None)
    return json.dumps(windows, ensure_ascii=False, indent=2)


@mcp.tool()
def take_screenshot(window_title: str = "") -> Image:
    """Captura la pantalla completa, o solo una ventana si se da window_title
    (coincidencia parcial, ej. 'VMware Workstation'). En VMware captura el
    escritorio real del invitado y trae la ventana al frente si hace falta."""
    path = EVIDENCE / "latest.png"
    _grab(window_title).save(path)
    return Image(path=str(path))


@mcp.tool()
def save_evidence(name: str, description: str, window_title: str = "") -> str:
    """Guarda una captura numerada para documentar un paso (pantalla completa o una ventana)."""
    name = re.sub(r"[^a-zA-Z0-9_-]", "-", name)[:50]
    if not name:
        return "Nombre no válido."

    index = 1
    while (EVIDENCE / f"{index:03d}-{name}.png").exists():
        index += 1

    path = EVIDENCE / f"{index:03d}-{name}.png"
    _grab(window_title).save(path)

    record = {
        "number": index,
        "name": name,
        "description": description[:500],
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "image": path.name,
    }

    with (EVIDENCE / "evidence.jsonl").open("a", encoding="utf-8") as file:
        file.write(json.dumps(record, ensure_ascii=False) + "\n")

    return f"Captura guardada: {path}"


@mcp.tool()
def focus_window(window_title: str) -> str:
    """Trae una ventana al frente (por ejemplo 'VMware Workstation') y devuelve su tamaño."""
    _, title, (left, top, width, height) = _target_window(window_title)
    return json.dumps(
        {
            "title": title,
            "rect": {"left": left, "top": top, "width": width, "height": height},
        },
        ensure_ascii=False,
    )


@mcp.tool()
def click(
    window_title: str,
    x: int,
    y: int,
    button: str = "left",
    clicks: int = 1,
) -> str:
    """Haz clic en (x, y) relativas a la ventana capturada (0,0 = esquina superior izquierda).
    Activa la ventana antes de hacer clic. Usa take_screenshot para localizar el punto."""
    hwnd, title, (left, top, width, height) = _target_window(window_title)
    _check_point(x, y, width, height)
    _release_mouse_grab(hwnd)
    pyautogui.click(left + x, top + y, clicks=clicks, button=button, interval=0.15)
    return f"Clic {button} x{clicks} en '{title}' ({x}, {y})."


@mcp.tool()
def move_mouse(window_title: str, x: int, y: int) -> str:
    """Mueve el ratón a (x, y) relativas a la ventana (sin hacer clic)."""
    hwnd, title, (left, top, width, height) = _target_window(window_title)
    _check_point(x, y, width, height)
    _release_mouse_grab(hwnd)
    pyautogui.moveTo(left + x, top + y, duration=0.2)
    return f"Ratón en '{title}' ({x}, {y})."


@mcp.tool()
def drag(
    window_title: str,
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    duration: float = 0.5,
) -> str:
    """Arrastra desde (x1, y1) hasta (x2, y2), coordenadas relativas a la ventana."""
    hwnd, title, (left, top, width, height) = _target_window(window_title)
    _check_point(x1, y1, width, height)
    _check_point(x2, y2, width, height)
    _release_mouse_grab(hwnd)
    pyautogui.moveTo(left + x1, top + y1, duration=0.2)
    pyautogui.dragTo(left + x2, top + y2, duration=duration)
    return f"Arrastrado en '{title}' de ({x1}, {y1}) a ({x2}, {y2})."


@mcp.tool()
def scroll(window_title: str, clicks: int, x: int = -1, y: int = -1) -> str:
    """Desplaza la rueda dentro de la ventana. clicks positivos = arriba, negativos = abajo.
    Si no se dan x/y, usa el centro de la ventana."""
    hwnd, title, (left, top, width, height) = _target_window(window_title)
    if x < 0 or y < 0:
        x, y = width // 2, height // 2
    _check_point(x, y, width, height)
    _release_mouse_grab(hwnd)
    pyautogui.scroll(clicks, x=left + x, y=top + y)
    return f"Scroll {clicks} en '{title}' ({x}, {y})."


@mcp.tool()
def type_text(text: str, window_title: str = "") -> str:
    """Escribe texto en la ventana activa. Si se da window_title, la activa primero.
    Usa el portapapeles para caracteres que pyautogui no puede teclear (ñ, tildes, etc.)."""
    if window_title.strip():
        _target_window(window_title)

    try:
        pyautogui.write(text, interval=0.02)
    except (KeyError, ValueError):
        pyperclip.copy(text)
        pyautogui.hotkey("ctrl", "v")
        time.sleep(0.2)
    return f"Texto escrito ({len(text)} caracteres)."


@mcp.tool()
def press_keys(keys: str, window_title: str = "") -> str:
    """Pulsa una tecla o combinación. Ejemplos: 'enter', 'esc', 'tab',
    'ctrl+g', 'ctrl+alt+delete', 'win+r'."""
    if window_title.strip():
        _target_window(window_title)

    parts = [part.strip() for part in keys.split("+") if part.strip()]
    if not parts:
        raise RuntimeError("Indica al menos una tecla.")

    if len(parts) == 1:
        pyautogui.press(parts[0])
    else:
        pyautogui.hotkey(*parts)
    return f"Teclas pulsadas: {'+'.join(parts)}."


@mcp.tool()
def list_running_vms() -> str:
    """Lista las máquinas virtuales en ejecución usando vmrun de VMware Workstation."""
    if not VMRUN.exists():
        return f"No se encontró vmrun en '{VMRUN}'. Define VMRUN_PATH si está en otra ruta."

    try:
        result = subprocess.run(
            [str(VMRUN), "list"],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        return "vmrun no respondió a tiempo."

    output = (result.stdout or result.stderr).strip()
    if result.returncode != 0:
        return f"vmrun falló (código {result.returncode}): {output}"
    return output or "No hay máquinas virtuales en ejecución."


if __name__ == "__main__":
    mcp.run()
