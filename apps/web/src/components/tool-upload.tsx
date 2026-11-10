"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { type FormEvent, type ReactNode, useEffect, useId, useRef, useState } from "react";

import { FormMessage } from "@/components/auth-ui";
import { Button, CutCard } from "@/components/ui";
import { api, ApiError, type ToolName, type ToolsInfo } from "@/lib/api";
import { formatBytes } from "@/lib/format";
import { uploadFile, type UploadProgress } from "@/lib/upload";

/** Formulario de subida de una herramienta: elige archivo, sube por partes con barra de progreso
 *  y, al terminar, lleva al seguimiento del trabajo. `children` son los campos propios de la herramienta. */
export function ToolUpload({ tool, fileLabel, fileHint, submitLabel, extra, children }: {
  tool: ToolName; fileLabel: string; fileHint: string; submitLabel: string;
  extra?: (form: FormData) => Record<string, unknown>; children?: ReactNode;
}) {
  const router = useRouter();
  const inputId = useId();
  const [info, setInfo] = useState<ToolsInfo | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [progress, setProgress] = useState<UploadProgress | null>(null);
  const [error, setError] = useState("");
  const abort = useRef<AbortController | null>(null);

  useEffect(() => {
    api<ToolsInfo>("/tools").then(setInfo).catch(() => setInfo(null));
    return () => abort.current?.abort(); // salir de la página detiene la subida (se puede reanudar)
  }, []);

  const limits = info?.[tool];
  const uploading = progress !== null;
  const pct = progress ? Math.floor((progress.sent / progress.total) * 100) : 0;

  function check(f: File): string {
    if (!limits) return "";
    const ext = f.name.slice(f.name.lastIndexOf(".")).toLowerCase();
    if (!limits.extensions.includes(ext)) return `Formato no admitido. Usa: ${limits.extensions.join(", ")}`;
    if (f.size > limits.max_bytes) return `El archivo pesa ${formatBytes(f.size)}; el máximo es ${formatBytes(limits.max_bytes)}.`;
    return "";
  }

  async function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!file) return;
    const problem = check(file);
    if (problem) return setError(problem);
    setError("");
    abort.current = new AbortController();
    setProgress({ sent: 0, total: file.size, part: 0, parts: 1, retrying: false });
    try {
      const job = await uploadFile({
        tool, file, extra: extra?.(new FormData(e.currentTarget)), signal: abort.current.signal, onProgress: setProgress,
      });
      router.push(`/herramientas/trabajos/${job.id}`);
    } catch (err) {
      setProgress(null);
      if (abort.current?.signal.aborted) {
        setError("Subida detenida. Elige el mismo archivo y vuelve a subir para continuar donde iba.");
      } else if (err instanceof ApiError) {
        setError(err.message);
      } else {
        setError("Se perdió la conexión. Elige el mismo archivo y vuelve a subir: continúa donde se quedó.");
      }
    }
  }

  return (
    <CutCard innerClassName="p-8">
      <form onSubmit={onSubmit} className="space-y-6" aria-busy={uploading}>
        {error && <FormMessage kind="error">{error}</FormMessage>}

        <div>
          <label htmlFor={inputId} className="fx-label text-muted">{fileLabel}</label>
          <input id={inputId} type="file" required disabled={uploading}
            accept={limits?.extensions.join(",")} aria-describedby={`${inputId}-hint`}
            onChange={(e) => { const f = e.target.files?.[0] ?? null; setFile(f); setError(f ? check(f) : ""); }}
            className="mt-2 block w-full rounded-md border border-line bg-ink px-4 py-3 text-sm text-text file:mr-4 file:rounded-full file:border-0 file:bg-violet/25 file:px-4 file:py-2 file:text-sm file:font-semibold file:text-text hover:file:bg-violet/40 focus:border-violet focus:outline-none disabled:opacity-60" />
          <p id={`${inputId}-hint`} className="mt-2 text-xs text-dim">
            {fileHint}
            {limits && <> Máximo {formatBytes(limits.max_bytes)} · {limits.per_day} por día.</>}
            {file && <> Elegiste <span className="text-muted">{file.name}</span> ({formatBytes(file.size)}).</>}
          </p>
        </div>

        <fieldset disabled={uploading} className="space-y-6">{children}</fieldset>

        {uploading && progress ? (
          <div>
            <div className="flex items-baseline justify-between gap-4 text-sm">
              <p role="status" aria-live="polite">
                {progress.retrying ? "Reconectando… la subida continúa sola." : pct >= 100 ? "Verificando el archivo…" : "Subiendo. No cierres esta pestaña."}
              </p>
              <p className="font-mono text-cyan">{pct}%</p>
            </div>
            <div className="mt-3 h-2 overflow-hidden rounded-full bg-panel-2" role="progressbar"
              aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct} aria-label="Progreso de la subida">
              <div className="h-full bg-linear-to-r from-magenta via-violet to-cyan transition-[width]" style={{ width: `${pct}%` }} />
            </div>
            <p className="mt-2 text-xs text-dim">
              {formatBytes(progress.sent)} de {formatBytes(progress.total)} · parte {Math.min(progress.part + 1, progress.parts)} de {progress.parts}
            </p>
            <Button type="button" variant="ghost" className="mt-5" onClick={() => abort.current?.abort()}>Detener</Button>
          </div>
        ) : (
          <div className="flex flex-wrap items-center gap-4">
            <Button type="submit" disabled={!file || Boolean(error && file && check(file))}>{submitLabel}</Button>
            <Link href="/herramientas/trabajos" className="text-sm text-cyan hover:text-white">Ver mis trabajos →</Link>
          </div>
        )}
      </form>
    </CutCard>
  );
}
