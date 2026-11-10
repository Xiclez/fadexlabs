// Subida por partes a /api/tools/uploads. Cloudflare Tunnel rechaza cuerpos de más de 100 MB,
// así que el archivo viaja en partes (8 MB) y cada parte se reintenta sola si falla la red.
// Es reanudable: iniciar otra vez con el mismo archivo devuelve por qué parte iba.

import { api, ApiError, type Job, type ToolName, type UploadState } from "@/lib/api";

const RETRIES = 6;

export type UploadProgress = { sent: number; total: number; part: number; parts: number; retrying: boolean };

const sleep = (ms: number, signal?: AbortSignal) =>
  new Promise<void>((resolve, reject) => {
    const id = setTimeout(resolve, ms);
    signal?.addEventListener("abort", () => {
      clearTimeout(id);
      reject(new DOMException("Subida cancelada", "AbortError"));
    }, { once: true });
  });

/** Errores que no se arreglan reintentando la misma parte. */
const isFatal = (e: unknown) => e instanceof ApiError && e.status >= 400 && e.status < 500 && e.status !== 408 && e.status !== 429;

export async function uploadFile(opts: {
  tool: ToolName;
  file: File;
  extra?: Record<string, unknown>;
  signal?: AbortSignal;
  onProgress?: (p: UploadProgress) => void;
}): Promise<Job> {
  const { tool, file, extra, signal, onProgress } = opts;
  let state = await api<UploadState>("/tools/uploads", {
    method: "POST", json: { tool, filename: file.name, size: file.size, ...extra }, signal,
  });
  const base = `/tools/uploads/${state.upload_id}`;
  const report = (part: number, retrying = false) => onProgress?.({
    sent: Math.min(part * state.chunk_size, file.size), total: file.size, part, parts: state.total_parts, retrying,
  });

  let part = state.received_parts; // > 0 cuando se reanuda una subida a medias
  report(part);
  while (part < state.total_parts) {
    const chunk = file.slice(part * state.chunk_size, (part + 1) * state.chunk_size);
    for (let attempt = 0; ; attempt++) {
      try {
        state = await api<UploadState>(`${base}/chunks/${part}`, {
          method: "PUT", body: chunk, headers: { "content-type": "application/octet-stream" }, signal,
        });
        break;
      } catch (e) {
        if (signal?.aborted) throw e;
        if (e instanceof ApiError && e.status === 409) {
          // el servidor va por otra parte (p. ej. llegó la parte pero se perdió la respuesta): resincroniza
          state = await api<UploadState>(base, { signal });
          break;
        }
        if (isFatal(e) || attempt >= RETRIES) throw e;
        report(part, true);
        await sleep(Math.min(1000 * 2 ** attempt, 30000), signal);
      }
    }
    part = state.received_parts;
    report(part);
  }
  return api<Job>(`${base}/complete`, { method: "POST", signal });
}
