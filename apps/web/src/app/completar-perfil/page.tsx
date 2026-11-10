"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { type FormEvent, Suspense, useEffect, useState } from "react";

import { AuthShell, Field, FormMessage, PrivacyCheckbox } from "@/components/auth-ui";
import { Button } from "@/components/ui";
import { api, ApiError, setAccessToken } from "@/lib/api";
import { useAuth } from "@/lib/auth";

function safeNext(path: string | null) {
  return path && path.startsWith("/") && !path.startsWith("//") ? path : "/cuenta";
}

function ProfileForm() {
  const { user, status, reload } = useAuth();
  const router = useRouter();
  const next = safeNext(useSearchParams().get("next"));
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);

  useEffect(() => {
    if (status === "anonymous") router.replace("/login");
    if (status === "authenticated" && user?.profile_complete) router.replace(next);
  }, [status, user, router, next]);

  async function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    setError("");
    setPending(true);
    try {
      const { access_token } = await api<{ access_token: string }>("/auth/complete-profile", {
        method: "POST",
        json: {
          whatsapp: form.get("whatsapp"),
          accept_privacy: form.get("accept_privacy") === "on",
          display_name: form.get("display_name") || null,
        },
      });
      setAccessToken(access_token);
      await reload();
      router.replace(next);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "No se pudo conectar. Intenta de nuevo.");
    } finally {
      setPending(false);
    }
  }

  if (status !== "authenticated" || !user) return <p className="text-sm text-muted">Cargando…</p>;
  return (
    <form onSubmit={onSubmit} className="space-y-5">
      {error && <FormMessage kind="error">{error}</FormMessage>}
      <Field label="Nombre artístico o nombre" name="display_name" defaultValue={user.display_name}
        autoComplete="nickname" minLength={2} maxLength={80} />
      <Field label="WhatsApp" name="whatsapp" type="tel" autoComplete="tel" inputMode="tel" placeholder="614 115 1657" required
        hint="10 dígitos. Si no es de México, incluye la lada internacional." />
      <PrivacyCheckbox />
      <Button type="submit" disabled={pending} className="w-full">{pending ? "Guardando…" : "Continuar"}</Button>
    </form>
  );
}

export default function CompletarPerfilPage() {
  return (
    <AuthShell title="Un paso más" subtitle="Necesitamos tu WhatsApp para soporte y para avisarte de la beta de las herramientas.">
      <Suspense fallback={<p className="text-sm text-muted">Cargando…</p>}>
        <ProfileForm />
      </Suspense>
    </AuthShell>
  );
}
