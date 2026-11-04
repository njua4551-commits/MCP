#!/usr/bin/env node
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";
import { PtBridge } from "./bridge.js";
import { captureWindow } from "./capture.js";
import * as snip from "./snippets.js";
const bridge = new PtBridge();
await bridge.start();
const server = new McpServer({ name: "pt-mcp", version: "1.0.0" });
const text = (v, isError = false) => ({
    content: [{ type: "text", text: typeof v === "string" ? v : JSON.stringify(v, null, 2) }],
    isError,
});
const reply = (r) => (r.ok ? text(r.result ?? { ok: true }) : text({ error: r.error }, true));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
// ---------- Tools -------------------------------------------------------------------------------
server.registerTool("pt_status", {
    title: "Estado del bridge",
    description: "Indica si el bridge HTTP está activo y si Packet Tracer está conectado. Llámala primero si algo falla.",
    annotations: { readOnlyHint: true },
}, async () => text(bridge.status()));
server.registerTool("pt_docs", {
    title: "Documentación de la API de PT",
    description: "Devuelve la cheat-sheet de la API de scripting de Packet Tracer y la técnica para descubrir métodos. LEER antes de usar pt_execute_js.",
    annotations: { readOnlyHint: true },
}, async () => text(snip.DOCS));
server.registerTool("pt_execute_js", {
    title: "Ejecutar JS en Packet Tracer",
    description: "Ejecuta código JavaScript en el script host de Packet Tracer (objeto global `ipc`). El código es el CUERPO de una función: " +
        "usa `return` para devolver datos (JSON-serializables). Es la herramienta más potente: permite todo lo que expone la API IPC. " +
        "Si un método no existe, enumera los miembros con `for (var k in obj)`. Consulta pt_docs.",
    inputSchema: {
        code: z.string().describe("Cuerpo de función JS (ES5 preferido). Debe usar return."),
        timeout_ms: z.number().int().min(1000).max(120000).optional(),
    },
}, async ({ code, timeout_ms }) => reply(await bridge.run(code, timeout_ms)));
server.registerTool("pt_get_network", {
    title: "Snapshot de la red",
    description: "Lista todos los dispositivos (nombre, modelo, puertos) y los cables (extremos y tipo).",
    annotations: { readOnlyHint: true },
}, async () => reply(await bridge.run(snip.getNetwork())));
server.registerTool("pt_add_device", {
    title: "Añadir dispositivo",
    description: "Coloca un dispositivo en el canvas lógico. Ej.: model 'PC-PT', '2911', '2960-24TT', 'Printer-PT', 'Server-PT'.",
    inputSchema: {
        name: z.string(),
        model: z.string(),
        x: z.number().default(100),
        y: z.number().default(100),
    },
}, async ({ name, model, x, y }) => reply(await bridge.run(snip.addDevice(name, model, x, y))));
server.registerTool("pt_add_link", {
    title: "Conectar dispositivos",
    description: "Crea un cable. cable: straight | cross | roll | fiber | serial | console | wireless | auto. " +
        "Interfaces típicas: FastEthernet0 (PC), FastEthernet0/1 (switch 2960), GigabitEthernet0/0 (router).",
    inputSchema: {
        device1: z.string(), interface1: z.string(),
        device2: z.string(), interface2: z.string(),
        cable: z.string().default("auto"),
    },
}, async (a) => reply(await bridge.run(snip.addLink(a.device1, a.interface1, a.device2, a.interface2, a.cable))));
server.registerTool("pt_configure_pc", {
    title: "Configurar IP de un PC/Laptop/Printer",
    description: "Aplica IP estática o DHCP en FastEthernet0.",
    inputSchema: {
        device: z.string(),
        ip: z.string().optional(), mask: z.string().optional(),
        gateway: z.string().optional(), dns: z.string().optional(),
        dhcp: z.boolean().optional(),
    },
}, async (a) => reply(await bridge.run(snip.configurePc(a.device, a.ip, a.mask, a.gateway, a.dns, a.dhcp))));
server.registerTool("pt_configure_ios", {
    title: "Configurar router/switch (IOS)",
    description: "Envía una lista de comandos de configuración global (sin 'configure terminal') y hace 'write memory'.",
    inputSchema: { device: z.string(), commands: z.array(z.string()).min(1) },
}, async ({ device, commands }) => reply(await bridge.run(snip.configureIos(device, commands))));
async function runCli(device, command, waitMs) {
    const start = await bridge.run(snip.cliStart(device, command), 15_000);
    if (!start.ok)
        return start;
    const id = start.result?.id;
    if (!id)
        return { ok: false, error: "cliStart no devolvió id" };
    const deadline = Date.now() + waitMs;
    let last = { out: "", done: false };
    while (Date.now() < deadline) {
        await sleep(250);
        const r = await bridge.run(snip.cliRead(id), 15_000);
        if (!r.ok)
            return r;
        last = r.result;
        if (last.done)
            break;
    }
    return { ok: true, result: { output: last.out, finished: last.done } };
}
server.registerTool("pt_run_show", {
    title: "Ejecutar comando y leer salida (EXPERIMENTAL)",
    description: "Ejecuta UN comando en la CLI de un dispositivo (p. ej. 'show ip interface brief', en modo privilegiado) y devuelve la salida. " +
        "Usa eventos asíncronos de PT; si la salida sale vacía consulta pt_docs.",
    inputSchema: {
        device: z.string(), command: z.string(),
        wait_ms: z.number().int().min(500).max(60000).default(5000),
    },
}, async ({ device, command, wait_ms }) => reply(await runCli(device, command, wait_ms)));
server.registerTool("pt_ping", {
    title: "Ping desde un dispositivo (EXPERIMENTAL)",
    description: "Hace ping desde un PC/router a una IP y devuelve la salida (espera hasta 15 s por defecto).",
    inputSchema: {
        source: z.string(), target: z.string(),
        wait_ms: z.number().int().min(1000).max(60000).default(15000),
    },
}, async ({ source, target, wait_ms }) => reply(await runCli(source, `ping ${target}`, wait_ms)));
server.registerTool("pt_capture", {
    title: "Captura de pantalla de Packet Tracer",
    description: "Devuelve una imagen PNG de la ventana de Packet Tracer (sólo Windows). Útil para que el modelo VEA la topología.",
    annotations: { readOnlyHint: true },
}, async () => {
    const c = await captureWindow();
    if (!c.ok)
        return text({ error: c.error }, true);
    return { content: [{ type: "image", data: c.data, mimeType: "image/png" }] };
});
await server.connect(new StdioServerTransport());
console.error("[pt-mcp] servidor MCP listo (stdio)");
