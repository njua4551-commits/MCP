#!/usr/bin/env python3
"""MCP VMware — servidor de herramientas para Workstation/Fusion.

Protocolo: JSON-RPC 2.0 por stdio (MCP). Sin dependencias externas (solo stdlib).
Requiere: vmrun en PATH o VMRUN. Las operaciones de invitado requieren VMware Tools.
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

VMRUN = os.environ.get("VMRUN", "vmrun")
HOST_TYPE = os.environ.get("VMWARE_HOST_TYPE", "fusion" if sys.platform == "darwin" else "ws")
defaults = ["Documents/Virtual Machines"] if os.name == "nt" else (
    ["Virtual Machines.localized", "Virtual Machines"] if sys.platform == "darwin" else ["Escritorio/VMs", "vmware"])
VMS_DIR = Path(os.environ.get("VMWARE_VMS_DIR") or next(
    (Path.home() / d for d in defaults if (Path.home() / d).is_dir()), Path.home() / defaults[0]))
SCREENSHOT_DIR = os.environ.get("VMWARE_SCREENSHOT_DIR", os.path.join(tempfile.gettempdir(), "mcp-portatil-vmware"))

# Credenciales opcionales para runProgramInGuest (VMware Tools)
GUEST_USER = os.environ.get("VMWARE_GUEST_USER", "")
GUEST_PASS = os.environ.get("VMWARE_GUEST_PASS", "")


def vmrun(*args, timeout=120):
    """Ejecuta vmrun -T ws y devuelve (ok, salida)."""
    cmd = [VMRUN, "-T", HOST_TYPE] + list(args)
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        out = (p.stdout or "").strip()
        err = (p.stderr or "").strip()
        return p.returncode == 0 and not out.lower().startswith("error"), out or err
    except FileNotFoundError:
        return False, "vmrun no encontrado en PATH"
    except subprocess.TimeoutExpired:
        return False, f"timeout de vmrun tras {timeout}s"


def vmrun_guest(*args, timeout=120):
    """Como vmrun pero inyecta credenciales de guest si están definidas."""
    if GUEST_USER and GUEST_PASS:
        return vmrun("-gu", GUEST_USER, "-gp", GUEST_PASS, *args, timeout=timeout)
    return vmrun(*args, timeout=timeout)


def find_vmx(name):
    """Busca el .vmx de una VM por nombre de carpeta (o ruta directa)."""
    if os.path.isfile(name) and name.endswith(".vmx"):
        return name
    return next((str(p) for p in inventory() if p.stem.casefold() == name.casefold()), None)


def inventory():
    if not VMS_DIR.is_dir():
        raise ValueError("Configura VMWARE_VMS_DIR con la carpeta de máquinas virtuales.")
    return sorted([*VMS_DIR.glob("*.vmx"), *VMS_DIR.glob("*/*.vmx")])


def running_vms():
    """Devuelve el set de rutas .vmx en ejecución (vmrun -T ws list)."""
    ok, out = vmrun("list", timeout=30)
    if not ok:
        raise ValueError(out or "vmrun list falló")
    paths = set()
    for line in out.splitlines():
        line = line.strip()
        if line.endswith(".vmx"):
            paths.add(line)
    return paths


def list_vms():
    vms = []
    running = running_vms()
    for vmx in inventory():
        state = "encendida" if str(vmx) in running else "apagada"
        vms.append({"nombre": vmx.stem, "estado": state})
    return vms


TOOLS = [
    {
        "name": "vm_list",
        "description": "Lista las máquinas virtuales del directorio configurado con su estado.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "vm_state",
        "description": "Devuelve el estado de una VM (on, off, suspended, ...).",
        "inputSchema": {
            "type": "object",
            "properties": {"vm": {"type": "string", "description": "Nombre de la carpeta de la VM"}},
            "required": ["vm"],
        },
    },
    {
        "name": "vm_start",
        "description": "Enciende una VM (con GUI si gui=true, o en segundo plano).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "vm": {"type": "string"},
                "gui": {"type": "boolean", "default": True},
            },
            "required": ["vm"],
        },
    },
    {
        "name": "vm_stop",
        "description": "Apaga una VM. soft=apagado limpio (necesita VMware Tools), hard=corte inmediato.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "vm": {"type": "string"},
                "hard": {"type": "boolean", "default": False},
            },
            "required": ["vm"],
        },
    },
    {
        "name": "vm_screenshot",
        "description": "Captura la pantalla de la VM y guarda un PNG. Devuelve la ruta del archivo.",
        "inputSchema": {
            "type": "object",
            "properties": {"vm": {"type": "string"}},
            "required": ["vm"],
        },
    },
    {
        "name": "vm_run_cmd",
        "description": "Ejecuta un comando DENTRO del guest (Windows) vía VMware Tools. Requiere credenciales configuradas en VMWARE_GUEST_USER/PASS.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "vm": {"type": "string"},
                "cmd": {"type": "string", "description": "Comando a ejecutar en el guest (ej: 'powershell -Command whoami')"},
            },
            "required": ["vm", "cmd"],
        },
    },
]


def call_tool(name, args):
    """Ejecuta una herramienta y devuelve (texto, isError)."""
    vm = args.get("vm", "")

    if name == "vm_list":
        vms = list_vms()
        return json.dumps(vms, ensure_ascii=False), False

    if name == "vm_state":
        vmx = find_vmx(vm)
        if not vmx:
            return f"VM no encontrada: {vm}", True
        state = "encendida" if vmx in running_vms() else "apagada"
        return state, False

    if name == "vm_start":
        vmx = find_vmx(vm)
        if not vmx:
            return f"VM no encontrada: {vm}", True
        flag = ["start", vmx] + (["nogui"] if not args.get("gui", True) else [])
        ok, out = vmrun(*flag)
        return (f"VM encendida: {vm}" if ok else f"error: {out}"), not ok

    if name == "vm_stop":
        vmx = find_vmx(vm)
        if not vmx:
            return f"VM no encontrada: {vm}", True
        ok, out = vmrun("stop", vmx, "hard" if args.get("hard") else "soft")
        return (f"VM apagada: {vm}" if ok else f"error: {out}"), not ok

    if name == "vm_screenshot":
        vmx = find_vmx(vm)
        if not vmx:
            return f"VM no encontrada: {vm}", True
        os.makedirs(SCREENSHOT_DIR, exist_ok=True)
        png = os.path.join(SCREENSHOT_DIR, Path(vmx).stem + ".png")
        ok, out = vmrun_guest("captureScreen", vmx, png)
        if ok and os.path.isfile(png):
            return f"Screenshot guardado: {png}", False
        return f"error capturando pantalla: {out}", True

    if name == "vm_run_cmd":
        if not GUEST_USER or not GUEST_PASS:
            return ("runProgramInGuest requiere credenciales: define VMWARE_GUEST_USER y "
                    "VMWARE_GUEST_PASS al iniciar el servidor MCP"), True
        vmx = find_vmx(vm)
        if not vmx:
            return f"VM no encontrada: {vm}", True
        cmd = args.get("cmd", "")
        ok, out = vmrun_guest("runProgramInGuest", vmx, r"C:\Windows\System32\cmd.exe", "/d", "/c", cmd, timeout=300)
        return (out if ok else f"error: {out}"), not ok

    return f"herramienta desconocida: {name}", True


def handle(req):
    """Procesa una petición JSON-RPC y devuelve la respuesta (o None si es notificación)."""
    method = req.get("method")
    rid = req.get("id")
    params = req.get("params") or {}

    if method == "initialize":
        result = {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "mcp-vmware-linux", "version": "1.0.0"},
        }
    elif method == "notifications/initialized":
        return None
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        try:
            text, is_error = call_tool(name, args)
        except (ValueError, OSError) as e:
            text, is_error = str(e), True
        result = {
            "content": [{"type": "text", "text": text}],
            "isError": is_error,
        }
    else:
        if rid is None:
            return None
        return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": f"método no soportado: {method}"}}

    if rid is None:
        return None
    return {"jsonrpc": "2.0", "id": rid, "result": result}


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError as e:
            resp = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": str(e)}}
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()
            continue
        resp = handle(req)
        if resp is not None:
            sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
