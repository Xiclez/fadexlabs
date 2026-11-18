"use client";

import { type FormEvent, useState } from "react";

import { FormMessage } from "@/components/auth-ui";
import { Button, cx } from "@/components/ui";
import { api, ApiError, type FeedbackResult, type Job } from "@/lib/api";

const LABELS = ["", "Mala", "Regular", "Buena", "Muy buena", "Excelente"];

/** Solo conteos del resumen: es lo que se adjunta a la opinión. */
function details(job: Job): Record<string, number | string | boolean> {
  const out: Record<string, number | string | boolean> = {};
  for (const [k, v] of Object.entries(job.summary ?? {})) {
    if (typeof v === "number" || typeof v === "boolean" || (typeof v === "string" && v.length <= 40)) out[k] = v;
  }
  return out;
}

export function StarRating({ value, onChange }: { value: number; onChange: (n: number) => void }) {
  const [hover, setHover] = useState(0);
  const shown = hover || value;
  return (
    <div role="radiogroup" aria-label="Calificación" className="flex items-center gap-1" onMouseLeave={() => setHover(0)}>
      {[1, 2, 3, 4, 5].map((n) => (
        <button key={n} type="button" role="radio" aria-checked={value === n} aria-label={`${n} de 5: ${LABELS[n]}`}
          onMouseEnter={() => setHover(n)} onClick={() => onChange(n)}
          onKeyDown={(e) => {
            if (e.key === "ArrowRight" || e.key === "ArrowUp") { e.preventDefault(); onChange(Math.min(5, (value || 0) + 1)); }
            if (e.key === "ArrowLeft" || e.key === "ArrowDown") { e.preventDefault(); onChange(Math.max(1, (value || 2) - 1)); }
          }}
          tabIndex={value === n || (!value && n === 1) ? 0 : -1}
          className={cx("text-3xl leading-none transition", n <= shown ? "text-lime drop-shadow-[0_0_8px_rgb(198_244_50/0.5)]" : "text-line hover:text-dim")}>
          ★
        </button>
      ))}
      <span className="ml-3 text-sm text-muted" aria-live="polite">{shown ? LABELS[shown] : ""}</span>
    </div>
  );
}

/** Encuesta al terminar o detener un trabajo: estrellas + comentario breve. Con comentario, invita al Google Forms. */
export function FeedbackPrompt({ job, onSent }: { job: Job; onSent?: () => void }) {
  const [rating, setRating] = useState(0);
  const [comment, setComment] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<FeedbackResult | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!rating) return setError("Elige de 1 a 5 estrellas.");
    setPending(true);
    setError("");
    try {
      setResult(await api<FeedbackResult>("/feedback", {
        method: "POST",
        json: { source: "web", tool: job.tool, job_ref: job.id, rating, comment: comment.trim(), stopped: job.stopped, details: details(job) },
      }));
      onSent?.();
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) setResult({ detail: err.message, form_url: null });
      else setError(err instanceof ApiError ? err.message : "No se pudo enviar. Intenta de nuevo.");
    } finally {
      setPending(false);
    }
  }

  if (result) {
    return (
      <section className="mt-8 border-t border-line pt-6" aria-live="polite">
        <p className="fx-label text-lime">¡Gracias!</p>
        <p className="mt-2 text-sm">{result.detail}</p>
        {result.form_url && (
          <div className="mt-5 fx-panel border-l-lime p-5">
            <p className="font-display text-lg font-bold uppercase">Una cosa más</p>
            <p className="mt-2 text-sm text-muted">
              Responde 8 preguntas (2 minutos) y te damos <span className="text-text">acceso prioritario</span> y{" "}
              <span className="text-text">un trimestre gratis</span> cuando salga la versión oficial.
            </p>
            <a href={result.form_url} target="_blank" rel="noopener noreferrer"
              className="mt-4 inline-flex items-center justify-center gap-2 rounded-full bg-linear-to-r from-magenta via-violet to-cyan px-6 py-3 text-sm font-semibold tracking-wide text-white fx-glow transition hover:brightness-110">
              Responder la encuesta ↗
            </a>
          </div>
        )}
      </section>
    );
  }

  return (
    <form onSubmit={submit} className="mt-8 border-t border-line pt-6">
      <h2 className="fx-label text-violet">{job.stopped ? "Lo detuviste: ¿cómo te fue?" : "¿Cómo te fue?"}</h2>
      <p className="mt-2 text-sm text-muted">Estás usando la beta: tu opinión decide qué mejoramos primero.</p>
      <div className="mt-4"><StarRating value={rating} onChange={setRating} /></div>
      <label className="mt-5 block">
        <span className="fx-label text-muted">Comentario breve (opcional)</span>
        <textarea value={comment} onChange={(e) => setComment(e.target.value)} maxLength={500} rows={3}
          placeholder="¿Qué te gustó? ¿Qué falló o qué te faltó?"
          className="mt-2 w-full rounded-md border border-line bg-ink px-4 py-3 text-sm text-text placeholder:text-dim focus:border-violet focus:outline-none" />
        <span className="mt-1 block text-right text-xs text-dim">{comment.length}/500</span>
      </label>
      {error && <div className="mt-3"><FormMessage kind="error">{error}</FormMessage></div>}
      <div className="mt-4"><Button type="submit" disabled={pending}>{pending ? "Enviando…" : "Enviar opinión"}</Button></div>
    </form>
  );
}
