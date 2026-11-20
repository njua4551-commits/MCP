# Cisco Packet Tracer por MCP

Este módulo permite a un cliente MCP crear dispositivos y cables, configurar interfaces, hacer ping y capturar el lienzo real de Packet Tracer. Se probó con **Packet Tracer 9.0.1 en Linux**.

### 1. Instalar el servidor y registrarlo en la IA

Instala Node.js 22 o superior y Cisco Packet Tracer desde el sitio oficial de Cisco Networking Academy. Abre Packet Tracer, completa el inicio de sesión si lo solicita y llega al lienzo. Ejecuta el servidor MCP **en el mismo equipo que Packet Tracer**.

```sh
git clone https://github.com/njua4551-commits/MCP.git
cd MCP/mcp-portatil
npm ci
node mcp.mjs config json cisco-pt-mcp
```

Importa la entrada generada en la configuración MCP de tu cliente y activa `cisco-pt-mcp`. Para VS Code, Codex u OpenCode sustituye `json` por `vscode`, `codex` u `opencode`; consulta los [destinos de configuración](../README.md#conectar-un-cliente). Chromium no hace falta para Cisco.

### 2. Conectar Packet Tracer

1. En Packet Tracer abre **Extensions → Scripting → Configure PT Script Modules → Add** y selecciona [`MCP-Bridge.pts`](MCP-Bridge.pts) de esta carpeta.
2. Selecciona **Cisco MCP Bridge** y pulsa **Start** si está detenido. Si aparece **Stop**, ya está en marcha.
3. Abre **Extensions → MCP Bridge**. Usa `http://127.0.0.1:37101` y pulsa **Conectar** si aún no está conectado. Deja Packet Tracer y el cliente MCP abiertos.
4. Pide a la IA «ejecuta `pt_status`». El resultado debe incluir **`packetTracerConnected: true`**. `listening: true` solo indica que el servidor está escuchando.

### 3. Usarlo

- **Solo diseño:** en un lienzo vacío, pide «Crea un switch S1 y dos PC llamados PC1 y PC2. Conecta ambos al switch sin asignar IP. Verifica los cables con `pt_get_network`». Guarda el trabajo con **File → Save As**.
- **LAN con conectividad:** desde `MCP/mcp-portatil`, ejecuta `node cisco/probar-lan.mjs` sobre un lienzo vacío. Crea seis PC y dos impresoras, verifica ocho cables y comprueba el ping PC1 → PC2.
- **Abrir ejemplos:** en **File → Open** selecciona [la topología CCNA sin configurar](topologia-ccna.pkt) o [la demo LAN, Wi-Fi e IoT](demo-video.pkt). Pide «lista los dispositivos» o «captura el lienzo con `pt_capture`».

Si al cambiar de proyecto aparece `packetTracerConnected: false`, vuelve a abrir **Extensions → MCP Bridge** y reconecta. Si cambias `PT_MCP_PORT` o estableces `PT_MCP_TOKEN` en el cliente, usa el mismo puerto y token en la ventana del módulo.
