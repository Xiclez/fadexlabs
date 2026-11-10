"use client";

import Link from "next/link";
import { type FormEvent, useState } from "react";

import { AuthShell, Field, FormMessage } from "@/components/auth-ui";
import { Button } from "@/components/ui";
import { api, ApiError, type Message } from "@/lib/api";

export default function RecuperarPage() {
  const [error, setError] = useState("");
  const [done, setDone] = useState("");
  const [pending, setPending] = useState(false);

  async function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    setError("");
    setPending(true);
    try {
      setDone((await api<Message>("/auth/forgot-password", { method: "POST", json: { email: form.get("email") } })).detail);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "No se pudo conectar. Intenta de nuevo.");
    } finally {
      setPending(false);
    }
  }

  return (
    <AuthShell title="Recuperar acceso" subtitle="Te enviamos un enlace para elegir una nueva contraseña. Vence en 30 minutos."
      footer={<Link href="/login" className="text-cyan hover:text-white">Volver a ingresar</Link>}>
      {done ? (
        <FormMessage kind="ok">{done}</FormMessage>
      ) : (
        <form onSubmit={onSubmit} className="space-y-5">
          {error && <FormMessage kind="error">{error}</FormMessage>}
          <Field label="Email" name="email" type="email" autoComplete="email" required />
          <Button type="submit" disabled={pending} className="w-full">{pending ? "Enviando…" : "Enviar enlace"}</Button>
        </form>
      )}
    </AuthShell>
  );
}
