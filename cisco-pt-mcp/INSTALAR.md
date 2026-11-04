# Instalación — Cisco Packet Tracer + OpenCode (Windows)

## 1. Servidor MCP (una sola vez)
```
cd pt-mcp
npm install
npm run build
```
(`dist/` ya viene compilado, pero `npm install` es necesario para las dependencias.)

## 2. Registrar en OpenCode
Copia `opencode.json` a tu carpeta de trabajo (o fusiónalo con el tuyo) y cambia
`C:/RUTA/A/pt-mcp/dist/server.js` por la ruta real, con `/` en lugar de `\`.
Comprueba: `opencode mcp list` → debe aparecer `cisco-pt-mcp`.
Opcional: copia `AGENTS.md` a tu carpeta de trabajo.

## 3. Bridge dentro de Packet Tracer (File Script Module)
1. Abre Packet Tracer y guarda un `.pkt` vacío (ej. `lab-mcp.pkt`).
2. `Extensions → Scripting → Edit File Script Module…`
3. Crea/pega estos archivos (carpeta `pt-extension/`):
   - `main.js` y `runcode.js` → scripts del módulo
   - `interface/bridge.html` → archivo web del módulo (nombre `bridge.html`)
4. Guarda, cierra y reabre el `.pkt`; acepta el aviso de seguridad.
5. El bridge se conecta solo. Para ver el log: `Extensions → MCP Bridge`
   (debe decir "Conectado" y "Servidor MCP alcanzado" cuando OpenCode esté abierto).

> Usa SIEMPRE ese `.pkt` como base de tus laboratorios (o copia el módulo a cada uno):
> un File Script Module solo corre en el archivo que lo contiene.

## 4. Prueba
En OpenCode:
> Con cisco-pt-mcp: llama a pt_status y pt_docs; crea 1 switch 2960-24TT, 4 PCs y 1 impresora,
> cablea, asigna 192.168.1.0/24 y haz pt_ping entre dos PCs.

## Si falla
| Síntoma | Qué hacer |
|---|---|
| "Packet Tracer no está conectado" | Abre `Extensions → MCP Bridge`; si dice Desconectado pulsa Conectar |
| "Servidor MCP no responde" (en el log) | Abre OpenCode; revisa que el puerto sea 37101 en ambos lados |
| Puerto ocupado | Solo una instancia de OpenCode a la vez, o cambia `PT_MCP_PORT` y el campo Servidor del bridge |
| `pt_ping`/`pt_run_show` vacíos | Son experimentales: pide al modelo enumerar `getCommandLine()` con `pt_execute_js` y ajustar |
| Timeout | Cierra diálogos abiertos en PT |

## Qué está probado
Servidor MCP + cola + 11 tools: ✅ test e2e con PT simulado.
Bridge dentro de PT real, `pt_ping`, `pt_run_show`, `pt_capture`: 🟡 no probados (sigue el patrón de PTBuilder-MCP).
Seguridad: define `PT_MCP_TOKEN` en `environment` y escríbelo en el campo Token del bridge.
