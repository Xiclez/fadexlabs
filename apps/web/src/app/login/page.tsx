"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { type FormEvent, Suspense, useState } from "react";

import { AuthShell, Field, FormMessage } from "@/components/auth-ui";
import { GoogleButton } from "@/components/google-button";
import { Button } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";

// Códigos que devuelve /api/auth/google/callback en ?error=
const GOOGLE_ERRORS: Record<string, string> = {
  google_cancelado: "Cancelaste el inicio de sesión con Google.",
  google_estado: "La sesión con Google no coincide con este navegador. Intenta de nuevo.",
  google_vencido: "El inicio de sesión con Google venció. Intenta de nuevo.",
  google_invalido: "Google no pudo confirmar tu identidad. Intenta de nuevo.",
  google_email: "Tu cuenta de Google no tiene el email verificado.",
  cuenta_inactiva: "Esta cuenta está desactivada. Escríbenos para ayudarte.",
};

function GoogleError() {
  const code = useSearchParams().get("error");
  return code && GOOGLE_ERRORS[code] ? <FormMessage kind="error">{GOOGLE_ERRORS[code]}</FormMessage> : null;
}

function safeNext(path: string | null) {
  return path && path.startsWith("/") && !path.startsWith("//") && !path.includes("\\") ? path : "/cuenta";
}

export default function LoginPage() {
  return (
    <AuthShell title="Ingresar" subtitle="Accede a tus compras, descargas y herramientas."
      footer={<>¿No tienes cuenta? <Link href="/registro" className="text-cyan hover:text-white">Créala aquí</Link></>}>
      <Suspense fallback={<p className="text-sm text-muted">Cargando…</p>}>
        <LoginForm />
      </Suspense>
    </AuthShell>
  );
}

/** ?next= lleva de vuelta a donde se pidió el login (p. ej. autorizar la app de escritorio). */
function LoginForm() {
  const { login } = useAuth();
  const router = useRouter();
  const next = safeNext(useSearchParams().get("next"));
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);

  async function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    setError("");
    setPending(true);
    try {
      await login(String(form.get("email")), String(form.get("password")));
      router.push(next);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "No se pudo conectar. Intenta de nuevo.");
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="space-y-5">
      <GoogleError />
      <GoogleButton next={next} />
      <form onSubmit={onSubmit} className="space-y-5">
        {error && <FormMessage kind="error">{error}</FormMessage>}
        <Field label="Email" name="email" type="email" autoComplete="email" required />
        <Field label="Contraseña" name="password" type="password" autoComplete="current-password" required />
        <Button type="submit" disabled={pending} className="w-full">{pending ? "Ingresando…" : "Ingresar"}</Button>
        <p className="text-center text-sm">
          <Link href="/recuperar" className="text-muted hover:text-white">¿Olvidaste tu contraseña?</Link>
        </p>
      </form>
    </div>
  );
}
