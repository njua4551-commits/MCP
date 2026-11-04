"""MCP bridge que corre DENTRO de la VM Windows Server 2019.

Da al agente del host control nativo del guest: PowerShell, archivos,
servicios, portapapeles, capturas y ratón/teclado en la sesión interactiva.

Se ejecuta como tarea programada interactiva del usuario Administrador
(sesión 1), por eso pyautogui y las capturas ven el escritorio real.
"""

import ctypes
import hmac
import json
import logging
import os
import platform
import re
import socket
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

import psutil
import pyautogui
import pyperclip
import uvicorn
from mcp.server.fastmcp import FastMCP, Image
from PIL import ImageGrab
from starlette.responses import JSONResponse

BASE = Path(r"C:\opencode-agent")
LOCAL_EVIDENCE = BASE / "evidence"
SHARED_EVIDENCE = Path(r"\\vmware-host\Shared Folders\iss2")
TMP = BASE / "tmp"
LOG = BASE / "server.log"
TOKEN_FILE = BASE / "token.txt"

for folder in (BASE, LOCAL_EVIDENCE, TMP):
    folder.mkdir(parents=True, exist_ok=True)

PYTHON = Path(sys.executable)
POWERSHELL = Path(r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe")
PORT = 8765
HOST = "0.0.0.0"

pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0.15

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        user32.SetProcessDPIAware()
    except Exception:
        pass


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


user32.GetForegroundWindow.restype = ctypes.c_void_p
user32.RealChildWindowFromPoint.restype = ctypes.c_void_p
user32.RealChildWindowFromPoint.argtypes = [ctypes.c_void_p, POINT]
user32.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
user32.SetFocus.argtypes = [ctypes.c_void_p]
user32.SetForegroundWindow.argtypes = [ctypes.c_void_p]
user32.BringWindowToTop.argtypes = [ctypes.c_void_p]
user32.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
user32.IsIconic.argtypes = [ctypes.c_void_p]
user32.GetClientRect.argtypes = [ctypes.c_void_p, ctypes.POINTER(RECT)]
kernel32.GetCurrentThreadId.restype = ctypes.c_ulong


def _activate(hwnd) -> bool:
    """Trae la ventana al frente y enfoca el control hijo del centro (sin hacer clic)."""
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE

    current = kernel32.GetCurrentThreadId()
    foreground = user32.GetForegroundWindow()
    foreground_thread = user32.GetWindowThreadProcessId(foreground, None) if foreground else 0
    target_thread = user32.GetWindowThreadProcessId(hwnd, None)

    attached = []
    for thread in {foreground_thread, target_thread}:
        if thread and thread != current and user32.AttachThreadInput(current, thread, True):
            attached.append(thread)

    try:
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)

        target = hwnd
        for _ in range(6):
            rect = RECT()
            if not user32.GetClientRect(target, ctypes.byref(rect)):
                break
            point = POINT((rect.right - rect.left) // 2, (rect.bottom - rect.top) // 2)
            child = user32.RealChildWindowFromPoint(target, point)
            if not child or child == target:
                break
            target = child
        if target != hwnd:
            user32.SetFocus(target)
    finally:
        for thread in attached:
            user32.AttachThreadInput(current, thread, False)

    time.sleep(0.2)
    return user32.GetForegroundWindow() == hwnd


def _redirect_output():
    """pythonw no tiene consola: manda stdout/stderr al log con rotación simple."""
    if "--console" in sys.argv:
        return
    try:
        if LOG.exists() and LOG.stat().st_size > 5 * 1024 * 1024:
            rotated = LOG.with_suffix(".1.log")
            if rotated.exists():
                rotated.unlink()
            LOG.rename(rotated)
    except Exception:
        pass
    stream = open(LOG, "a", encoding="utf-8", buffering=1)
    sys.stdout = stream
    sys.stderr = stream


_redirect_output()


def _token() -> str:
    token = TOKEN_FILE.read_text(encoding="utf-8").strip()
    if len(token) < 24:
        raise SystemExit("token.txt ausente o demasiado corto; no se inicia el servidor.")
    return token


def _session_id() -> int:
    sid = ctypes.c_ulong()
    kernel32.ProcessIdToSessionId(os.getpid(), ctypes.byref(sid))
    return sid.value


def _truncate(text: str, limit: int = 30000) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n...[truncado, {len(text)} caracteres en total]"


def _usable(directory: Path) -> bool:
    """Comprueba que se puede crear y borrar un archivo en la carpeta."""
    try:
        directory.mkdir(parents=True, exist_ok=True)
        probe = directory / ".write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


def _evidence_dir() -> Path:
    """Carpeta compartida del host si está montada; si no, evidencia local."""
    return SHARED_EVIDENCE if _usable(SHARED_EVIDENCE) else LOCAL_EVIDENCE


def _run_process(args, timeout: int, cwd: str | None = None) -> str:
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            cwd=cwd,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except subprocess.TimeoutExpired as exc:
        partial = (exc.stdout or "") + (exc.stderr or "")
        return f"TIMEOUT tras {timeout}s.\n{_truncate(str(partial))}"
    except Exception as exc:  # noqa: BLE001
        return f"ERROR al ejecutar: {exc}"

    output = (result.stdout or "") + (result.stderr or "")
    output = output.strip()
    if result.returncode != 0:
        return f"exit={result.returncode}\n{_truncate(output)}"
    return _truncate(output) or "(sin salida)"


mcp = FastMCP(
    "guest-vmware",
    instructions=(
        "Control nativo de la VM Windows Server 2019. Coordenadas de ratón en "
        "píxeles absolutos del escritorio del guest; usa screenshot para verlas."
    ),
    stateless_http=True,
    host=HOST,
    port=PORT,
)


@mcp.tool()
def run_powershell(script: str, timeout: int = 120) -> str:
    """Ejecuta PowerShell dentro del guest y devuelve stdout+stderr.
    El script se guarda como .ps1 UTF-8 con BOM para respetar acentos y ñ."""
    prelude = (
        "$ProgressPreference='SilentlyContinue';"
        "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8;"
        "$ErrorActionPreference='Continue';"
    )
    fd, path = tempfile.mkstemp(suffix=".ps1", dir=str(TMP))
    os.close(fd)
    try:
        Path(path).write_text("\ufeff" + prelude + script, encoding="utf-8")
        return _run_process(
            [
                str(POWERSHELL),
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                path,
            ],
            timeout=timeout,
            cwd=str(Path.home()),
        )
    finally:
        try:
            Path(path).unlink()
        except OSError:
            pass


@mcp.tool()
def run_command(command: str, timeout: int = 120) -> str:
    """Ejecuta un comando de cmd.exe en el guest (útil para herramientas nativas)."""
    return _run_process(
        [r"C:\Windows\System32\cmd.exe", "/c", command],
        timeout=timeout,
        cwd=str(Path.home()),
    )


@mcp.tool()
def read_file(path: str, max_bytes: int = 200000) -> str:
    """Lee un archivo de texto del guest (UTF-8 con fallback a latin-1)."""
    file = Path(path)
    if not file.exists():
        return f"No existe: {file}"
    if file.is_dir():
        return f"Es un directorio: {file}"
    data = file.read_bytes()[:max_bytes]
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        text = data.decode("latin-1", "replace")
    suffix = "" if file.stat().st_size <= max_bytes else f"\n...[leídos {max_bytes} de {file.stat().st_size} bytes]"
    return text + suffix


@mcp.tool()
def write_file(path: str, content: str, append: bool = False) -> str:
    """Crea o sobrescribe un archivo de texto en el guest (UTF-8, crea carpetas)."""
    file = Path(path)
    file.parent.mkdir(parents=True, exist_ok=True)
    mode = "a" if append else "w"
    with file.open(mode, encoding="utf-8", newline="") as handle:
        handle.write(content)
    return f"{'Añadidos' if append else 'Escritos'} {len(content)} caracteres en {file}"


@mcp.tool()
def list_dir(path: str = "C:\\") -> str:
    """Lista el contenido de un directorio con tipo, tamaño y fecha de modificación."""
    folder = Path(path)
    if not folder.exists():
        return f"No existe: {folder}"
    if not folder.is_dir():
        return f"No es un directorio: {folder}"

    entries = []
    try:
        for item in sorted(folder.iterdir(), key=lambda p: (p.is_file(), p.name.lower())):
            try:
                stat = item.stat()
                entries.append(
                    {
                        "name": item.name,
                        "type": "dir" if item.is_dir() else "file",
                        "size": None if item.is_dir() else stat.st_size,
                        "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
                    }
                )
            except OSError as exc:
                entries.append({"name": item.name, "error": str(exc)})
    except PermissionError as exc:
        return f"Sin permiso para listar {folder}: {exc}"
    return json.dumps(entries, ensure_ascii=False, indent=2)


@mcp.tool()
def get_system_info() -> str:
    """Resumen del guest: usuario, sesión, OS, CPU/RAM, discos, IPs y pantalla."""
    memory = psutil.virtual_memory()
    disks = []
    for part in psutil.disk_partitions(all=False):
        try:
            usage = psutil.disk_usage(part.mountpoint)
        except (PermissionError, OSError):
            continue
        disks.append(
            {
                "device": part.device,
                "total_gb": round(usage.total / 1073741824, 1),
                "free_gb": round(usage.free / 1073741824, 1),
            }
        )
    info = {
        "hostname": socket.gethostname(),
        "user": f"{os.environ.get('USERDOMAIN', '')}\\{os.environ.get('USERNAME', '')}",
        "os": platform.platform(),
        "python": sys.version.split()[0],
        "pid": os.getpid(),
        "session_id": _session_id(),
        "uptime_hours": round((time.time() - psutil.boot_time()) / 3600, 1),
        "screen": {
            "width": user32.GetSystemMetrics(0),
            "height": user32.GetSystemMetrics(1),
        },
        "cpu": {
            "cores": psutil.cpu_count(logical=True),
            "percent": psutil.cpu_percent(interval=0.3),
        },
        "memory": {
            "total_mb": round(memory.total / 1048576),
            "used_mb": round(memory.used / 1048576),
            "percent": memory.percent,
        },
        "disks": disks,
        "ipv4": [
            addr.address
            for name, addrs in psutil.net_if_addrs().items()
            for addr in addrs
            if addr.family == socket.AF_INET and not addr.address.startswith("127.")
        ],
    }
    return json.dumps(info, ensure_ascii=False, indent=2)


@mcp.tool()
def list_services(name_filter: str = "") -> str:
    """Lista servicios de Windows (nombre, estado, inicio) filtrados por texto."""
    services = []
    needle = name_filter.lower()
    for service in psutil.win_service_iter():
        try:
            data = service.as_dict()
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            continue
        haystack = f"{data.get('name', '')} {data.get('display_name', '')}".lower()
        if needle and needle not in haystack:
            continue
        services.append(
            {
                "name": data.get("name"),
                "display_name": data.get("display_name"),
                "status": data.get("status"),
                "start_type": data.get("start_type"),
            }
        )
    return json.dumps(services, ensure_ascii=False, indent=2)


@mcp.tool()
def screenshot() -> Image:
    """Captura el escritorio completo del guest (todas las pantallas)."""
    path = _evidence_dir() / "latest.png"
    ImageGrab.grab(all_screens=True).save(path)
    return Image(path=str(path))


@mcp.tool()
def save_evidence(name: str, description: str) -> str:
    """Guarda una captura numerada para documentar un paso."""
    safe = re.sub(r"[^a-zA-Z0-9_-]", "-", name)[:50]
    if not safe:
        return "Nombre no válido."

    folder = _evidence_dir()
    index = 1
    while (folder / f"{index:03d}-{safe}.png").exists():
        index += 1

    path = folder / f"{index:03d}-{safe}.png"
    ImageGrab.grab(all_screens=True).save(path)

    record = {
        "number": index,
        "name": safe,
        "description": description[:500],
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "image": path.name,
    }
    with (folder / "evidence.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    return f"Captura guardada: {path}"


@mcp.tool()
def click(x: int, y: int, button: str = "left", clicks: int = 1) -> str:
    """Haz clic en coordenadas absolutas del escritorio del guest."""
    pyautogui.click(x, y, clicks=clicks, button=button, interval=0.15)
    return f"Clic {button} x{clicks} en ({x}, {y})."


@mcp.tool()
def move_mouse(x: int, y: int) -> str:
    """Mueve el ratón a coordenadas absolutas (sin hacer clic)."""
    pyautogui.moveTo(x, y, duration=0.2)
    return f"Ratón en ({x}, {y})."


@mcp.tool()
def drag(x1: int, y1: int, x2: int, y2: int, duration: float = 0.5) -> str:
    """Arrastra con el botón izquierdo de (x1, y1) a (x2, y2)."""
    pyautogui.moveTo(x1, y1, duration=0.2)
    pyautogui.dragTo(x2, y2, duration=duration, button="left")
    return f"Arrastrado de ({x1}, {y1}) a ({x2}, {y2})."


@mcp.tool()
def scroll(clicks: int, x: int = -1, y: int = -1) -> str:
    """Rueda del ratón; positivo arriba, negativo abajo. Si x/y >= 0 mueve antes."""
    if x >= 0 and y >= 0:
        pyautogui.moveTo(x, y, duration=0.2)
    pyautogui.scroll(clicks)
    return f"Scroll {clicks} en ({x}, {y})" if x >= 0 else f"Scroll {clicks}."


@mcp.tool()
def type_text(text: str) -> str:
    """Escribe texto en la ventana activa. Usa el portapapeles si hay ñ, tildes, etc."""
    if all(char in pyautogui.KEYBOARD_KEYS for char in text):
        pyautogui.write(text, interval=0.02)
    else:
        pyperclip.copy(text)
        pyautogui.hotkey("ctrl", "v")
        time.sleep(0.25)
    return f"Texto escrito ({len(text)} caracteres)."


@mcp.tool()
def press_keys(keys: str) -> str:
    """Pulsa una tecla o combinación: 'enter', 'esc', 'tab', 'ctrl+g', 'win+r'."""
    parts = [part.strip().lower() for part in keys.split("+") if part.strip()]
    if not parts:
        raise RuntimeError("Indica al menos una tecla.")
    parts = ["win" if part in ("windows", "cmd") else part for part in parts]
    if len(parts) == 1:
        pyautogui.press(parts[0])
    else:
        pyautogui.hotkey(*parts)
    return f"Teclas pulsadas: {'+'.join(parts)}."


@mcp.tool()
def get_clipboard() -> str:
    """Devuelve el texto actual del portapapeles del guest."""
    return pyperclip.paste()


@mcp.tool()
def set_clipboard(text: str) -> str:
    """Copia texto al portapapeles del guest."""
    pyperclip.copy(text)
    return f"Portapapeles actualizado ({len(text)} caracteres)."


@mcp.tool()
def list_windows() -> str:
    """Lista ventanas visibles con título, PID, estado y rectángulo en pantalla."""
    windows = []

    class RECT(ctypes.Structure):
        _fields_ = [
            ("left", ctypes.c_long),
            ("top", ctypes.c_long),
            ("right", ctypes.c_long),
            ("bottom", ctypes.c_long),
        ]

    def callback(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length == 0:
            return True
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)
        rect = RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        windows.append(
            {
                "title": buffer.value,
                "pid": pid.value,
                "minimized": bool(user32.IsIconic(hwnd)),
                "rect": {
                    "left": rect.left,
                    "top": rect.top,
                    "width": rect.right - rect.left,
                    "height": rect.bottom - rect.top,
                },
            }
        )
        return True

    user32.EnumWindows(ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)(callback), None)
    return json.dumps(windows, ensure_ascii=False, indent=2)


@mcp.tool()
def focus_window(title: str) -> str:
    """Trae al frente la primera ventana visible cuyo título contenga 'title'
    y enfoca su control principal (sin hacer clic)."""
    matches = []

    def callback(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length == 0:
            return True
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)
        if title.lower() in buffer.value.lower():
            matches.append((hwnd, buffer.value))
        return True

    user32.EnumWindows(ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)(callback), None)
    if not matches:
        return f"No hay ventanas que contengan '{title}'. Usa list_windows."

    hwnd, real_title = matches[0]
    active = _activate(hwnd)
    state = "enfocada" if active else "traída al frente (foco no confirmado)"
    return f"Ventana {state}: '{real_title}'."


class AuthAndHealth:
    """Middleware ASGI puro: bearer token para /mcp y /health sin auth."""

    def __init__(self, app, token: str):
        self.app = app
        self.expected = f"Bearer {token}".encode("latin-1")

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            if scope.get("path") == "/health":
                response = JSONResponse(
                    {
                        "status": "ok",
                        "pid": os.getpid(),
                        "session_id": _session_id(),
                        "hostname": socket.gethostname(),
                    }
                )
                await response(scope, receive, send)
                return

            headers = dict(scope.get("headers") or [])
            provided = headers.get(b"authorization", b"")
            if not hmac.compare_digest(provided, self.expected):
                response = JSONResponse({"error": "unauthorized"}, status_code=401)
                await response(scope, receive, send)
                return

        await self.app(scope, receive, send)


def main() -> None:
    logging.basicConfig(
        stream=sys.stderr,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    token = _token()
    app = AuthAndHealth(mcp.streamable_http_app(), token)
    print(f"[{datetime.now().isoformat(timespec='seconds')}] guest-vmware MCP en {HOST}:{PORT} pid={os.getpid()} session={_session_id()}")
    uvicorn.run(app, host=HOST, port=PORT, log_config=None, access_log=False)


if __name__ == "__main__":
    main()
