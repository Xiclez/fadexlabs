"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { FormMessage } from "@/components/auth-ui";
import { ToolGate } from "@/components/tool-gate";
import { Button, ButtonLink, Container, CutCard, cx, Label } from "@/components/ui";
import { api, ApiError, downloadFile, type Job, type JobPage, type JobStatus } from "@/lib/api";
import { formatBytes, formatDate, formatDuration } from "@/lib/format";

const POLL_MS = 4000;
const TOOL = {
  tracklist: { name: "Tracklist ID", href: "/herramientas/tracklist" },
  library_upgrade: { name: "DJ Library Upgrader", href: "/herramientas/library-upgrader" },
};
const STATUS: Record<JobStatus, { label: string; className: string }> = {
  uploading: { label: "Subiendo", className: "text-muted" },
  queued: { label: "En cola", className: "text-violet" },
  running: { label: "En proceso", className: "text-cyan" },
  done: { label: "Listo", className: "text-lime" },
  failed: { label: "No se pudo", className: "text-magenta" },
  expired: { label: "Vencido", className: "text-dim" },
};
const FILE_LABEL: Record<string, string> = {
  "tracklist.txt": "Tracklist (TXT)",
  "tracklist.csv": "Tracklist (CSV)",
  "informe.csv": "Informe por pista (CSV)",
  "no_encontradas.txt": "No encontradas (TXT)",
  "revision.csv": "Revisión de tu librería (CSV)",
};
const active = (j: Job) => j.status === "queued" || j.status === "running";

function StatusTag({ status }: { status: JobStatus }) {
  return <span className={cx("fx-label", STATUS[status].className)}>{STATUS[status].label}</span>;
}

function ProgressBar({ job }: { job: Job }) {
  return (
    <div className="h-2 overflow-hidden rounded-full bg-panel-2" role="progressbar" aria-valuemin={0}
      aria-valuemax={100} aria-valuenow={job.progress} aria-label={`Avance: ${job.message}`}>
      <div className={cx("h-full bg-linear-to-r from-magenta via-violet to-cyan transition-[width] duration-700",
        job.status === "queued" && "animate-pulse")} style={{ width: `${Math.max(job.progress, 3)}%` }} />
    </div>
  );
}

// ---------- lista ----------

export function JobList() {
  return <ToolGate><JobListInner /></ToolGate>;
}

function JobListInner() {
  const [page, setPage] = useState<JobPage | null>(null);
  const [error, setError] = useState("");
  const load = useCallback(() => api<JobPage>("/tools/jobs?limit=50").then((p) => { setPage(p); setError(""); })
    .catch((e) => setError(e instanceof ApiError ? e.message : "No se pudo conectar.")), []);

  useEffect(() => { load(); }, [load]);
  // mientras haya algo en cola o en proceso, se actualiza solo
  const busy = page?.items.some(active) ?? false;
  useEffect(() => {
    if (!busy) return;
    const id = setInterval(load, POLL_MS);
    return () => clearInterval(id);
  }, [busy, load]);

  return (
    <Container className="py-16">
      <Label>Herramientas</Label>
      <h1 className="mt-3 font-display text-4xl font-bold uppercase sm:text-5xl">Mis trabajos</h1>
      <div className="mt-6 flex flex-wrap gap-3">
        <ButtonLink href={TOOL.tracklist.href}>Nueva tracklist</ButtonLink>
        <ButtonLink href={TOOL.library_upgrade.href} variant="ghost">Mejorar mi librería</ButtonLink>
      </div>

      <div className="mt-10">
        {error && <FormMessage kind="error">{error}</FormMessage>}
        {!page && !error && <p className="text-muted" role="status">Cargando…</p>}
        {page && page.items.length === 0 && (
          <p className="fx-panel border-l-violet p-5 text-sm text-muted">Aún no tienes trabajos. Sube un set o tu librería para empezar.</p>
        )}
        {page && page.items.length > 0 && (
          <ul className="space-y-4" aria-live="polite">
            {page.items.map((job) => (
              <li key={job.id}>
                <Link href={`/herramientas/trabajos/${job.id}`} className="fx-panel block border-l-violet p-5 transition hover:border-l-cyan">
                  <div className="flex flex-wrap items-baseline justify-between gap-3">
                    <p className="fx-label text-muted">{TOOL[job.tool].name}</p>
                    <StatusTag status={job.status} />
                  </div>
                  <p className="mt-2 break-all font-semibold">{job.input_name}</p>
                  <p className="mt-1 text-sm text-muted">{job.message}</p>
                  {active(job) && <div className="mt-3"><ProgressBar job={job} /></div>}
                  <p className="mt-3 text-xs text-dim">{formatDate(job.created_at)} · {formatBytes(job.input_bytes)}</p>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </div>
    </Container>
  );
}

// ---------- detalle ----------

export function JobDetail({ id }: { id: string }) {
  return <ToolGate><JobDetailInner id={id} /></ToolGate>;
}

function JobDetailInner({ id }: { id: string }) {
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState<{ status: number; text: string } | null>(null);
  const load = useCallback(() => api<Job>(`/tools/jobs/${encodeURIComponent(id)}`).then((j) => { setJob(j); setError(null); })
    .catch((e) => setError(e instanceof ApiError ? { status: e.status, text: e.message } : { status: 0, text: "No se pudo conectar." })), [id]);

  useEffect(() => { load(); }, [load]);
  const busy = job ? active(job) : false;
  useEffect(() => {
    if (!busy) return;
    const timer = setInterval(load, POLL_MS);
    return () => clearInterval(timer);
  }, [busy, load]);

  if (error && !job) {
    return (
      <Container className="max-w-2xl py-20">
        <FormMessage kind="error">
          {error.status === 404 || error.status === 422 ? "No encontramos este trabajo en tu cuenta." : error.text}
        </FormMessage>
        <div className="mt-8"><ButtonLink href="/herramientas/trabajos" variant="ghost">← Mis trabajos</ButtonLink></div>
      </Container>
    );
  }
  if (!job) return <Container className="py-24"><p className="text-muted" role="status">Cargando…</p></Container>;

  const tool = TOOL[job.tool];
  return (
    <Container className="max-w-3xl py-16">
      <Link href="/herramientas/trabajos" className="fx-label text-muted hover:text-white">← Mis trabajos</Link>
      <div className="mt-6 flex flex-wrap items-baseline justify-between gap-3">
        <Label>{tool.name}</Label>
        <StatusTag status={job.status} />
      </div>
      <h1 className="mt-3 break-all font-display text-2xl font-bold sm:text-3xl">{job.input_name}</h1>
      <p className="mt-2 text-sm text-dim">
        Subido el {formatDate(job.created_at)} · {formatBytes(job.input_bytes)}
        {job.options.formato && <> · entrega en {job.options.formato.toUpperCase()}</>}
      </p>

      <CutCard className="mt-8" innerClassName="p-8">
        {active(job) && (
          <div aria-live="polite">
            <div className="flex items-baseline justify-between gap-4">
              <p className="font-semibold">{job.message}</p>
              <p className="font-mono text-cyan">{job.progress}%</p>
            </div>
            <div className="mt-4"><ProgressBar job={job} /></div>
            <p className="mt-4 text-sm text-muted">
              {job.status === "queued"
                ? "Tu trabajo está en la fila: se procesa uno a la vez por herramienta."
                : job.tool === "library_upgrade"
                  ? "Una librería grande tarda varias horas. Puedes cerrar esta página: te avisamos por email."
                  : "Puedes cerrar esta página: te avisamos por email cuando esté listo."}
            </p>
          </div>
        )}

        {job.status === "failed" && (
          <div>
            <FormMessage kind="error">{job.message}</FormMessage>
            <div className="mt-6"><ButtonLink href={tool.href}>Intentar de nuevo</ButtonLink></div>
          </div>
        )}

        {job.status === "expired" && <p className="text-muted">{job.message}. Los resultados se guardan 30 días.</p>}

        {job.status === "done" && <Result job={job} />}
      </CutCard>
    </Container>
  );
}

function Result({ job }: { job: Job }) {
  const [error, setError] = useState("");
  const s = (job.summary ?? {}) as Record<string, number | string | string[] | Record<string, number> | null>;
  const notes = Array.isArray(s.notes) ? s.notes : [];
  const n = (key: string) => (typeof s[key] === "number" ? (s[key] as number) : 0);

  async function download(name: string) {
    setError("");
    try {
      const base = job.input_name.replace(/\.[^.]+$/, "");
      await downloadFile(`/tools/jobs/${job.id}/files/${name}`, `${base} - ${name}`);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "No se pudo descargar. Intenta de nuevo.");
    }
  }

  const facts: [string, string][] = job.tool === "tracklist"
    ? [
      ["Temas identificados", String(n("tracks"))],
      ["Tramos ID - ID", String(n("unidentified"))],
      ...(n("duration_seconds") ? [["Duración del set", formatDuration(n("duration_seconds"))] as [string, string]] : []),
      ["Motores", (Array.isArray(s.sources) ? s.sources : []).map((x) => (x === "acrcloud" ? "ACRCloud" : "Shazam")).join(" + ")],
    ]
    : [
      ["Pistas en tu librería", String(n("in_library"))],
      ["Se podían mejorar", String(n("to_upgrade"))],
      ["Entregadas", String(n("delivered"))],
      ...(s.by_format && typeof s.by_format === "object" && !Array.isArray(s.by_format)
        ? [["Formatos", Object.entries(s.by_format).map(([k, v]) => `${v} ${k}`).join(", ")] as [string, string]] : []),
      ["No encontradas", String(n("not_found"))],
      ...(n("rejected_other_recording") ? [["Descartadas (otra grabación)", String(n("rejected_other_recording"))] as [string, string]] : []),
      ...(n("fake_lossless") ? [["Falsos lossless (marcados)", String(n("fake_lossless"))] as [string, string]] : []),
      ...(n("doubtful_match") ? [["Coincidencia dudosa (marcadas)", String(n("doubtful_match"))] as [string, string]] : []),
      ...(n("unfinished") ? [["Sin terminar por tiempo", String(n("unfinished"))] as [string, string]] : []),
    ];

  return (
    <div>
      <p className="font-display text-xl font-bold uppercase"><span className="fx-gradient-text">{job.message}</span></p>
      <dl className="mt-6 divide-y divide-line text-sm">
        {facts.filter(([, v]) => v).map(([k, v]) => (
          <div key={k} className="flex justify-between gap-4 py-2.5"><dt className="text-muted">{k}</dt><dd className="text-right">{v}</dd></div>
        ))}
      </dl>
      {notes.map((note) => <p key={note} className="mt-4 rounded-md border border-violet/40 bg-violet/10 px-4 py-3 text-sm">{note}</p>)}

      {job.tool === "library_upgrade" && job.drive_url && (
        <div className="mt-8">
          <a href={job.drive_url} target="_blank" rel="noopener noreferrer"
            className="inline-flex items-center justify-center gap-2 rounded-full bg-linear-to-r from-magenta via-violet to-cyan px-6 py-3 text-sm font-semibold tracking-wide text-white fx-glow transition hover:brightness-110">
            Abrir mi librería en Google Drive ↗
          </a>
          <p className="mt-3 text-xs text-dim">
            Mismos nombres y carpetas que tu original: descarga la carpeta y reemplaza los archivos de tu librería.
          </p>
        </div>
      )}
      {job.tool === "library_upgrade" && s.delivery === "pending" && (
        <p className="mt-6 rounded-md border border-cyan/40 bg-cyan/10 px-4 py-3 text-sm text-cyan" role="status">
          Tu librería ya está lista en nuestro servidor. Te enviaremos el enlace de descarga por WhatsApp.
        </p>
      )}

      {job.files.length > 0 && (
        <div className="mt-8 border-t border-line pt-6">
          <h2 className="fx-label text-violet">Descargas</h2>
          {error && <div className="mt-3"><FormMessage kind="error">{error}</FormMessage></div>}
          <div className="mt-4 flex flex-wrap gap-3">
            {job.files.map((name, i) => (
              <Button key={name} type="button" variant={i === 0 && !job.drive_url ? "primary" : "ghost"} onClick={() => download(name)}>
                {FILE_LABEL[name] ?? name}
              </Button>
            ))}
          </div>
        </div>
      )}
      {job.expires_at && <p className="mt-6 text-xs text-dim">Disponible hasta el {formatDate(job.expires_at)}</p>}
    </div>
  );
}
