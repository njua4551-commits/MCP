# cisco-packet-tracer-mcp

MCP independiente para automatizar Cisco Packet Tracer desde OpenCode (Windows).
No comparte nada con `vmware-visual-mcp`.

## Estado

- **Fase 0 (Descubrimiento): completada.**
- **Fase 2 (Control visual seguro): completada.** `gui.py` (enfoque verificado, clic relativo al cliente, teclado, espera, guardas) + tools `pt_focus_window`, `pt_click`, `pt_type`, `pt_wait`, `pt_point_here`, `pt_open_file`, `pt_open_device_cli`.
- **OCR nativo de Windows** (`src/cisco_pt/ocr.py`, paquetes `winrt-*`, idiomas es-ES/es-MX/en-US): lee etiquetas del lienzo y salida de CLI sin enviar imágenes fuera.
- Modo por defecto: `read_only` (`config.READ_ONLY = True`). Clic/teclado requieren `confirm=True`.
- El MCP antiguo `cisco-pt` (`C:\Users\Enoc\pt-mcp`) fue retirado de la config y eliminado; respaldo en `%TEMP%\opencode\pt-mcp-backup-*.zip`.

## Hallazgos de Fase 2

- Las ventanas de dispositivo de PT 8.2.2 son **ventanas Qt separadas** (`title` = nombre del equipo), no pestañas del frame principal. Verificar cambios comparando el frame principal da falsos negativos.
- Las coordenadas de la captura **no** son coordenadas de cliente: usar `window_manager.image_to_client()` (diferencia = barra de título, 23 px).
- `PrintWindow` no captura menús desplegables (son ventanas propias); los tooltips de Qt tienen owner y no son diálogos modales.
- Prueba: doble clic en `Router1` → ventana `Router1` con pestañas Physical/Config/CLI; pestaña CLI activada con banner IOS. Evidencia `evidence/002-r1-cli-abierta.png`.
- Pendiente para Fase 3: los `Enter` sintéticos no avanzan el terminal (falta enfocar el widget de texto de la CLI).

## Entorno verificado

- Cisco Packet Tracer **8.2.2.400**
- `C:\Program Files\Cisco Packet Tracer 8.2.2\bin\PacketTracer.exe`
- Proceso: `PacketTracer.exe`, ventana principal: título `Cisco Packet Tracer`
- Captura fiable: `PrintWindow` + `PW_RENDERFULLCONTENT` (funciona con la ventana en segundo plano)

## Instalación

```cmd
cd /d C:\Users\Enoc\cisco-packet-tracer-mcp
python -m venv .venv
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## Prueba de Fase 0

```cmd
.venv\Scripts\python.exe tests\fase0_check.py
```

Salida: JSON compacto con versión, ruta, ventana (hwnd/pid/rect), método de
captura, métricas y `no_side_effects`. Evidencia en
`evidence/001-topologia-inicial.png`.

Criterio de salida cumplido: captura válida (1366x738, std 67.6, 638 colores)
sin mover el cursor ni cambiar la ventana en primer plano, con PT en segundo plano.

## Estructura

```
config.py                     rutas, proceso/título, umbrales de captura
src/cisco_pt/window_manager.py localizar ventana, rect real, versión instalada
src/cisco_pt/capture.py        PrintWindow -> BitBlt -> recorte escritorio + validación
tests/fase0_check.py           prueba de aceptación de Fase 0
```

## Siguiente fase

Fase 2: control visual seguro (enfoque de ventana, clic relativo, teclado,
lectura de pantalla) con `read_only` por defecto y pruebas en laboratorio descartable.
