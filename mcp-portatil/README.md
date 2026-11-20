# MCP portátil

Cuatro servidores independientes del proveedor de IA. Un cliente con MCP local los inicia por **stdio**; una IA con acceso a terminal puede usar `mcp-ia list` y `mcp-ia call`. Un chat sin herramientas, terminal ni conector no puede ejecutarlos.

## En otro equipo

Descomprime el kit en una carpeta permanente. Desde esa carpeta, con **Node.js 22+ y npm**:

```sh
npm ci
npx playwright install chromium
node mcp.mjs config json
```

Chromium solo es necesario para Playwright. En Linux sin bibliotecas de navegador, usa `npx playwright install --with-deps chromium` en una distribución compatible. Para habilitar el comando corto `mcp-ia` desde cualquier directorio: `npm link` (o usa `node` y la ruta completa a `mcp.mjs`).

## Conectar un cliente

Genera el formato **en el equipo donde corre el cliente**. El resultado contiene las rutas locales correctas a Node y al kit, sin contraseñas. Fusiona las entradas con el archivo existente; vuelve a generarlas si mueves el kit.

| Cliente | Comando | Destino |
|---|---|---|
| Claude Code, Claude Desktop, Cursor, Gemini CLI y clientes con `mcpServers` | `node mcp.mjs config json` | `.mcp.json` de Claude Code, `claude_desktop_config.json`, `~/.cursor/mcp.json` o `~/.gemini/settings.json` |
| VS Code / Code - OSS | `node mcp.mjs config vscode` | `MCP: Open User Configuration` o `.vscode/mcp.json` |
| Codex CLI | `node mcp.mjs config codex` | `~/.codex/config.toml` |
| OpenCode V2 | `node mcp.mjs config opencode` | `mcp.servers` en `opencode.json` |

Puedes seleccionar servidores: `node mcp.mjs config codex playwright cisco-pt-mcp`. Para otro cliente stdio, el ejecutable es Node y los argumentos son **tres entradas separadas**: la ruta absoluta a `mcp.mjs`, `serve` y el nombre del servidor.

## Usar desde una terminal

```sh
mcp-ia list playwright
mcp-ia call playwright browser_navigate '{"url":"https://example.com"}'
mcp-ia call cisco-pt-mcp pt_status
mcp-ia call vmware vm_list
mcp-ia call windows-control-mcp get_system_info
```

`list` devuelve los nombres y esquemas en JSON. `call` acepta `{}` por defecto, un objeto JSON como argumento o `-` para leerlo de stdin (útil en Windows). Los errores de herramienta dan código de salida distinto de cero. Cada `call` abre una sesión nueva; para mantener las pestañas entre operaciones usa el servidor desde un cliente MCP persistente.

## Qué necesita cada servidor

- **`playwright`**: Chromium headless, con un perfil aislado por cliente. Detecta el navegador instalado por Playwright. Opcionales: `PLAYWRIGHT_MCP_EXECUTABLE_PATH`, `PLAYWRIGHT_BROWSERS_PATH`, `PLAYWRIGHT_MCP_OUTPUT_DIR`. La salida predeterminada está en `mcp-portatil/playwright`, dentro del directorio temporal del sistema.
- **`cisco-pt-mcp`**: Packet Tracer y el servidor deben compartir el mismo `localhost`. Lo más rápido: `Extensions → Scripting → Configure PT Script Module → Add` e importa `cisco/MCP-Bridge.pts` (ya trae el módulo, la interfaz y los permisos). Si prefieres montarlo a mano, en `Extensions → Scripting → Edit File Script Module` carga `main.js`, `runcode.js` y `interface/bridge.html` de `cisco/pt-extension/`; guarda y vuelve a abrir el `.pkt`. Después, `Extensions → MCP Bridge`, conecta al puerto `37101`. `pt_status` debe indicar `packetTracerConnected: true`; `listening: true` por sí solo no basta. Si cambias `PT_MCP_PORT` o `PT_MCP_TOKEN`, ajusta también la extensión. `pt_capture` solicita un PNG del lienzo a la API de Packet Tracer; en Windows también puede capturar la ventana.
- **`vmware`**: se ejecuta en el **host** con Python 3 y `vmrun` de VMware Workstation o Fusion. `VMWARE_VMS_DIR` selecciona el directorio que contiene los `.vmx` o sus carpetas. Puedes fijar `MCP_PYTHON`, `VMRUN` (ruta al ejecutable) y `VMWARE_HOST_TYPE` (`ws`/`fusion`). Las operaciones dentro del invitado que requieren credenciales usan `VMWARE_GUEST_USER` y `VMWARE_GUEST_PASS`. Para ratón y teclado usa `windows-control-mcp`.
- **`windows-control-mcp`**: el servicio MCP existente debe estar activo en una VM Windows accesible desde el cliente. Para controlar el escritorio, la sesión debe estar desbloqueada. El adaptador usa Streamable HTTP con Bearer y lo presenta a la IA por stdio. En clientes que solo aceptan MCP remoto también puedes registrar directamente la URL del servicio con su cabecera de autenticación.

### Conectar otro cliente a una VM existente

En el equipo del cliente, crea `~/.mcp-portatil/` (en Windows, dentro de tu carpeta de usuario). Guarda ahí `last_ip.txt` con la IP del invitado y `token.txt` con el token del servicio, legible solo por tu usuario. El adaptador usa `http://IP:8765/mcp`. En la instalación Linux original reutiliza los archivos de `~/.local/share/mcp/guest-vmware-mcp/` si no existe `~/.mcp-portatil/`.

Para otra URL o HTTPS, configura **en el entorno del servidor** `MCP_GUEST_URL` y `MCP_GUEST_TOKEN_FILE` (ruta absoluta), o `MCP_GUEST_TOKEN`. También puedes fijar `MCP_GUEST_DIR` para el par de archivos. Si el cliente filtra variables heredadas, decláralas en su configuración; en Codex se usa `env_vars`. La VM debe admitir la conexión desde ese host: copiar el kit no cambia su red ni su firewall.

## Reproducir la demo de Cisco

[Instalación paso a paso de Cisco, prueba de conexión y archivos de ejemplo](cisco/README.md).

Con un `.pkt` vacío y el bridge conectado, ejecuta `node cisco/probar-lan.mjs` desde el kit. Crea 6 PC y 2 impresoras conectados a un switch, lee de vuelta las 8 conexiones y comprueba el ping de PC1 a PC2. Si ya hay dispositivos, solo verifica si coinciden con esa LAN.

Para la segunda escena, pide a la IA: «Añade un AccessPoint-PT conectado a SW1 y 4 Laptop-PT con `wifi: true`. Configúralos en Wireless0 con IP libres de la misma subred y comprueba ping desde cada portátil a PC1». Para la tercera: «Amplía la topología con un HomeRouter-PT-AC, una luz (Light), un ventilador (Fan) y una puerta (Door); verifica su asociación y conectividad antes de dar la práctica por hecha». La interpretación de la guía PDF o su imagen depende del cliente de IA.
