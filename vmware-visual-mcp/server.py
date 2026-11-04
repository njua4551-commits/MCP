import ctypes
import json
import os
import re
import subprocess
import tempfile
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

# Credenciales del invitado para comandos por consola (vm_run). Van por entorno
# para no pagarlas en tokens en cada llamada.
VM_USER = os.environ.get("VM_USER", "")
VM_PASS = os.environ.get("VM_PASS", "")
VMX_PATH = os.environ.get("VMX_PATH", "")

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


def _screen_capture(hwnd, allow_focus: bool = True) -> PILImage.Image:
    """Captura la ventana desde la pantalla real. Necesario para ver el escritorio del invitado."""
    title = win32gui.GetWindowText(hwnd)
    if allow_focus:
        if not _activate_window(hwnd):
            raise RuntimeError(
                f"No se pudo traer '{title}' al frente para capturarla. "
                "Haz clic en la ventana y vuelve a intentarlo."
            )
    elif win32gui.IsIconic(hwnd):
        raise RuntimeError(
            f"'{title}' está minimizada. Usa activate=True para restaurarla."
        )

    left, top, width, height = _visible_rect(hwnd)
    if width <= 0 or height <= 0:
        raise RuntimeError("La ventana está fuera de la pantalla y no se puede capturar.")

    return pyautogui.screenshot(region=(left, top, width, height))


def _capture_window(window_title: str, allow_focus: bool = True) -> PILImage.Image:
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
        return _screen_capture(hwnd, allow_focus)

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
        if not allow_focus:
            raise RuntimeError(
                f"PrintWindow no capturó el contenido de '{title}'. "
                "Pasa activate=True (roba el foco) o deja la ventana visible sin tapar."
            )
        return _screen_capture(hwnd, allow_focus)
    return img


def _grab(window_title: str = "", allow_focus: bool = True):
    """Ventana concreta si se indica título; pantalla completa si no."""
    if window_title.strip():
        return _capture_window(window_title, allow_focus)
    return pyautogui.screenshot()


def _crop(img: PILImage.Image, crop: str) -> PILImage.Image:
    """Recorta con 'x0,y0,x1,y1' en fracciones 0-1 (útil para quitar barras de VMware)."""
    if not crop.strip():
        return img
    try:
        left, top, right, bottom = (float(part) for part in crop.split(","))
    except ValueError:
        raise RuntimeError("crop debe ser 'x0,y0,x1,y1' en fracciones 0-1 (ej. '0,0.1,1,0.95').")

    width, height = img.size
    box = (
        int(min(max(left, 0.0), 1.0) * width),
        int(min(max(top, 0.0), 1.0) * height),
        int(min(max(right, 0.0), 1.0) * width),
        int(min(max(bottom, 0.0), 1.0) * height),
    )
    if box[2] - box[0] < 8 or box[3] - box[1] < 8:
        raise RuntimeError("El recorte resultante es demasiado pequeño.")
    return img.crop(box)


def _resize(img: PILImage.Image, max_width: int) -> PILImage.Image:
    """Reduce el ancho: el coste en tokens de una imagen va por píxeles, no por formato."""
    if max_width <= 0 or img.width <= max_width:
        return img
    ratio = max_width / img.width
    return img.resize((max_width, max(1, round(img.height * ratio))), PILImage.LANCZOS)


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
def list_windows(title_part: str = "", include_rect: bool = False) -> str:
    """Lista ventanas visibles. Filtra con title_part (recomendado: 'VMware') para
    no gastar tokens. include_rect añade posición/tamaño de cada ventana."""
    windows = []

    def callback(hwnd, _):
        title = win32gui.GetWindowText(hwnd)
        if not win32gui.IsWindowVisible(hwnd) or not title:
            return
        if title_part.strip() and title_part.lower() not in title.lower():
            return
        if include_rect:
            left, top, width, height = _window_rect(hwnd)
            windows.append(
                {
                    "title": title,
                    "minimized": bool(win32gui.IsIconic(hwnd)),
                    "rect": [left, top, width, height],
                }
            )
        else:
            windows.append(title)

    win32gui.EnumWindows(callback, None)
    return json.dumps(windows, ensure_ascii=False)


@mcp.tool()
def take_screenshot(
    window_title: str = "",
    max_width: int = 1280,
    quality: int = 80,
    crop: str = "",
    activate: bool = False,
) -> Image:
    """Captura la pantalla completa, o solo una ventana si se da window_title
    (coincidencia parcial, ej. 'VMware Workstation'). Ya viene optimizada para
    gastar pocos tokens: se reescala a `max_width` px (0 = sin reescalar) y se
    puede recortar con `crop='x0,y0,x1,y1'` en fracciones 0-1 (ej. '0,0.08,1,0.95'
    para quitar barras). `activate=True` trae la ventana al frente; necesario en
    VMware si está minimizada o tapada."""
    img = _grab(window_title, allow_focus=activate)
    img = _crop(img, crop)
    img = _resize(img, max_width)
    path = EVIDENCE / "latest.jpg"
    img.convert("RGB").save(path, "JPEG", quality=quality)
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


def _vmrun(args, timeout: int = 120):
    if not VMRUN.exists():
        raise RuntimeError(f"No se encontró vmrun en '{VMRUN}'. Define VMRUN_PATH.")
    try:
        result = subprocess.run(
            [str(VMRUN), "-T", "ws", *args],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"vmrun tardó más de {timeout}s.")
    return result.returncode, ((result.stdout or "") + (result.stderr or "")).strip()


@mcp.tool()
def wait_ms(ms: int) -> str:
    """Espera `ms` milisegundos (máx 120000) sin capturar nada. Úsalo en vez de
    repetir take_screenshot para esperar a que cargue una pantalla."""
    ms = max(0, min(int(ms), 120000))
    time.sleep(ms / 1000)
    return f"Esperado {ms} ms."


@mcp.tool()
def vm_run(command: str, vm_path: str = "", timeout: int = 120, linux: bool = False) -> str:
    """Ejecuta `command` DENTRO del invitado y devuelve su salida (texto, máx 4000
    caracteres). Es la vía barata: úsala por defecto y deja take_screenshot solo
    para verificar el resultado visual. Requiere VM_USER, VM_PASS y VMX_PATH en el
    entorno del servidor."""
    if not (VM_USER and VM_PASS):
        return (
            "Falta VM_USER/VM_PASS en el entorno del servidor MCP; sin credenciales "
            "del invitado no puedo ejecutar comandos."
        )
    vmx = vm_path.strip() or VMX_PATH
    if not vmx:
        return "Falta VMX_PATH (o pasa vm_path) con la ruta del .vmx de la VM."

    creds = ["-gu", VM_USER, "-gp", VM_PASS]
    tag = str(int(time.time() * 1000))
    suffix = "sh" if linux else "bat"
    script = Path(tempfile.gettempdir()) / f"vmrun-{tag}.{suffix}"
    output = Path(tempfile.gettempdir()) / f"vmrun-{tag}.out"

    if linux:
        guest_script = f"/tmp/vmrun-{tag}.sh"
        guest_output = f"/tmp/vmrun-{tag}.out"
        script.write_text(
            f"#!/bin/bash\n({command}) > {guest_output} 2>&1\n",
            encoding="utf-8",
            newline="\n",
        )
        runner = ["/bin/bash", guest_script]
    else:
        guest_script = rf"C:\Windows\Temp\vmrun-{tag}.bat"
        guest_output = rf"C:\Windows\Temp\vmrun-{tag}.out"
        script.write_text(
            f'@echo off\r\n({command}) > "{guest_output}" 2>&1\r\n', encoding="utf-8"
        )
        runner = [guest_script]

    try:
        code, out = _vmrun(
            [*creds, "copyFileFromHostToGuest", vmx, str(script), guest_script], 60
        )
        if code != 0:
            return f"No pude copiar el script al invitado: {out}"

        code, out = _vmrun([*creds, "runProgramInGuest", vmx, *runner], max(30, timeout))
        if code != 0:
            return f"El comando falló al ejecutarse (código {code}): {out}"

        code, out = _vmrun(
            [*creds, "copyFileFromGuestToHost", vmx, guest_output, str(output)], 60
        )
        if code != 0:
            return f"No pude leer la salida del comando: {out}"

        text = output.read_text(encoding="utf-8", errors="replace").strip()
        if not text:
            return "Comando ejecutado sin salida."
        if len(text) > 4000:
            text = "...(recortado)\n" + text[-4000:]
        return text
    finally:
        for path in (script, output):
            try:
                path.unlink()
            except OSError:
                pass


if __name__ == "__main__":
    mcp.run()
