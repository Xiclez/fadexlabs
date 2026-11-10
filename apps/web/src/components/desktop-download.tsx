"use client";

import { useEffect, useState } from "react";

import { CutCard } from "@/components/ui";
import type { DesktopRelease } from "@/lib/api";

/** Descarga de DJ Library Upgrader para Windows (versión publicada en GET /api/desktop/latest). */
export function DesktopDownload() {
  const [release, setRelease] = useState<DesktopRelease | null | undefined>(undefined);

  useEffect(() => {
    fetch("/api/desktop/latest")
      .then((r) => (r.ok ? r.json() : null))
      .then(setRelease)
      .catch(() => setRelease(null));
  }, []);

  return (
    <section id="escritorio" className="mt-12 scroll-mt-24">
      <CutCard innerClassName="grid gap-8 p-8 lg:grid-cols-[1.2fr_1fr]">
        <div>
          <p className="fx-label text-lime">Beta cerrada · Windows 10 y 11</p>
          <h2 className="mt-3 font-display text-3xl font-bold uppercase sm:text-4xl">DJ Library Upgrader para Windows</h2>
          <p className="mt-5 leading-relaxed text-muted">
            La misma mejora de librería, en tu computadora: eliges la carpeta de tu música y el formato, y la app busca,
            descarga, verifica y entrega cada pista con tu propia cuenta de Soulseek. Tu música no se sube a ningún lado;
            nuestros servidores solo comprueban tu lugar en la beta.
          </p>
          <div className="mt-8">
            {release === undefined && <p className="text-sm text-muted" role="status">Buscando la última versión…</p>}
            {release === null && <p className="text-sm text-muted">La descarga se publica muy pronto.</p>}
            {release && (
              <>
                {/* enlace normal (no next/link): es un archivo externo */}
                <a href={release.url}
                  className="inline-flex items-center justify-center gap-2 rounded-full bg-linear-to-r from-magenta via-violet to-cyan px-6 py-3 text-sm font-semibold tracking-wide text-white fx-glow transition hover:brightness-110">
                  Descargar v{release.version} (.exe)
                </a>
                <p className="mt-3 break-all font-mono text-xs text-dim">SHA-256 {release.sha256}</p>
                {release.notas && <p className="mt-3 text-sm text-muted">{release.notas}</p>}
              </>
            )}
          </div>
        </div>
        <ul className="grid content-start gap-3 text-sm">
          <li className="fx-panel border-l-violet px-4 py-3">Se instala sin permisos de administrador y se actualiza sola.</li>
          <li className="fx-panel border-l-violet px-4 py-3">
            Durante la beta el instalador no está firmado: Windows mostrará “Windows protegió su PC”. Pulsa
            <span className="text-text"> Más información → Ejecutar de todos modos</span>.
          </li>
          <li className="fx-panel border-l-violet px-4 py-3">
            Al abrirla, entra con tu cuenta de FADEX: se abre tu navegador para autorizar el equipo.
          </li>
        </ul>
      </CutCard>
    </section>
  );
}
