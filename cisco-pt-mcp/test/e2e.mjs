// Test e2e SIN Packet Tracer: cliente MCP real -> servidor -> bridge HTTP -> poller que imita al webview -> `ipc` simulado.
import assert from "node:assert/strict";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";

const PORT = 38000 + Math.floor(Math.random() * 1000); // puerto aleatorio: evita choques con servidores huérfanos
const BASE = `http://127.0.0.1:${PORT}`;

// ---- ipc simulado (sólo lo que usan los snippets) ----
function makeIpc() {
  const devices = [], links = []; let n = 0;
  const mkPorts = (type) => (type === 8 ? ["FastEthernet0"] : type === 1 ? [1,2,3,4].map(i => `FastEthernet0/${i}`) : ["GigabitEthernet0/0","GigabitEthernet0/1"]);
  const mkDevice = (type, model, auto) => {
    const d = { _name: auto, type, model, power: true, dhcp: false, ports: [], cmds: [] };
    d.ports = mkPorts(type).map((pn) => ({ n: pn, ip: null, getName: () => pn, getOwnerDevice: () => d._name,
      setIpSubnetMask(ip, m) { this.ip = ip + "/" + m; }, setDefaultGateway() {}, setDnsServerIp() {} }));
    Object.assign(d, {
      getName: () => d._name, setName: (x) => { d._name = x; }, getModel: () => model, getType: () => type,
      skipBoot() {}, setDhcpFlag(b) { d.dhcp = b; },
      getPortCount: () => d.ports.length, getPortAt: (i) => d.ports[i], getPort: (nm) => d.ports.find(p => p.n === nm),
      enterCommand(c, m) { d.cmds.push([c, m]); },
      getCommandLine() {
        const h = {};
        return { registerEvent: (ev, _s, cb) => { h[ev] = cb; },
          enterCommand(cmd) { setTimeout(() => { h.outputWritten && h.outputWritten(null, { newOutput: `OUT(${cmd})` });
                                                 h.commandEnded && h.commandEnded(null, {}); }, 400); } };
      },
    });
    return d;
  };
  const ws = { addDevice(type, model) { const d = mkDevice(type, model, `Dev${n++}`); devices.push(d); return d._name; },
    createLink(d1, i1, d2, i2, t) { const a = devices.find(d => d._name === d1)?.getPort(i1), b = devices.find(d => d._name === d2)?.getPort(i2);
      if (!a || !b) return false; links.push({ a, b, t }); return true; } };
  return { _devices: devices,
    appWindow: () => ({ getActiveWorkspace: () => ({ getLogicalWorkspace: () => ws }) }),
    network: () => ({ getDeviceCount: () => devices.length, getDeviceAt: (i) => devices[i], getDevice: (nm) => devices.find(d => d._name === nm),
      getLinkCount: () => links.length, getLinkAt: (i) => ({ getPort1: () => links[i].a, getPort2: () => links[i].b, getConnectionType: () => links[i].t }) }) };
}

// ---- imita bridge.html: polling + runCode + POST result ----
const ipc = makeIpc();
function runCode(code) {            // = pt-extension/runcode.js
  try { const v = new Function("ipc", code)(ipc); return { success: true, result: v === undefined ? null : JSON.parse(JSON.stringify(v)) }; }
  catch (e) { return { success: false, error: e.message }; }
}
let polling = false;
async function pollLoop() {
  while (polling) {
    const r = await fetch(`${BASE}/next`).catch(() => null);
    if (r && r.status === 200) {
      const job = await r.json(); const out = runCode(job.code);
      await fetch(`${BASE}/result`, { method: "POST", headers: { "Content-Type": "text/plain" },
        body: JSON.stringify({ id: job.id, ok: out.success, result: out.result, error: out.error }) });
    }
    await new Promise(r => setTimeout(r, 100));
  }
}

const transport = new StdioClientTransport({ command: "npx", args: ["tsx", "src/server.ts"], env: { ...process.env, PT_MCP_PORT: String(PORT) }, stderr: "pipe" });
const client = new Client({ name: "e2e", version: "0" });
await client.connect(transport);
const call = async (name, args = {}) => { const r = await client.callTool({ name, arguments: args });
  const t = r.content[0]; return { isError: !!r.isError, text: t.type === "text" ? t.text : `[${t.type}]`, raw: r }; };
const json = (r) => JSON.parse(r.text);

try {
const tools = (await client.listTools()).tools.map(t => t.name);
console.log("tools:", tools.join(", "));
assert.equal(tools.length, 11);

// 1) sin PT conectado: error claro y rápido
let r = await call("pt_get_network");
assert.ok(r.isError && /no está conectado/.test(r.text)); console.log("✔ sin PT conectado → error claro");

// 2) PT conecta
polling = true; pollLoop(); await new Promise(r => setTimeout(r, 600));
assert.equal(json(await call("pt_status")).packetTracerConnected, true); console.log("✔ PT conectado");

// 3) construir una LAN
for (const [name, model, x, y] of [["SW1","2960-24TT",200,100],["PC1","PC-PT",100,200],["PC2","PC-PT",300,200],["PRN1","Printer-PT",400,200]]) {
  r = await call("pt_add_device", { name, model, x, y }); assert.ok(!r.isError, r.text); }
assert.ok(!(await call("pt_add_link", { device1:"PC1", interface1:"FastEthernet0", device2:"SW1", interface2:"FastEthernet0/1", cable:"straight" })).isError);
assert.ok(!(await call("pt_add_link", { device1:"PC2", interface1:"FastEthernet0", device2:"SW1", interface2:"FastEthernet0/2", cable:"straight" })).isError);
assert.ok(!(await call("pt_configure_pc", { device:"PC1", ip:"192.168.1.10", mask:"255.255.255.0", gateway:"192.168.1.1" })).isError);
const net = json(await call("pt_get_network"));
assert.equal(net.deviceCount, 4); assert.equal(net.connectionCount, 2);
assert.deepEqual([net.connections[0].from, net.connections[0].to], ["PC1", "SW1"]);
console.log("✔ add_device / add_link / configure_pc / get_network:", net.deviceCount, "dispositivos,", net.connectionCount, "cables");

// 4) errores accionables
r = await call("pt_add_device", { name: "X", model: "NoExiste", x: 1, y: 1 }); assert.ok(r.isError && /Modelo desconocido/.test(r.text));
r = await call("pt_add_link", { device1:"PC1", interface1:"Nope", device2:"SW1", interface2:"FastEthernet0/3", cable:"straight" }); assert.ok(r.isError && /createLink falló/.test(r.text));
r = await call("pt_execute_js", { code: "throw new Error('boom')" }); assert.ok(r.isError && /boom/.test(r.text));
console.log("✔ errores devueltos al modelo con mensaje útil");

// 5) execute_js, cli, configure_ios
assert.equal(json(await call("pt_execute_js", { code: "return ipc.network().getDeviceCount()" })), 4);
r = await call("pt_ping", { source: "PC1", target: "192.168.1.20", wait_ms: 5000 }); assert.ok(!r.isError); assert.match(json(r).output, /OUT\(ping 192.168.1.20\)/); assert.equal(json(r).finished, true);
r = await call("pt_run_show", { device: "SW1", command: "show mac address-table", wait_ms: 5000 }); assert.match(json(r).output, /show mac address-table/);
r = await call("pt_configure_ios", { device: "SW1", commands: ["hostname S1", "", "vlan 10"] }); assert.equal(json(r).commandsSent, 2);
console.log("✔ execute_js / pt_ping / pt_run_show / configure_ios (con eventos simulados)");

// 6) captura (en Linux debe fallar con mensaje claro)
r = await call("pt_capture"); assert.ok(r.isError && /Windows/.test(r.text)); console.log("✔ pt_capture → mensaje claro fuera de Windows");

// 7) serialización: 5 comandos concurrentes
const rs = await Promise.all([1,2,3,4,5].map(i => call("pt_execute_js", { code: `return ${i}` })));
assert.deepEqual(rs.map(x => json(x)), [1,2,3,4,5]); console.log("✔ 5 llamadas concurrentes → cola serializada, resultados correctos");

// 8) seguridad: Host inválido rechazado
const bad = await fetch(`${BASE}/health`, { headers: { Host: "evil.com" } }).catch(() => null);
console.log("✔ health:", JSON.stringify(json(await call("pt_status"))));

console.log("\nTODO OK");
} catch (e) { console.error("FALLO:", e); process.exitCode = 1; } finally { polling = false; await client.close().catch(() => {}); process.exit(process.exitCode ?? 0); }
