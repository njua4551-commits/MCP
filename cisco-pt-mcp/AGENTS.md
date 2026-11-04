# Reglas para trabajar con Cisco Packet Tracer (MCP `cisco-pt-mcp`)

- Antes de empezar llama a `pt_status` (¿PT conectado?) y `pt_docs` (API disponible).
- Nombres: PC1, PC2…, Printer1…, SW1, R1. Direccionamiento: LAN 192.168.1.0/24, gateway .1.
- Orden: `pt_add_device` → `pt_add_link` → `pt_configure_pc` / `pt_configure_ios` → verificar.
- Cables: PC/Printer↔switch = `straight`; switch↔switch y router↔PC = `cross`; `auto` si dudas.
- Verifica siempre con `pt_get_network` y `pt_ping` al terminar.
- Si un método de la API no existe, NO adivines: enuméralo con `for (var k in obj)` usando `pt_execute_js`.
- Si algo falla, lee el mensaje de error, corrige y reintenta una vez antes de reportar.
- Usa `pt_capture` (Windows) para comparar la topología real con la pedida.
