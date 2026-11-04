import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";

async function makeClient(label) {
  const transport = new StdioClientTransport({
    command: "node",
    args: ["dist/server.js"],
    cwd: process.cwd(),
    stderr: "pipe",
  });
  const client = new Client({ name: "probe-" + label, version: "1.0.0" });
  await client.connect(transport);
  return client;
}

const a = await makeClient("A");
await new Promise((r) => setTimeout(r, 800));
const b = await makeClient("B");
await new Promise((r) => setTimeout(r, 800));

for (const [label, c] of [["A", a], ["B", b]]) {
  const st = await c.callTool({ name: "pt_status", arguments: {} });
  console.log(label, "STATUS:", st.content?.[0]?.text?.replace(/\s+/g, " "));
  const run = await c.callTool({ name: "pt_get_network", arguments: {} });
  console.log(label, "GET_NETWORK:", String(run.content?.[0]?.text).replace(/\s+/g, " ").slice(0, 160));
}

await a.close();
await b.close();
process.exit(0);
