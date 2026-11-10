"use client";

import { useEffect, useState } from "react";

import type { BetaStatus } from "@/lib/api";

/** "Beta cerrada: quedan X de 10 lugares" (dato en vivo de la API). */
export function BetaCounter() {
  const [beta, setBeta] = useState<BetaStatus | null>(null);

  useEffect(() => {
    fetch("/api/beta").then((r) => (r.ok ? r.json() : null)).then(setBeta).catch(() => setBeta(null));
  }, []);

  if (!beta) return null;
  const pct = Math.round((beta.taken / beta.seats) * 100);
  return (
    <div className="fx-panel border-l-lime p-5">
      <p className="fx-label text-lime">Beta cerrada</p>
      <p className="mt-2 font-display text-2xl font-bold uppercase">
        {beta.available > 0
          ? <>Quedan <span className="fx-gradient-text">{beta.available}</span> de {beta.seats} lugares</>
          : "Lugares agotados"}
      </p>
      <div className="mt-4 h-2 overflow-hidden rounded-full bg-panel-2" role="progressbar"
        aria-valuemin={0} aria-valuemax={beta.seats} aria-valuenow={beta.taken} aria-label="Lugares ocupados">
        <div className="h-full bg-linear-to-r from-magenta via-violet to-cyan" style={{ width: `${pct}%` }} />
      </div>
      <p className="mt-3 text-sm text-muted">
        {beta.available > 0
          ? "Acceso para las primeras cuentas registradas que confirmen su email y su WhatsApp."
          : "Crea tu cuenta y te avisamos cuando abramos más lugares."}
      </p>
    </div>
  );
}
