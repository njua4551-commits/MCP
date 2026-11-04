# MCP Servers para OpenCode

Colección de servidores [MCP](https://modelcontextprotocol.io/) usados con OpenCode
para automatizar **VMware**, **Cisco Packet Tracer**, **Playwright** y una **VM invitada**.

| MCP | Tipo | Lenguaje | Qué hace |
|---|---|---|---|
| `vmware-visual-mcp` | local (stdio) | Python | Localiza/enfoca la ventana de VMware Workstation, captura pantalla, mueve ratón y teclado del host. |
| `guest-vmware-mcp` | remoto (HTTP) | Python | Corre dentro de la VM: PowerShell, archivos, portapapeles, capturas y control real del escritorio del invitado. |
| `cisco-pt-mcp` | local (stdio) | TypeScript/Node | Controla Packet Tracer vía su API de scripting y un puente HTTP: crear topologías, configurar PCs/IOS, ping, capturas. |
| `cisco-packet-tracer-mcp` | local (stdio) | Python | Alternativa basada en GUI + OCR: encuentra la ventana de Packet Tracer y opera por imagen. |
| `playwright-mcp` | local (stdio) | Node (npm) | Navegador real vía CDP; solo se versiona la configuración (paquete oficial `@playwright/mcp`). |

## Estructura

```
vmware-visual-mcp/        server.py + requirements.txt
guest-vmware-mcp/         server.py + deploy.py + requirements.txt
cisco-pt-mcp/             src/ (TS) + dist/ (JS compilado) + pt-extension/
cisco-packet-tracer-mcp/  server.py + src/cisco_pt/ + tests/
playwright-mcp/           README + package.json (config del paquete oficial)
opencode.json.example     Configuración de los 5 MCP para OpenCode
```

## Requisitos

- Windows 10/11
- Python 3.11+ (los MCP Python usan `mcp`, `pyautogui`, `psutil`, `pillow`, `pytesseract`)
- Node.js 20+ (para `cisco-pt-mcp` y `playwright-mcp`)
- VMware Workstation, Cisco Packet Tracer 8.x, Google Chrome

## Instalación

```powershell
# MCP Python (repetir por cada uno)
cd vmware-visual-mcp
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt

# MCP TypeScript
cd cisco-pt-mcp
npm install
npm run build

# Playwright
npm install -g @playwright/mcp@0.0.83
```

En Packet Tracer hay que cargar la extensión de `cisco-pt-mcp/pt-extension/`
(`main.js` + `interface/bridge.html`) desde *Extensions → Scripting → Run*.

## Configuración en OpenCode

Copia `opencode.json.example` y ajusta rutas absolutas:

```powershell
Copy-Item opencode.json.example "$env:USERPROFILE\.config\opencode\opencode.json"
```

Ejemplo mínimo:

```jsonc
{
  "mcp": {
    "vmware-visual-mcp": {
      "type": "local",
      "command": ["C:/ruta/vmware-visual-mcp/.venv/Scripts/python.exe",
                  "C:/ruta/vmware-visual-mcp/server.py"]
    },
    "cisco-pt-mcp": {
      "type": "local",
      "command": ["node", "C:/ruta/cisco-pt-mcp/dist/server.js"],
      "environment": { "PT_MCP_PORT": "37101", "PT_MCP_TIMEOUT_MS": "62000" }
    }
  }
}
```

## Seguridad

- `guest-vmware-mcp` usa un **bearer token**. No subas `token.txt` ni `.env`
  (ya están en `.gitignore`); genera uno nuevo con `deploy.py`.
- `cisco-pt-mcp` abre un puente HTTP local en `PT_MCP_PORT` (por defecto 37101):
  no lo expongas fuera de `localhost`.
- Las carpetas `evidence/`, `logs/` y las capturas pueden contener datos de tu
  red; están excluidas del repo.

## Licencia

MIT.
