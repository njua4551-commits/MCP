# opencode-mcps

MCP servers para [OpenCode](https://opencode.ai) listos para usar en otra máquina.

## Contenido

| Servidor | Tipo | Origen | Incluido en repo |
| --- | --- | --- | --- |
| `vmware-visual-mcp` | local (Python) | Captura/control de ventanas VMware Workstation | Sí (`mcp/vmware-visual-mcp`) |
| `playwright` | local (npx) | [`@playwright/mcp`](https://www.npmjs.com/package/@playwright/mcp) | No (se instala con npx) |
| `guest-vmware` | remoto (HTTP) | Control nativo dentro de la VM Windows | Sí (`mcp/guest-vmware-mcp`) |

## Instalación

1. Copia `opencode.jsonc` en tu configuración global `~/.config/opencode/opencode.json`
   (en Windows: `C:\Users\<usuario>\.config\opencode\opencode.json`), o en
   `opencode.json` del proyecto.
2. Ajusta `cwd`/`command` a la ruta real de este repo.
3. Prepara el MCP local de VMware:

```powershell
cd mcp\vmware-visual-mcp
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
```

4. Define las variables de entorno (ver `.env.example`):

```powershell
setx GUEST_MCP_TOKEN "tu-token"
setx GUEST_MCP_URL "http://IP-DEL-INVITADO:8765/mcp"
```

5. Servidor del invitado (se ejecuta **dentro** de la VM):

```powershell
cd mcp\guest-vmware-mcp
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Guarda el valor impreso en `C:\opencode-agent\token.txt` dentro de la VM y
arranca `python server.py` en su sesión interactiva. Detalles en
`mcp/guest-vmware-mcp/README.md`.

6. Verifica la conexión:

```sh
opencode mcp list
```

## Requisitos

- Python 3.10+ con Tk/pywin32 (Windows) para `vmware-visual-mcp`.
- Node.js 18+ para Playwright (`npx -y @playwright/mcp`).
- VMware Workstation instalado si usas `VMRUN_PATH`/`vmrun`.
- Chrome con CDP en `http://127.0.0.1:9222` si usas el modo CDP de Playwright.

## Seguridad

No subas tokens ni rutas personales. Usa `{env:VAR}` en la configuración y
mantén `.env` fuera de git.
