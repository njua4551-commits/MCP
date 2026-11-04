import http from "node:http";
import { randomUUID } from "node:crypto";

export type BridgeReply = { ok: boolean; result?: unknown; error?: string };

type Job = {
  id: string;
  code: string;
  resolve: (r: BridgeReply) => void;
  timer: NodeJS.Timeout;
};

// stdout está reservado para el protocolo MCP: TODO log va a stderr.
const log = (...a: unknown[]) => console.error("[pt-bridge]", ...a);

export class PtBridge {
  private queue: Job[] = [];
  private inFlight = new Map<string, Job>();
  private lastPoll = 0;
  listening = false;
  /** Si otra instancia ya escucha en el puerto, esta actúa como cliente suyo. */
  private proxyUrl: string | null = null;
  private remote: Record<string, unknown> | null = null;

  constructor(
    private port = Number(process.env.PT_MCP_PORT ?? 37101),
    private token = process.env.PT_MCP_TOKEN ?? "",
    private timeoutMs = Number(process.env.PT_MCP_TIMEOUT_MS ?? 60_000),
  ) {}

  /** PT está "conectado" si hizo polling en los últimos 3 s. */
  get connected() {
    return Date.now() - this.lastPoll < 3000;
  }

  status() {
    if (this.proxyUrl) {
      const r = this.remote ?? {};
      return {
        listening: true,
        proxied: true,
        port: this.port,
        packetTracerConnected: Boolean(r.packetTracerConnected),
        queued: Number(r.queued ?? 0),
        inFlight: Number(r.inFlight ?? 0),
      };
    }
    return {
      listening: this.listening,
      proxied: false,
      port: this.port,
      packetTracerConnected: this.connected,
      queued: this.queue.length,
      inFlight: this.inFlight.size,
    };
  }

  start(): Promise<void> {
    return new Promise((resolve) => {
      const srv = http.createServer((req, res) => this.handle(req, res));
      srv.on("error", async (e: NodeJS.ErrnoException) => {
        log(`no puedo escuchar en ${this.port}: ${e.code}`);
        if (e.code === "EADDRINUSE") {
          // Otra instancia del MCP ya escucha: reenviamos los trabajos a ella.
          const health = await this.fetchRemote("/health");
          if (health) {
            this.proxyUrl = `http://127.0.0.1:${this.port}`;
            this.remote = health as Record<string, unknown>;
            log(`modo proxy hacia ${this.proxyUrl}`);
          } else {
            log("el puerto está ocupado pero no responde: revisa procesos node huérfanos");
          }
        }
        resolve(); // el MCP sigue vivo; las tools devolverán un error claro
      });
      srv.listen(this.port, "127.0.0.1", () => {
        this.listening = true;
        log(`escuchando en http://127.0.0.1:${this.port}`);
        resolve();
      });
    });
  }

  /** Petición HTTP interna contra el bridge que sí escucha (modo proxy). */
  private fetchRemote(path: string, body?: unknown): Promise<unknown | null> {
    return new Promise((resolve) => {
      const payload = body === undefined ? undefined : JSON.stringify(body);
      const req = http.request(
        {
          host: "127.0.0.1",
          port: this.port,
          path,
          method: payload === undefined ? "GET" : "POST",
          headers: {
            ...(payload ? { "content-type": "application/json", "content-length": Buffer.byteLength(payload) } : {}),
            ...(this.token ? { "x-pt-token": this.token } : {}),
          },
          timeout: this.timeoutMs,
        },
        (res) => {
          const chunks: Buffer[] = [];
          res.on("data", (c: Buffer) => chunks.push(c));
          res.on("end", () => {
            const raw = Buffer.concat(chunks).toString("utf8");
            try {
              resolve(raw ? JSON.parse(raw) : null);
            } catch {
              resolve(null);
            }
          });
        },
      );
      req.on("error", () => resolve(null));
      req.on("timeout", () => {
        req.destroy();
        resolve(null);
      });
      if (payload) req.write(payload);
      req.end();
    });
  }

  /** Encola código JS para el script host de Packet Tracer y espera el resultado. */
  run(code: string, timeoutMs = this.timeoutMs): Promise<BridgeReply> {
    if (this.proxyUrl) {
      return this.fetchRemote("/__run", { code, timeoutMs }).then((r) => {
        if (!r) return { ok: false, error: "El bridge que escucha en el puerto no respondió." };
        return r as BridgeReply;
      });
    }
    if (!this.listening)
      return Promise.resolve({
        ok: false,
        error: `Bridge HTTP no disponible: el puerto ${this.port} está ocupado (¿otra instancia de OpenCode abierta?).`,
      });
    if (!this.connected)
      return Promise.resolve({
        ok: false,
        error:
          "Packet Tracer no está conectado al bridge. Abre Packet Tracer, Extensions > MCP Bridge y pulsa Conectar.",
      });
    return new Promise((resolve) => {
      const id = randomUUID();
      const timer = setTimeout(() => {
        this.queue = this.queue.filter((j) => j.id !== id);
        this.inFlight.delete(id);
        resolve({ ok: false, error: `Timeout de ${timeoutMs} ms esperando a Packet Tracer` });
      }, timeoutMs);
      this.queue.push({ id, code, resolve, timer });
    });
  }

  private handle(req: http.IncomingMessage, res: http.ServerResponse) {
    const send = (status: number, body?: unknown) => {
      res.writeHead(status, {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Headers": "content-type,x-pt-token",
        "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
        "Content-Type": "application/json",
      });
      res.end(body === undefined ? undefined : JSON.stringify(body));
    };

    // Anti DNS-rebinding: sólo aceptamos Host local.
    const host = (req.headers.host ?? "").split(":")[0];
    if (host !== "127.0.0.1" && host !== "localhost") return send(403, { error: "host no permitido" });
    if (req.method === "OPTIONS") return send(204);

    const url = new URL(req.url ?? "/", "http://127.0.0.1");
    if (this.token) {
      const got = url.searchParams.get("token") ?? req.headers["x-pt-token"];
      if (got !== this.token) return send(401, { error: "token inválido" });
    }

    if (req.method === "GET" && url.pathname === "/health") return send(200, this.status());

    // Petición interna de otra instancia del MCP (modo proxy).
    if (req.method === "POST" && url.pathname === "/__run") {
      let size = 0;
      const chunks: Buffer[] = [];
      req.on("data", (c: Buffer) => {
        size += c.length;
        if (size > 2_000_000) req.destroy();
        else chunks.push(c);
      });
      req.on("end", () => {
        let body: { code?: string; timeoutMs?: number } = {};
        try {
          body = JSON.parse(Buffer.concat(chunks).toString("utf8"));
        } catch {
          return send(400, { ok: false, error: "JSON inválido" });
        }
        if (typeof body.code !== "string") return send(400, { ok: false, error: "falta code" });
        void this.run(body.code, body.timeoutMs ?? this.timeoutMs).then((r) => send(200, r));
      });
      return;
    }

    if (req.method === "GET" && url.pathname === "/next") {
      this.lastPoll = Date.now();
      // Un solo comando en vuelo a la vez: PT ejecuta todo en su hilo de UI.
      if (this.inFlight.size === 0 && this.queue.length > 0) {
        const job = this.queue.shift()!;
        this.inFlight.set(job.id, job);
        return send(200, { id: job.id, code: job.code });
      }
      return send(204);
    }

    if (req.method === "POST" && url.pathname === "/result") {
      let size = 0;
      const chunks: Buffer[] = [];
      req.on("data", (c: Buffer) => {
        size += c.length;
        if (size > 8_000_000) req.destroy();
        else chunks.push(c);
      });
      req.on("end", () => {
        try {
          const msg = JSON.parse(Buffer.concat(chunks).toString("utf8")) as {
            id: string; ok: boolean; result?: unknown; error?: string;
          };
          const job = this.inFlight.get(msg.id);
          if (!job) return send(404, { error: "id desconocido (¿timeout?)" });
          clearTimeout(job.timer);
          this.inFlight.delete(msg.id);
          job.resolve({ ok: msg.ok, result: msg.result, error: msg.error });
          send(200, { ok: true });
        } catch {
          send(400, { error: "JSON inválido" });
        }
      });
      return;
    }
    send(404, { error: "no encontrado" });
  }
}
