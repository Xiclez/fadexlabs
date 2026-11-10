"use client";

import Link from "next/link";
import { type FormEvent, useState } from "react";

import { AuthShell, Field, FormMessage, PrivacyCheckbox } from "@/components/auth-ui";
import { GoogleButton } from "@/components/google-button";
import { Button } from "@/components/ui";
import { api, ApiError, type Message } from "@/lib/api";

export default function RegistroPage() {
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
      const res = await api<Message>("/auth/register", {
        method: "POST",
        json: {
          email: form.get("email"),
          password: form.get("password"),
          display_name: form.get("display_name"),
          whatsapp: form.get("whatsapp"),
          accept_privacy: form.get("accept_privacy") === "on",
        },
      });
      setDone(res.detail);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "No se pudo conectar. Intenta de nuevo.");
    } finally {
      setPending(false);
    }
  }

  return (
    <AuthShell title="Crear cuenta" subtitle="Una sola cuenta para la tienda, el marketplace y las herramientas para DJs."
      footer={<>¿Ya tienes cuenta? <Link href="/login" className="text-cyan hover:text-white">Ingresa</Link></>}>
      {done ? (
        <FormMessage kind="ok">{done}</FormMessage>
      ) : (
        <div className="space-y-5">
          <GoogleButton next="/cuenta" />
          <form onSubmit={onSubmit} className="space-y-5">
            {error && <FormMessage kind="error">{error}</FormMessage>}
            <Field label="Nombre artístico o nombre" name="display_name" autoComplete="nickname" minLength={2} maxLength={80} required />
            <Field label="Email" name="email" type="email" autoComplete="email" required />
            <Field label="WhatsApp" name="whatsapp" type="tel" autoComplete="tel" inputMode="tel" placeholder="614 115 1657" required
              hint="10 dígitos. Si no es de México, incluye la lada internacional (+1, +34…)." />
            <Field label="Contraseña" name="password" type="password" autoComplete="new-password" minLength={10} required
              hint="Mínimo 10 caracteres. Una frase larga es más segura que una contraseña corta." />
            <Field label="Repite la contraseña" name="password2" type="password" autoComplete="new-password" minLength={10} required />
            <PrivacyCheckbox />
            <Button type="submit" disabled={pending} className="w-full">{pending ? "Creando…" : "Crear cuenta"}</Button>
          </form>
        </div>
      )}
    </AuthShell>
  );
}
