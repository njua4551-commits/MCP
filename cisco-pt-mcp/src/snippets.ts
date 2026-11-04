// Código JS que se ejecuta DENTRO del script host de Packet Tracer (objeto global `ipc`).
// Cada snippet es el CUERPO de una función: usa `return` para devolver datos y `throw` para fallar.
// Los argumentos se inyectan con JSON.stringify (quoting seguro).

const j = (v: unknown) => JSON.stringify(v === undefined ? null : v);

// Constantes verificadas en PTBuilder (devices.js / links.js). Amplía la tabla si necesitas más modelos.
const TABLES = `
var DEVICE_TYPES = {"Router-PT":0,"1841":0,"1941":0,"2811":0,"2901":0,"2911":0,"ISR4321":0,"ISR4331":0,
"Switch-PT":1,"2950-24":1,"2950T-24":1,"2960-24TT":1,"Cloud-PT":2,"Bridge-PT":3,"Hub-PT":4,"Repeater-PT":5,
"AccessPoint-PT":7,"AccessPoint-PT-A":7,"AccessPoint-PT-AC":7,"AccessPoint-PT-N":7,"PC-PT":8,"Server-PT":9,
"Printer-PT":10,"Linksys-WRT300N":11,"DSL-Modem-PT":13,"Cable-Modem-PT":14,"3560-24PS":16,"3650-24PS":16,
"Laptop-PT":18,"TabletPC-PT":19,"SMARTPHONE-PT":20};
var LINK_TYPES = {"straight":8100,"cross":8101,"roll":8102,"fiber":8103,"phone":8104,"cable":8105,
"serial":8106,"auto":8107,"console":8108,"wireless":8109,"coaxial":8110};
`;

export const addDevice = (name: string, model: string, x: number, y: number) => `${TABLES}
var t = DEVICE_TYPES[${j(model)}];
if (t === undefined) throw new Error("Modelo desconocido: " + ${j(model)} + ". Disponibles: " + Object.keys(DEVICE_TYPES).join(", "));
var auto = ipc.appWindow().getActiveWorkspace().getLogicalWorkspace().addDevice(t, ${j(model)}, ${j(x)}, ${j(y)});
if (!auto) throw new Error("addDevice devolvió vacío");
var d = ipc.network().getDevice(auto);
d.setName(${j(name)});
if (t <= 1 || t == 16) d.skipBoot();
return { name: ${j(name)}, model: ${j(model)} };`;

export const addLink = (d1: string, i1: string, d2: string, i2: string, type: string) => `${TABLES}
var lt = LINK_TYPES[${j(type)}];
if (lt === undefined) throw new Error("Tipo de cable desconocido: " + ${j(type)} + ". Disponibles: " + Object.keys(LINK_TYPES).join(", "));
var ok = ipc.appWindow().getActiveWorkspace().getLogicalWorkspace().createLink(${j(d1)}, ${j(i1)}, ${j(d2)}, ${j(i2)}, lt);
if (ok !== true) throw new Error("createLink falló: revisa nombres de dispositivo/interfaz y tipo de cable");
return { linked: [${j(d1)} + ":" + ${j(i1)}, ${j(d2)} + ":" + ${j(i2)}] };`;

export const configurePc = (
  name: string, ip?: string, mask?: string, gw?: string, dns?: string, dhcp?: boolean,
) => `
var d = ipc.network().getDevice(${j(name)});
if (!d) throw new Error("Dispositivo no encontrado: " + ${j(name)});
var p = d.getPort("FastEthernet0");
if (!p) throw new Error("FastEthernet0 no existe en " + ${j(name)});
if (${j(dhcp)} !== null) d.setDhcpFlag(${j(dhcp)});
if (${j(ip)} && ${j(mask)}) p.setIpSubnetMask(${j(ip)}, ${j(mask)});
if (${j(gw)}) p.setDefaultGateway(${j(gw)});
if (${j(dns)}) p.setDnsServerIp(${j(dns)});
return { configured: ${j(name)} };`;

export const configureIos = (device: string, commands: string[]) => `
var d = ipc.network().getDevice(${j(device)});
if (!d) throw new Error("Dispositivo no encontrado: " + ${j(device)});
d.skipBoot();
var cmds = ${j(commands)}, sent = 0;
d.enterCommand("!", "global");
for (var i = 0; i < cmds.length; i++) {
  if (String(cmds[i]).replace(/\\s/g, "")) { d.enterCommand(cmds[i], ""); sent++; }
}
d.enterCommand("write memory", "enable");
return { device: ${j(device)}, commandsSent: sent };`;

export const getNetwork = () => `
var net = ipc.network();
function ownerOf(port) {
  try {
    if (typeof port.getOwnerDevice === "function") {
      var o = port.getOwnerDevice();
      return (typeof o === "string") ? o : (o && o.getName ? o.getName() : null);
    }
  } catch (e) {}
  return null;
}
var devices = [], connections = [], portOwner = {};
for (var i = 0; i < net.getDeviceCount(); i++) {
  var d = net.getDeviceAt(i), ports = [];
  for (var k = 0; k < d.getPortCount(); k++) {
    var p = d.getPortAt(k); if (!p) continue;
    portOwner[p.getName()] = d.getName();
    ports.push(p.getName());
  }
  devices.push({ name: d.getName(), model: d.getModel(), type: d.getType(), ports: ports });
}
for (var l = 0; l < net.getLinkCount(); l++) {
  var lk = net.getLinkAt(l), a = lk.getPort1(), b = lk.getPort2();
  connections.push({
    from: ownerOf(a) || portOwner[a.getName()], fromPort: a.getName(),
    to: ownerOf(b) || portOwner[b.getName()], toPort: b.getName(),
    cable: lk.getConnectionType()
  });
}
return { deviceCount: devices.length, devices: devices, connectionCount: connections.length, connections: connections };`;

// --- EXPERIMENTAL: captura de salida de CLI (eventos asíncronos de PT) ---------------------------
// Los nombres de evento/argumentos (outputWritten, commandEnded, args.newOutput) hay que confirmarlos
// en tu versión de PT con la tool pt_docs -> "descubrimiento de API".
export const cliStart = (device: string, command: string) => `
__ptmcp = (typeof __ptmcp === "undefined") ? { jobs: {}, seq: 0 } : __ptmcp;
var d = ipc.network().getDevice(${j(device)});
if (!d) throw new Error("Dispositivo no encontrado: " + ${j(device)});
var cl = d.getCommandLine();
if (!cl) throw new Error("El dispositivo no tiene CommandLine");
var id = "job" + (++__ptmcp.seq);
var job = { out: "", done: false };
__ptmcp.jobs[id] = job;
cl.registerEvent("outputWritten", null, function (src, args) {
  var t = args && (args.newOutput || args.output || args.text);
  if (t) job.out += t;
});
cl.registerEvent("commandEnded", null, function () { job.done = true; });
cl.enterCommand(${j(command)});
return { id: id };`;

export const cliRead = (id: string) => `
var job = (typeof __ptmcp !== "undefined") && __ptmcp.jobs[${j(id)}];
if (!job) throw new Error("job desconocido: " + ${j(id)});
return { out: job.out, done: job.done };`;

export const DOCS = `# Cheat-sheet de la API de scripting de Packet Tracer (script host)
El código de pt_execute_js es el CUERPO de una función: usa "return" para devolver datos y "throw" para error.
Debe devolver algo serializable a JSON. Motor JS antiguo: prefiere var/function (ES5).

Objetos raíz: ipc.network(), ipc.appWindow(), ipc.commandLog(), ipc.simulation()
- ipc.network(): getDeviceCount(), getDeviceAt(i), getDevice(nombre), getLinkCount(), getLinkAt(i)
- Workspace: ipc.appWindow().getActiveWorkspace().getLogicalWorkspace()
    .addDevice(tipoNumerico, modelo, x, y) -> nombre autogenerado ; .createLink(d1, if1, d2, if2, tipoCable)
- Device: getName(), setName(n), getModel(), getType(), getPower(), setPower(b), skipBoot(), getPortCount(), getPortAt(i),
    getPort(nombre), addModule(slot, tipo, modelo), enterCommand(cmd, modo) // modo: "" | "enable" | "global"
- Port: getName(), setIpSubnetMask(ip, mascara), setDefaultGateway(ip), setDnsServerIp(ip)
- PC: device.setDhcpFlag(bool)
- Link: getPort1(), getPort2(), getConnectionType()
- ipc.commandLog(): getEntryCount(), getEntryAt(i) -> getDeviceName(), getCommand(), getPrompt()
Tipos de dispositivo: router 0, switch 1, cloud 2, hub 4, AP 7, PC 8, server 9, printer 10, wireless router 11, L3 switch 16, laptop 18.
Cables: straight 8100, cross 8101, roll 8102, fiber 8103, serial 8106, console 8108, wireless 8109.

## Descubrimiento de API (si un método no existe)
Enumera los miembros reales de cualquier objeto:
  var o = ipc.network().getDevice("R1"); var m = []; for (var k in o) m.push(k); return m;
Prueba el nombre en un try/catch y devuelve el error. No adivines: enumera primero.

## Salida de CLI (EXPERIMENTAL)
pt_run_show y pt_ping usan device.getCommandLine() + eventos outputWritten/commandEnded. Si devuelven salida vacía,
enumera con el snippet de arriba sobre getCommandLine() y ajusta los nombres de evento.
Para "show" largos en IOS, ejecuta antes "terminal length 0" con pt_configure_ios.
`;
