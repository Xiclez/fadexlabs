"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef, useState } from "react";

import { AuthShell, FormMessage } from "@/components/auth-ui";
import { api, ApiError, type Message } from "@/lib/api";
import { useAuth } from "@/lib/auth";

function Verify() {
  const token = useSearchParams().get("token") ?? "";
  const { reload, status } = useAuth();
  const [result, setResult] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const sent = useRef(false); // el token es de un solo uso: no reenviar en el doble render de desarrollo

  useEffect(() => {
    if (!token || sent.current) return;
    sent.current = true;
    api<Message>("/auth/verify-email", { method: "POST", json: { token } })
      .then((r) => setResult({ kind: "ok", text: r.detail }))
      .catch((e) => setResult({ kind: "error", text: e instanceof ApiError ? e.message : "No se pudo conectar." }));
  }, [token]);

  useEffect(() => {
    if (result?.kind === "ok" && status === "authenticated") reload();
  }, [result, status, reload]);

  if (!token) return <FormMessage kind="error">El enlace no es válido.</FormMessage>;
  if (!result) return <p className="text-sm text-muted">Confirmando…</p>;
  return (
    <div className="space-y-5">
      <FormMessage kind={result.kind}>{result.text}</FormMessage>
      <Link href={status === "authenticated" ? "/cuenta" : "/login"} className="text-cyan hover:text-white">Continuar →</Link>
    </div>
  );
}

export default function VerificarEmailPage() {
  return (
    <AuthShell title="Confirmar email">
      <Suspense fallback={<p className="text-sm text-muted">Cargando…</p>}>
        <Verify />
      </Suspense>
    </AuthShell>
  );
}
