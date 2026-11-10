"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { type FormEvent, Suspense, useState } from "react";

import { AuthShell, Field, FormMessage } from "@/components/auth-ui";
import { Button } from "@/components/ui";
import { api, ApiError, type Message } from "@/lib/api";

function ResetForm() {
  const token = useSearchParams().get("token") ?? "";
  const [error, setError] = useState("");
  const [done, setDone] = useState("");
  const [pending, setPending] = useState(false);

  async function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    if (form.get("password") !== form.get("password2")) {
      setError("Las contraseñas no coinciden.");
      return;
    }
    setError("");
    setPending(true);
    try {
      setDone((await api<Message>("/auth/reset-password", {
        method: "POST", json: { token, password: form.get("password") },
      })).detail);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "No se pudo conectar. Intenta de nuevo.");
    } finally {
      setPending(false);
    }
  }

  if (!token) return <FormMessage kind="error">El enlace no es válido. Pide uno nuevo.</FormMessage>;
  if (done) {
    return (
      <div className="space-y-5">
        <FormMessage kind="ok">{done}</FormMessage>
        <Link href="/login" className="text-cyan hover:text-white">Ir a ingresar →</Link>
      </div>
    );
  }
  return (
    <form onSubmit={onSubmit} className="space-y-5">
      {error && <FormMessage kind="error">{error}</FormMessage>}
      <Field label="Nueva contraseña" name="password" type="password" autoComplete="new-password" minLength={10} required
        hint="Mínimo 10 caracteres. Al cambiarla se cerrarán todas tus sesiones." />
      <Field label="Repite la contraseña" name="password2" type="password" autoComplete="new-password" minLength={10} required />
      <Button type="submit" disabled={pending} className="w-full">{pending ? "Guardando…" : "Guardar contraseña"}</Button>
    </form>
  );
}

export default function RestablecerPage() {
  return (
    <AuthShell title="Nueva contraseña"
      footer={<Link href="/recuperar" className="text-cyan hover:text-white">Pedir otro enlace</Link>}>
      <Suspense fallback={<p className="text-sm text-muted">Cargando…</p>}>
        <ResetForm />
      </Suspense>
    </AuthShell>
  );
}
