"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";

import { AuthShell, FormMessage } from "@/components/auth-ui";
import { Button } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";

// Lo que manda la app de escritorio en la URL (ver apps/api/app/routers/desktop.py)
const B64URL = /^[A-Za-z0-9_-]+$/;

function readRequest(q: URLSearchParams) {
  const challenge = q.get("code_challenge") ?? "";
  const state = q.get("state") ?? "";
  const port = Number(q.get("redirect_port"));
  const valid = challenge.length === 43 && B64URL.test(challenge) && state.length >= 16 && state.length <= 128
    && B64URL.test(state) && Number.isInteger(port) && port >= 1024 && port <= 65535
    && (q.get("code_challenge_method") ?? "S256") === "S256";
  return valid ? { challenge, state, port, device: (q.get("device") ?? "").slice(0, 60) } : null;
}

function Authorize() {
  const { user, status } = useAuth();
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const req = readRequest(params);
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);

  useEffect(() => {
    const here = `${pathname}?${params.toString()}`;
    if (status === "anonymous") router.replace(`/login?next=${encodeURIComponent(here)}`);
    if (status === "authenticated" && user && !user.profile_complete) {
      router.replace(`/completar-perfil?next=${encodeURIComponent(here)}`);
    }
  }, [status, user, router, pathname, params]);

  if (!req) {
    return (
      <FormMessage kind="error">
        Este enlace de autorización no es válido. Vuelve a la app y pulsa “Entrar con FADEX” otra vez.
      </FormMessage>
    );
  }
  if (status !== "authenticated" || !user || !user.profile_complete) {
    return <p className="text-sm text-muted" role="status">Cargando…</p>;
  }

  async function allow() {
    if (!req) return;
    setPending(true);
    setError("");
    try {
      const { redirect_url } = await api<{ redirect_url: string }>("/auth/desktop/authorize", {
        method: "POST",
        json: { code_challenge: req.challenge, state: req.state, redirect_port: req.port, device_name: req.device },
      });
      window.location.href = redirect_url;  // la app recibe el código en su puerto local
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "No se pudo conectar. Intenta de nuevo.");
      setPending(false);
    }
  }

  function deny() {
    if (!req) return;
    window.location.href = `http://127.0.0.1:${req.port}/callback?error=access_denied&state=${encodeURIComponent(req.state)}`;
  }

  const allowed = user.beta || user.role === "admin";
  return (
    <div className="space-y-5">
      {error && <FormMessage kind="error">{error}</FormMessage>}
      <dl className="space-y-3 text-sm">
        <div className="flex justify-between gap-4"><dt className="text-muted">Cuenta</dt><dd>{user.email}</dd></div>
        {req.device && <div className="flex justify-between gap-4"><dt className="text-muted">Equipo</dt><dd>{req.device}</dd></div>}
      </dl>
      <p className="text-sm text-muted">
        La app podrá usar tu cuenta en este equipo para comprobar tu lugar en la beta. Puedes quitarle el acceso
        cuando quieras desde <span className="text-text">Mi cuenta → Sesiones activas</span>.
      </p>
      {!allowed && (
        <p className="fx-panel border-l-violet p-4 text-sm">
          Tu cuenta todavía no tiene lugar en la beta cerrada: puedes autorizar el equipo, pero la app no podrá
          mejorar librerías hasta que tengas lugar.
        </p>
      )}
      <div className="flex flex-col gap-3 sm:flex-row">
        <Button onClick={allow} disabled={pending} className="flex-1">{pending ? "Autorizando…" : "Autorizar"}</Button>
        <Button variant="ghost" onClick={deny} disabled={pending} className="flex-1">Cancelar</Button>
      </div>
    </div>
  );
}

export default function AutorizarEscritorioPage() {
  return (
    <AuthShell title="Autorizar DJ Library Upgrader"
      subtitle="Estás por conectar la app de escritorio de este equipo con tu cuenta de FADEX.">
      <Suspense fallback={<p className="text-sm text-muted">Cargando…</p>}>
        <Authorize />
      </Suspense>
    </AuthShell>
  );
}
