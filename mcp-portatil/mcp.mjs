#!/usr/bin/env node
import { existsSync, readFileSync } from 'node:fs';
import { spawn } from 'node:child_process';
import { createRequire } from 'node:module';
import { isIP } from 'node:net';
import { homedir, tmpdir } from 'node:os';
import { dirname, isAbsolute, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const script = fileURLToPath(import.meta.url);
const require = createRequire(import.meta.url);
const ids = ['playwright', 'cisco-pt-mcp', 'windows-control-mcp', 'vmware'];
const env = process.env;
const print = value => console.log(JSON.stringify(value, null, 2));
const help = `mcp-ia config <json|vscode|codex|opencode> [servidor ...]
mcp-ia serve <servidor>
mcp-ia list <servidor>
mcp-ia call <servidor> <herramienta> [objeto JSON o - para stdin]
Servidores: ${ids.join(', ')}`;

function server(id) {
  if (id === 'guest-vmware-mcp') return 'windows-control-mcp';
  if (!ids.includes(id)) throw new Error(`Servidor desconocido: ${id ?? '(vacío)'}. ${ids.join(', ')}`);
  return id;
}

function config(format, selected) {
  const names = selected.length ? [...new Set(selected.map(server))] : ids;
  const entries = names.map(id => [id, { command: process.execPath, args: [script, 'serve', id] }]);
  const servers = Object.fromEntries(entries);
  if (format === 'json') return print({ mcpServers: servers });
  if (format === 'vscode') return print({
    servers: Object.fromEntries(entries.map(([id, e]) => [id, { type: 'stdio', ...e }]))
  });
  if (format === 'codex') {
    return console.log(entries.map(([id, e]) => `[mcp_servers.${id}]\ncommand = ${JSON.stringify(e.command)}\nargs = ${JSON.stringify(e.args)}`).join('\n\n'));
  }
  if (format === 'opencode') return print({
    $schema: 'https://opencode.ai/config.json',
    mcp: { servers: Object.fromEntries(entries.map(([id, e]) => [id, { type: 'local', command: [e.command, ...e.args] }])) }
  });
  throw new Error(help);
}

function guestSettings() {
  // Mantener el destino y su credencial emparejados, también al cambiar la URL.
  const home = join(homedir(), '.mcp-portatil');
  const legacy = join(homedir(), '.local', 'share', 'mcp', 'guest-vmware-mcp');
  const folder = env.MCP_GUEST_DIR || (existsSync(home) || process.platform !== 'linux' ? home : legacy);
  if (!isAbsolute(folder)) throw new Error('MCP_GUEST_DIR debe ser una ruta absoluta.');
  let url;
  if (env.MCP_GUEST_URL) {
    url = new URL(env.MCP_GUEST_URL);
    if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password)
      throw new Error('MCP_GUEST_URL debe ser una URL HTTP(S) sin credenciales.');
    if (!env.MCP_GUEST_TOKEN && !env.MCP_GUEST_TOKEN_FILE)
      throw new Error('Indica MCP_GUEST_TOKEN_FILE o MCP_GUEST_TOKEN para esa URL.');
  } else {
    const ipFile = join(folder, 'last_ip.txt');
    if (!existsSync(ipFile)) throw new Error('Configura MCP_GUEST_URL y MCP_GUEST_TOKEN_FILE o prepara ~/.mcp-portatil/last_ip.txt y token.txt.');
    const ip = readFileSync(ipFile, 'utf8').trim();
    if (!isIP(ip)) throw new Error('last_ip.txt debe contener solo la IP del invitado.');
    url = new URL(`http://${isIP(ip) === 6 ? `[${ip}]` : ip}:8765/mcp`);
  }
  const file = env.MCP_GUEST_TOKEN_FILE || join(folder, 'token.txt');
  if (!isAbsolute(file)) throw new Error('MCP_GUEST_TOKEN_FILE debe ser una ruta absoluta.');
  const token = (env.MCP_GUEST_TOKEN || readFileSync(file, 'utf8')).trim();
  if (!token || /[\r\n]/.test(token)) throw new Error('Token del invitado vacío o inválido.');
  return { url, token };
}

// El SDK codifica stdio y Streamable HTTP; el intermediario conserva IDs, capacidades y contenido.
async function guest() {
  const { url, token } = guestSettings();
  const { StdioServerTransport } = await import('@modelcontextprotocol/sdk/server/stdio.js');
  const { StreamableHTTPClientTransport } = await import('@modelcontextprotocol/sdk/client/streamableHttp.js');
  const local = new StdioServerTransport();
  const http = new StreamableHTTPClientTransport(url, {
    requestInit: { headers: { Authorization: `Bearer ${token}` }, redirect: 'error' }
  });
  let initId, closing = false;
  const close = async () => {
    if (closing) return;
    closing = true;
    const deadline = setTimeout(() => process.exit(), 1800).unref();
    try { await http.terminateSession(); } catch { /* La VM puede estar apagada. */ }
    await http.close();
    await local.close();
    clearTimeout(deadline);
  };
  local.onmessage = m => {
    if (m.method === 'initialize') initId = m.id;
    http.send(m).catch(e => {
      if ('method' in m && 'id' in m && !closing) {
        const message = `VMware: comprueba URL, red y token${e.code > 0 ? ` (HTTP ${e.code})` : ''}.`;
        local.send({ jsonrpc: '2.0', id: m.id, error: { code: -32000, message } }).catch(close);
      }
    });
  };
  http.onmessage = m => {
    if (m.id === initId && m.result?.protocolVersion) http.setProtocolVersion(m.result.protocolVersion);
    local.send(m).catch(close);
  };
  local.onerror = () => { console.error('Entrada stdio inválida.'); void close(); };
  await http.start();
  await local.start();
  process.stdin.once('end', close);
  process.once('SIGINT', close);
  process.once('SIGTERM', close);
}

async function serve(id) {
  if (id === 'windows-control-mcp') return guest();
  if (id === 'vmware') {
    const python = env.MCP_PYTHON || (process.platform === 'win32' ? 'python' : 'python3');
    const child = spawn(python, [join(dirname(script), 'vmware', 'server.py')], {
      stdio: 'inherit', env: { ...env, PYTHONUTF8: '1', PYTHONIOENCODING: 'utf-8' }
    });
    process.once('SIGTERM', () => child.kill());
    process.once('SIGINT', () => child.kill());
    child.once('error', () => { console.error('Falta Python 3: configura MCP_PYTHON.'); process.exitCode = 1; });
    child.once('exit', (code, signal) => { process.exitCode = code ?? (signal ? 1 : 0); });
    return;
  }
  if (id === 'cisco-pt-mcp') {
    env.PT_MCP_TIMEOUT_MS ??= '62000';
    process.stdin.once('end', () => process.exit(0));
    return import('./cisco/dist/server.js');
  }
  const cli = join(dirname(require.resolve('@playwright/mcp/package.json')), 'cli.js');
  const browser = env.PLAYWRIGHT_MCP_EXECUTABLE_PATH || require('playwright').chromium.executablePath();
  if (!existsSync(browser)) throw new Error('Falta Chromium. En la carpeta del kit ejecuta: npx playwright install chromium');
  const output = env.PLAYWRIGHT_MCP_OUTPUT_DIR || join(tmpdir(), 'mcp-portatil', 'playwright');
  process.argv = [process.execPath, cli, '--headless', '--isolated', '--executable-path', browser, '--output-dir', output];
  require(cli);
}

async function clientCommand(op, id, tool, raw) {
  let args;
  if (op === 'call') {
    if (!tool) throw new Error(help);
    args = JSON.parse(raw === '-' ? readFileSync(0, 'utf8') : (raw ?? '{}'));
    if (args === null || typeof args !== 'object' || Array.isArray(args)) throw new Error('Los argumentos deben ser un objeto JSON.');
  }
  const { Client } = await import('@modelcontextprotocol/sdk/client/index.js');
  const { StdioClientTransport } = await import('@modelcontextprotocol/sdk/client/stdio.js');
  const pass = Object.fromEntries(Object.entries(env).filter(([k]) =>
    /^(XDG_.*|LOCALAPPDATA|TMP(DIR)?|TEMP|HTTPS?_PROXY|NO_PROXY|NODE_EXTRA_CA_CERTS)$/i.test(k)
    || (id === 'windows-control-mcp' && k.startsWith('MCP_GUEST_'))
    || (id === 'vmware' && /^(MCP_PYTHON|VMWARE_.*|VMRUN)$/.test(k))
    || (id === 'playwright' && k.startsWith('PLAYWRIGHT_'))
    || (id === 'cisco-pt-mcp' && k.startsWith('PT_MCP_'))));
  const client = new Client({ name: 'mcp-ia', version: '1.0.0' });
  try {
    await client.connect(new StdioClientTransport({ command: process.execPath, args: [script, 'serve', id], env: pass }));
    if (op === 'list') {
      const tools = [];
      let cursor;
      do {
        const page = await client.listTools({ cursor });
        tools.push(...page.tools);
        cursor = page.nextCursor;
      } while (cursor);
      print(tools);
    } else {
      const result = await client.callTool({ name: tool, arguments: args }, undefined, { timeout: 180000 });
      print(result);
      if (result.isError) process.exitCode = 1;
    }
  } finally { await client.close(); }
}

try {
  const [op, id, ...args] = process.argv.slice(2);
  if (!op || op === '--help' || op === '-h') console.log(help);
  else if (op === 'config') config(id, args);
  else if (op === 'serve') await serve(server(id));
  else if (op === 'list' || op === 'call') await clientCommand(op, server(id), ...args);
  else throw new Error(help);
} catch (error) {
  console.error(error.message);
  process.exitCode = 1;
}
