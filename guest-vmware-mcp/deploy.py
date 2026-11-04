"""Despliega/actualiza el bridge MCP dentro de la VM y reinicia la tarea.

Uso (desde el host, con el venv que tiene pywinrm):
    C:\\Users\\Enoc\\vmware-visual-mcp\\.venv\\Scripts\\python.exe deploy.py
    C:\\Users\\Enoc\\vmware-visual-mcp\\.venv\\Scripts\\python.exe deploy.py --status
"""

import base64
import hashlib
import sys
import time
from pathlib import Path

import winrm

GUEST_IP = "192.168.222.134"
USER = "Administrador"
PASSWORD = "Server.123"
TASK = "OpenCode Guest MCP"
LOCAL = Path(__file__).with_name("server.py")
CHUNK = 1800


def session() -> winrm.Session:
    return winrm.Session(
        f"http://{GUEST_IP}:5985/wsman",
        auth=(USER, PASSWORD),
        transport="ntlm",
        read_timeout_sec=900,
        operation_timeout_sec=890,
    )


def ps(s: winrm.Session, script: str) -> tuple[int, str]:
    prelude = (
        "$ProgressPreference='SilentlyContinue';"
        "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8;"
        "$ErrorActionPreference='Continue';"
    )
    result = s.run_ps(prelude + script)
    return result.status_code, (result.std_out + result.std_err).decode("utf-8", "replace").strip()


def must(s: winrm.Session, label: str, script: str) -> str:
    code, output = ps(s, script)
    print(f"[{label}] {output}")
    if code != 0:
        raise SystemExit(f"falló {label} (status {code})")
    return output


def deploy() -> None:
    content = LOCAL.read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    payload = base64.b64encode(content).decode("ascii")
    s = session()

    for index in range(0, len(payload), CHUNK):
        piece = payload[index : index + CHUNK]
        verb = "Set-Content" if index == 0 else "Add-Content"
        code, output = ps(
            s,
            f"{verb} -Path 'C:/opencode-agent/server.b64' -Value '{piece}' -NoNewline -Encoding ASCII",
        )
        if code != 0:
            raise SystemExit(f"falló la subida en el trozo {index}: {output}")

    uploaded = must(
        s,
        "decode",
        r"""
$raw = Get-Content 'C:/opencode-agent/server.b64' -Raw
[IO.File]::WriteAllBytes('C:/opencode-agent/server.py', [Convert]::FromBase64String($raw))
Remove-Item 'C:/opencode-agent/server.b64' -Force
(Get-FileHash 'C:/opencode-agent/server.py' -Algorithm SHA256).Hash.ToLower()
""",
    )
    if uploaded.strip().lower() != digest:
        raise SystemExit(f"hash distinto: local {digest}, guest {uploaded}")
    print(f"[hash] ok {digest}")

    must(
        s,
        "compile",
        r'& "C:\Program Files\Python313\python.exe" -m py_compile "C:\opencode-agent\server.py"; "exit=$LASTEXITCODE"',
    )

    must(
        s,
        "stop",
        r"""
Stop-ScheduledTask -TaskName 'OpenCode Guest MCP' -ErrorAction SilentlyContinue
$conn = Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue
if ($conn) { Stop-Process -Id $conn.OwningProcess -Force -ErrorAction SilentlyContinue }
Start-Sleep -Seconds 2
if (Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue) { 'puerto ocupado' } else { 'puerto libre' }
""",
    )

    must(
        s,
        "start",
        r"""
Start-ScheduledTask -TaskName 'OpenCode Guest MCP'
Start-Sleep -Seconds 10
(Get-ScheduledTask -TaskName 'OpenCode Guest MCP').State
try { (Invoke-WebRequest -Uri 'http://127.0.0.1:8765/health' -UseBasicParsing -TimeoutSec 10).Content }
catch { "HEALTH FAIL: $($_.Exception.Message)" }
""",
    )


def status() -> None:
    s = session()
    must(
        s,
        "status",
        r"""
$task = Get-ScheduledTask -TaskName 'OpenCode Guest MCP' -ErrorAction SilentlyContinue
if (-not $task) { 'tarea NO registrada'; exit 1 }
"task=$($task.State) user=$($task.Principal.UserId) logon=$($task.Principal.LogonType) runlevel=$($task.Principal.RunLevel)"
try { (Invoke-WebRequest -Uri 'http://127.0.0.1:8765/health' -UseBasicParsing -TimeoutSec 8).Content }
catch { "health FAIL: $($_.Exception.Message)" }
Get-Process pythonw -ErrorAction SilentlyContinue | Select-Object Id,SessionId | Format-Table -AutoSize | Out-String
""",
    )


if __name__ == "__main__":
    if "--status" in sys.argv:
        status()
    else:
        deploy()
