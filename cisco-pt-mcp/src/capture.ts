import { execFile } from "node:child_process";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

export type Capture = { ok: true; data: string } | { ok: false; error: string };

/** Captura la ventana de Packet Tracer (sólo Windows) y devuelve el PNG en base64. */
export async function captureWindow(processName = "PacketTracer"): Promise<Capture> {
  if (process.platform !== "win32")
    return { ok: false, error: "pt_capture sólo está implementado para Windows (usa PowerShell + user32)." };
  const dir = await mkdtemp(path.join(tmpdir(), "ptcap-"));
  const out = path.join(dir, "pt.png");
  const script = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../scripts/capture.ps1");
  try {
    await new Promise<void>((resolve, reject) =>
      execFile(
        "powershell.exe",
        ["-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script, "-OutPath", out, "-ProcessName", processName],
        { timeout: 20_000, windowsHide: true },
        (err, _so, se) => (err ? reject(new Error(se || err.message)) : resolve()),
      ),
    );
    return { ok: true, data: (await readFile(out)).toString("base64") };
  } catch (e) {
    return { ok: false, error: `Captura fallida: ${(e as Error).message}` };
  } finally {
    rm(dir, { recursive: true, force: true }).catch(() => {});
  }
}
