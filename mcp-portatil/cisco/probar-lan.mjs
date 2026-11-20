// Laboratorio de la primera escena del vídeo. Ejecutar con un .pkt vacío conectado al bridge.
import { fileURLToPath } from 'node:url';
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { StdioClientTransport } from '@modelcontextprotocol/sdk/client/stdio.js';

const client = new Client({ name: 'prueba-lan-video', version: '1' });
async function call(name, args = {}) {
  const r = await client.callTool({ name, arguments: args });
  const text = r.content[0]?.text;
  if (r.isError) throw new Error(`${name}: ${text}`);
  return JSON.parse(text);
}

try {
  await client.connect(new StdioClientTransport({
    command: process.execPath, args: [fileURLToPath(new URL('../mcp.mjs', import.meta.url)), 'serve', 'cisco-pt-mcp'],
    env: Object.fromEntries(Object.entries(process.env).filter(([key]) => key.startsWith('PT_MCP_')))
  }));
  if (!(await call('pt_status')).packetTracerConnected) throw new Error('Abre el .pkt con MCP Bridge y pulsa Conectar.');
  // PT añade dispositivos auxiliares (p. ej. "Power Distribution Device", type 45) que no cuentan.
  const aux = d => d.type === 45 || /^Power Distribution/i.test(d.model);
  const userDevices = t => t.devices.filter(d => !aux(d));
  const names = ['PC1', 'PC2', 'PC3', 'PC4', 'PC5', 'PC6', 'PRN1', 'PRN2'];
  const before = userDevices(await call('pt_get_network'));
  if (before.length === 0) {
    await call('pt_add_device', { name: 'SW1', model: '2960-24TT', x: 400, y: 230 });
    for (const [i, name] of names.entries()) {
      await call('pt_add_device', { name, model: i < 6 ? 'PC-PT' : 'Printer-PT', x: 130 + (i % 4) * 180, y: i < 4 ? 80 : 380 });
      await call('pt_add_link', { device1: name, interface1: 'FastEthernet0', device2: 'SW1', interface2: `FastEthernet0/${i+1}`, cable: 'straight' });
      await call('pt_configure_pc', { device: name, ip: `192.168.1.${10+i}`, mask: '255.255.255.0' });
    }
  } else {
    console.log(`El lienzo ya tiene ${before.length} dispositivos: se verifica sin recrear.`);
  }
  const topo = await call('pt_get_network');
  const devices = userDevices(topo);
  if (devices.length !== 9 || topo.connectionCount !== 8 || !names.every(n =>
    topo.connections.some(c => (c.from === n && c.to === 'SW1') || (c.to === n && c.from === 'SW1'))))
    throw new Error('El inventario de Packet Tracer no coincide con la LAN esperada.');
  console.log('Topología verificada en el lienzo: 6 PC, 2 impresoras, 1 switch y 8 cables.');
  for (let i=0; i<3; i++) {
    const { output } = await call('pt_ping', { source: 'PC1', target: '192.168.1.11', wait_ms: 15000 });
    if (/192\.168\.1\.11[^\r\n]*\bttl\s*=/i.test(output)) { console.log('Ping PC1 → PC2 confirmado.'); break; }
    if (i === 2) throw new Error('La topología existe, pero no se recibió una respuesta de ping verificable. Comprueba PC1 → PC2 en Packet Tracer.');
    await new Promise(r => setTimeout(r, 3000));
  }
} catch (e) { console.error(e.message); process.exitCode = 1; }
finally { await client.close(); }
