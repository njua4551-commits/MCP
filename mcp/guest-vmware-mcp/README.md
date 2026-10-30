# guest-vmware-mcp

Servidor MCP que se ejecuta **dentro** de una VM Windows y expone control nativo
al host por HTTP (Streamable HTTP + Bearer token).

## Herramientas

- Sistema: `run_powershell`, `run_command`, `get_system_info`, `list_services`,
  `read_file`, `write_file`, `list_dir`.
- GUI: `screenshot`, `save_evidence`, `click`, `move_mouse`, `drag`, `scroll`,
  `type_text`, `press_keys`, `list_windows`, `focus_window`, `get_clipboard`,
  `set_clipboard`.

## Requisitos (dentro de la VM)

- Windows con sesión interactiva iniciada y desbloqueada (sin sesión, `screenshot`
  sale negro y `SendInput` no funciona).
- Python 3.10+ y las dependencias de `requirements.txt`.

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
```

## Token

El servidor no arranca sin `token.txt` (mínimo 24 caracteres). Por defecto se lee
de `C:\opencode-agent\token.txt`, o de `%GUEST_MCP_HOME%\token.txt`.

```powershell
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Guarda el valor en `token.txt` y usa el mismo en el host (`GUEST_MCP_TOKEN`).

## Arranque

```powershell
python server.py
```

Variables opcionales:

| Variable | Por defecto | Uso |
| --- | --- | --- |
| `GUEST_MCP_HOME` | `C:\opencode-agent` | Carpeta de trabajo, log, token y evidencias |
| `GUEST_MCP_PORT` | `8765` | Puerto HTTP |
| `GUEST_MCP_HOST` | `0.0.0.0` | Interfaz de escucha |
| `GUEST_MCP_SHARED_FOLDER` | `\\vmware-host\Shared Folders\opencode` | Evidencias; si no existe, usa `evidence\` local |

Rutas: `/mcp` (MCP protegido) y `/health` (sin auth).

## Conectar desde OpenCode (host)

```jsonc
{
  "mcp": {
    "servers": {
      "guest-vmware": {
        "type": "remote",
        "url": "{env:GUEST_MCP_URL}",
        "oauth": false,
        "headers": { "Authorization": "Bearer {env:GUEST_MCP_TOKEN}" }
      }
    }
  }
}
```

```powershell
setx GUEST_MCP_URL "http://IP-DEL-INVITADO:8765/mcp"
setx GUEST_MCP_TOKEN "el-mismo-token.txt"
```

Abre TCP 8765 en el firewall del invitado solo para la IP del host.

## Notas

- Para que arranque al iniciar sesión, crea una tarea programada (AtLogOn,
  Interactive, Highest) que ejecute `pythonw.exe server.py` en la sesión 1.
- `screenshot` devuelve el escritorio completo; las coordenadas son absolutas.
