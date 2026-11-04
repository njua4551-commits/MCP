# guest-vmware: control nativo de la VM desde OpenCode

Servidor MCP que corre **dentro** de Windows Server 2019, en la sesión interactiva
del usuario `Administrador`. OpenCode (host) se conecta por HTTP y obtiene control
nativo: PowerShell, archivos, servicios, portapapeles, capturas y ratón/teclado.

```
OpenCode host
  └─ MCP remoto  http://192.168.222.134:8765/mcp   (Bearer token)
       └─ pythonw.exe en sesión 1  (tarea "OpenCode Guest MCP")
            ├─ FastMCP + uvicorn en 0.0.0.0:8765
            ├─ pyautogui  → SendInput (ratón/teclado reales)
            ├─ ImageGrab  → captura del escritorio del guest
            └─ PowerShell / subprocess / psutil
```

El servidor del host `vmware-visual-mcp` sigue activo como respaldo (capturas de
la ventana de VMware), pero ya no es necesario para operar el guest.

## Estado actual

| Elemento | Valor |
|---|---|
| Guest | `SEVER-01Eblanco` · `192.168.222.134/24` (DHCP) |
| Usuario / sesión | `SERVIDORES1\Administrador` · sesión 1 |
| Python | 3.13.9 en `C:\Program Files\Python313` |
| Proyecto en el guest | `C:\opencode-agent` |
| Tarea programada | `OpenCode Guest MCP` · Interactive · Highest · AtLogOn |
| Firewall guest | TCP 8765 solo desde `192.168.222.1` |
| Config host | `C:\Users\Enoc\.config\opencode\opencode.json` |
| Capturas | `C:\Users\Enoc\Desktop\iss2` (shared folder `iss2`) |

Archivos en el guest:

- `server.py` — servidor MCP (fuente: `C:\Users\Enoc\guest-vmware-mcp\server.py`)
- `token.txt` — bearer token (43 caracteres)
- `server.log` — log con rotación a 5 MB al arrancar
- `evidence\` — respaldo local si el shared folder no está montado
- `tmp\` — scripts `.ps1` temporales

## Capturas

`screenshot` y `save_evidence` escriben directamente en la carpeta compartida de
VMware:

- Guest: `\\vmware-host\Shared Folders\iss2`
- Host: `C:\Users\Enoc\Desktop\iss2`

Configuración usada (persiste en el `.vmx`):

```powershell
vmrun -T ws addSharedFolder "<vmx>" iss2 "C:\Users\Enoc\Desktop\iss2"
vmrun -T ws enableSharedFolders "<vmx>"
```

Si el share no está disponible, el servidor guarda en
`C:\opencode-agent\evidence` y sigue funcionando; cuando vuelve el share,
retoma la carpeta del host automáticamente.

## Herramientas

Sistema: `run_powershell`, `run_command`, `get_system_info`, `list_services`,
`read_file`, `write_file`, `list_dir`.

GUI: `screenshot`, `save_evidence`, `click`, `move_mouse`, `drag`, `scroll`,
`type_text`, `press_keys`, `list_windows`, `focus_window`, `get_clipboard`,
`set_clipboard`.

Las coordenadas de ratón son **absolutas del escritorio del guest** (1164×626
actualmente). `screenshot` devuelve la imagen completa, así que se calculan
directamente sobre ella.

`focus_window` activa la ventana y enfoca el control hijo del centro sin hacer
clic; `type_text` usa el portapapeles automáticamente si hay `ñ`, tildes, etc.

## Operación

Con el venv que tiene `pywinrm`:

```powershell
# Estado de la tarea, health y proceso
C:\Users\Enoc\vmware-visual-mcp\.venv\Scripts\python.exe C:\Users\Enoc\guest-vmware-mcp\deploy.py --status

# Subir server.py tras un cambio y reiniciar la tarea
C:\Users\Enoc\vmware-visual-mcp\.venv\Scripts\python.exe C:\Users\Enoc\guest-vmware-mcp\deploy.py
```

Desde OpenCode, sin salir de la conversación:

- `run_powershell` con `Get-Content C:\opencode-agent\server.log -Tail 50`
- health directo: <http://192.168.222.134:8765/health>
- lista de servidores MCP: `opencode.cmd mcp list`

## Seguridad

- El endpoint exige `Authorization: Bearer <token>`; sin token responde 401.
- El firewall del guest solo permite el puerto 8765 desde `192.168.222.1`.
- El token está en `C:\opencode-agent\token.txt` y en `opencode.json`.

Para rotarlo:

1. Generar uno nuevo: `python -c "import secrets; print(secrets.token_urlsafe(32))"`.
2. Escribirlo en `C:\opencode-agent\token.txt` (sin salto de línea).
3. Actualizar `headers.Authorization` de `guest-vmware` en `opencode.json`.
4. Reiniciar la tarea (`deploy.py --status` no basta; usar `deploy.py` o
   `Stop-ScheduledTask` + `Start-ScheduledTask`).

## Limitaciones y notas

- La **sesión 1 debe estar iniciada y desbloqueada**. Si Windows bloquea la
  sesión, `screenshot` sale negro y `SendInput` no llega a las ventanas.
- La IP es **DHCP**. Si el lease cambia, actualizar `url` en `opencode.json`.
  Opcional: reserva DHCP en VMnet8 o IP estática en el guest.
- No hay autologon configurado: tras reiniciar la VM hay que iniciar sesión para
  que la tarea `AtLogOn` arranque el bridge. Se puede activar autologon si se
  quiere que vuelva solo.
- OpenCode 2.1.4 recarga la config MCP en caliente; si una versión futura no lo
  hace, reiniciar OpenCode y continuar la misma sesión.

## Troubleshooting

| Síntoma | Qué revisar |
|---|---|
| `opencode mcp list` no lo muestra | `url`/`headers` en `opencode.json`, IP del guest |
| 401 | token distinto entre `token.txt` y `opencode.json` |
| Timeout / health falla | tarea parada, puerto 8765, firewall, `server.log` |
| Capturas negras | sesión bloqueada o desconectada |
| La tarea no arranca | `Get-ScheduledTaskInfo` (`267011` = nunca ejecutada, `267009` = ejecutándose) y el log de TaskScheduler |

Evidencia de la prueba inicial: `C:\Users\Enoc\Desktop\iss2\002-notepad-acentos.png`
(Notepad con acentos y ñ escritos desde OpenCode, sin clic manual previo).
