"use client";

import { useEffect, useMemo, useState } from "react";

import { cx } from "@/components/ui";
import { api, type TrackLinks, type TracklistVisual, type VisualTrack } from "@/lib/api";

// Colores de marca para los tramos identificados (se alternan); los ID - ID van en gris.
const COLORS = ["#e040c8", "#8b5cf6", "#22d3ee", "#c6f432"];
const ID_COLOR = "#3a3b55";
const LINKS: [keyof TrackLinks, string][] = [
  ["youtube", "YouTube"], ["spotify", "Spotify"], ["beatport", "Beatport"], ["soundcloud", "SoundCloud"],
  ["apple_music", "Apple Music"], ["deezer", "Deezer"], ["shazam", "Shazam"],
];
const LEVEL = { alta: "text-lime", media: "text-cyan", baja: "text-magenta" } as const;

function clock(sec: number) {
  const s = Math.max(0, Math.round(sec));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), r = s % 60;
  return h ? `${h}:${String(m).padStart(2, "0")}:${String(r).padStart(2, "0")}` : `${m}:${String(r).padStart(2, "0")}`;
}

function colorOf(t: VisualTrack, i: number) {
  return t.unidentified ? ID_COLOR : COLORS[i % COLORS.length];
}

/** Forma de onda del set completo, estilo SoundCloud, con cada track marcado como un tramo. */
export function TracklistWave({ jobId }: { jobId: string }) {
  const [data, setData] = useState<TracklistVisual | null>(null);
  const [failed, setFailed] = useState(false);
  const [selected, setSelected] = useState(0);
  const [hover, setHover] = useState<number | null>(null);

  useEffect(() => {
    api<TracklistVisual>(`/tools/jobs/${encodeURIComponent(jobId)}/visual`).then(setData).catch(() => setFailed(true));
  }, [jobId]);

  const view = useMemo(() => {
    if (!data || !data.tracks.length) return null;
    const total = data.duration || data.tracks[data.tracks.length - 1].end || 1;
    const peaks = data.peaks.length ? data.peaks : Array(600).fill(30);
    const n = peaks.length;
    // a qué track pertenece cada barra
    const owner = peaks.map((_, i) => {
      const t = ((i + 0.5) / n) * total;
      const k = data.tracks.findIndex((tr) => t >= tr.start && t < tr.end);
      return k === -1 ? data.tracks.length - 1 : k;
    });
    const step = total > 5400 ? 1800 : total > 1800 ? 900 : 300;  // marcas de tiempo cada 30, 15 o 5 min
    const ticks = Array.from({ length: Math.floor(total / step) + 1 }, (_, i) => i * step).filter((t) => t > 0 && t < total);
    return { total, peaks, n, owner, ticks };
  }, [data]);

  if (failed) return null;
  if (!data || !view) return <p className="mt-8 text-sm text-muted" role="status">Cargando la forma de onda…</p>;

  const { total, peaks, n, owner, ticks } = view;
  const active = hover ?? selected;
  const track = data.tracks[selected];
  const pct = (t: number) => `${(100 * t) / total}%`;

  return (
    <section className="mt-8 border-t border-line pt-6" aria-label="Forma de onda del set con los tracks">
      <h2 className="fx-label text-violet">Tu set, tema por tema</h2>

      <div className="relative mt-6 select-none">
        {/* número de cada tramo sobre la onda (se ocultan si el tramo es muy angosto) */}
        <div className="relative h-6" aria-hidden>
          {data.tracks.map((t, i) => (t.end - t.start) / total > 0.018 && (
            <span key={t.n} style={{ left: pct(t.start) }}
              className={cx("absolute top-0 -translate-x-0 font-mono text-[0.65rem] tabular-nums",
                i === active ? "text-white" : "text-dim")}>
              {String(t.n).padStart(2, "0")}
            </span>
          ))}
        </div>

        <div className="relative h-36 sm:h-44">
          <svg viewBox={`0 0 ${n} 100`} preserveAspectRatio="none" className="absolute inset-0 h-full w-full" aria-hidden>
            {peaks.map((p, i) => {
              const k = owner[i];
              const t = data.tracks[k];
              const top = Math.max(1.5, p * 0.68);
              const on = k === active;
              return (
                <g key={i} fill={colorOf(t, k)} opacity={on ? 1 : 0.5}>
                  <rect x={i + 0.12} y={70 - top} width={0.76} height={top} />
                  {/* reflejo, como en SoundCloud */}
                  <rect x={i + 0.12} y={71} width={0.76} height={top * 0.42} opacity={0.35} />
                </g>
              );
            })}
          </svg>
          {/* tramos: líneas de corte y zonas para elegir cada track */}
          {data.tracks.map((t, i) => (
            <button key={t.n} type="button" tabIndex={-1} aria-hidden
              style={{ left: pct(t.start), width: pct(t.end - t.start) }}
              onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)} onClick={() => setSelected(i)}
              className={cx("absolute inset-y-0 border-l transition",
                i === active ? "border-white/70 bg-white/6" : "border-white/15 hover:bg-white/4")} />
          ))}
          {hover !== null && (
            <div className="pointer-events-none absolute -top-2 z-10 max-w-[70%] -translate-y-full truncate rounded-md border border-line bg-panel-2 px-3 py-1.5 text-xs shadow-lg"
              style={{ left: `min(${pct(data.tracks[hover].start)}, 30%)` }}>
              <span className="font-mono text-dim">{clock(data.tracks[hover].start)}</span>{" "}
              {data.tracks[hover].unidentified ? "ID - ID" : `${data.tracks[hover].artist} - ${data.tracks[hover].title}`}
            </div>
          )}
        </div>

        <div className="relative mt-1 h-4 font-mono text-[0.65rem] text-dim" aria-hidden>
          <span className="absolute left-0">0:00</span>
          {ticks.map((t) => <span key={t} style={{ left: pct(t) }} className="absolute -translate-x-1/2">{clock(t)}</span>)}
          <span className="absolute right-0">{clock(total)}</span>
        </div>
      </div>

      {track && <TrackCard track={track} color={colorOf(track, selected)} />}

      <ol className="mt-6 divide-y divide-line border-y border-line">
        {data.tracks.map((t, i) => (
          <li key={t.n}>
            <button type="button" onClick={() => setSelected(i)} aria-current={i === selected ? "true" : undefined}
              onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}
              className={cx("flex w-full items-center gap-4 px-2 py-2.5 text-left text-sm transition hover:bg-white/4",
                i === selected && "bg-violet/10")}>
              <span className="h-8 w-1 shrink-0 rounded-full" style={{ background: colorOf(t, i) }} aria-hidden />
              <span className="w-16 shrink-0 font-mono text-xs text-dim">{clock(t.start)}</span>
              <span className="min-w-0 flex-1 truncate">
                {t.unidentified ? <span className="text-dim">ID - ID</span>
                  : <><span className="font-semibold">{t.title}</span> <span className="text-muted">· {t.artist}</span></>}
              </span>
              {t.level && <span className={cx("fx-label hidden sm:inline", LEVEL[t.level])}>{t.level}</span>}
            </button>
          </li>
        ))}
      </ol>
    </section>
  );
}

function TrackCard({ track, color }: { track: VisualTrack; color: string }) {
  const facts = [["Álbum", track.meta.album], ["Sello", track.meta.label], ["Año", track.meta.year],
    ["Género", track.meta.genre], ["ISRC", track.meta.isrc]].filter(([, v]) => v) as [string, string][];
  return (
    <div className="mt-6 fx-panel flex flex-col gap-5 p-5 sm:flex-row" style={{ borderLeftColor: color }} aria-live="polite">
      {track.meta.cover && (
        // carátula externa (Shazam): un <img> simple, sin optimizar
        // eslint-disable-next-line @next/next/no-img-element
        <img src={track.meta.cover} alt="" width={112} height={112} loading="lazy"
          className="h-28 w-28 shrink-0 rounded-md object-cover" referrerPolicy="no-referrer" />
      )}
      <div className="min-w-0 flex-1">
        <p className="fx-label text-dim">
          {String(track.n).padStart(2, "0")} · {clock(track.start)} – {clock(track.end)}
        </p>
        {track.unidentified ? (
          <>
            <p className="mt-2 font-display text-xl font-bold uppercase">ID - ID</p>
            <p className="mt-1 text-sm text-muted">Tramo sin identificar.{track.note && ` ${track.note[0].toUpperCase()}${track.note.slice(1)}.`}</p>
          </>
        ) : (
          <>
            <p className="mt-2 font-display text-xl font-bold uppercase leading-tight">{track.title}</p>
            <p className="text-muted">{track.artist}</p>
            {track.confidence !== null && track.level && (
              <p className="mt-2 text-xs text-dim">
                Confianza <span className={LEVEL[track.level]}>{track.confidence}/100 ({track.level})</span>
              </p>
            )}
            {facts.length > 0 && (
              <dl className="mt-3 flex flex-wrap gap-x-5 gap-y-1 text-xs">
                {facts.map(([k, v]) => <div key={k}><dt className="inline text-dim">{k}: </dt><dd className="inline">{v}</dd></div>)}
              </dl>
            )}
            <div className="mt-4 flex flex-wrap gap-2">
              {LINKS.map(([key, label]) => track.links[key] && (
                <a key={key} href={track.links[key]} target="_blank" rel="noopener noreferrer"
                  className="rounded-full border border-line px-3.5 py-1.5 text-xs font-semibold transition hover:border-violet hover:text-white">
                  {label} ↗
                </a>
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
