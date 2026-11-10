"use client";

import { useRouter } from "next/navigation";
import { type FormEvent, useCallback, useEffect, useState } from "react";

import { Field, FormMessage } from "@/components/auth-ui";
import { Button, Container, CutCard, Label } from "@/components/ui";
import { api, ApiError, type Message, type Session, setAccessToken } from "@/lib/api";
import { useAuth } from "@/lib/auth";

function describeAgent(ua: string) {
  const browser = /Edg\//.test(ua) ? "Edge" : /Chrome\//.test(ua) ? "Chrome" : /Firefox\//.test(ua) ? "Firefox"
    : /Safari\//.test(ua) ? "Safari" : "Navegador";
  const os = /Windows/.test(ua) ? "Windows" : /Android/.test(ua) ? "Android" : /iPhone|iPad/.test(ua) ? "iOS"
    : /Mac OS/.test(ua) ? "macOS" : /Linux/.test(ua) ? "Linux" : "";
  return os ? `${browser} · ${os}` : browser;
}

const fmt = (iso: string) => new Date(iso).toLocaleString("es-MX", { dateStyle: "medium", timeStyle: "short" });

export default function CuentaPage() {
  const { user, status, logout } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (status === "anonymous") router.replace("/login");
    if (status === "authenticated" && user && !user.profile_complete) router.replace("/completar-perfil");
  }, [status, user, router]);

  if (status !== "authenticated" || !user || !user.profile_complete) {
    return <Container className="py-24"><p className="text-muted">Cargando tu cuenta…</p></Container>;
  }

  return (
    <Container className="py-16">
      <Label>Mi cuenta</Label>
      <h1 className="mt-3 font-display text-4xl font-bold uppercase sm:text-5xl">
        Hola, <span className="fx-gradient-text">{user.display_name}</span>
      </h1>
      <p className="mt-2 text-muted">{user.email}</p>

      {!user.email_verified && <VerifyBanner />}

      <div className={`mt-6 fx-panel p-5 ${user.beta ? "border-l-lime" : "border-l-violet"}`}>
        <p className={`fx-label ${user.beta ? "text-lime" : "text-violet"}`}>Beta cerrada · herramientas para DJs</p>
        <p className="mt-2 text-sm">
          {user.beta
            ? <>Tienes el lugar <span className="font-semibold text-lime">#{user.beta_seat}</span>: acceso a Tracklist ID y DJ Library Upgrader.</>
            : user.email_verified
              ? "Los lugares de la beta ya se ocuparon. Te avisaremos por WhatsApp cuando abramos más."
              : "Confirma tu email para entrar a la beta si aún quedan lugares."}
        </p>
      </div>

      <div className="mt-10 grid gap-6 lg:grid-cols-2">
        <CutCard>
          <h2 className="font-display text-lg font-bold uppercase">Perfil</h2>
          <dl className="mt-5 space-y-3 text-sm">
            <div className="flex justify-between gap-4"><dt className="text-muted">Rol</dt><dd className="capitalize">{user.role}</dd></div>
            <div className="flex justify-between gap-4"><dt className="text-muted">Email</dt>
              <dd>{user.email_verified ? <span className="text-cyan">Confirmado</span> : <span className="text-magenta">Sin confirmar</span>}</dd></div>
            <div className="flex justify-between gap-4"><dt className="text-muted">WhatsApp</dt><dd>{user.whatsapp}</dd></div>
            <div className="flex justify-between gap-4"><dt className="text-muted">Google</dt>
              <dd>{user.google_linked ? <span className="text-cyan">Vinculada</span> : "No vinculada"}</dd></div>
            <div className="flex justify-between gap-4"><dt className="text-muted">Miembro desde</dt><dd>{fmt(user.created_at)}</dd></div>
          </dl>
          <div className="mt-8 border-t border-line pt-6">
            <h3 className="fx-label text-violet">Compras y descargas</h3>
            <p className="mt-2 text-sm text-muted">Aquí aparecerán tus productos cuando abra la tienda.</p>
          </div>
        </CutCard>

        {user.has_password ? <ChangePassword /> : (
          <CutCard>
            <h2 className="font-display text-lg font-bold uppercase">Contraseña</h2>
            <p className="mt-4 text-sm text-muted">
              Entras con Google, así que tu cuenta no tiene contraseña. Si también quieres entrar con email y
              contraseña, usa <a href="/recuperar" className="text-cyan hover:text-white">“¿Olvidaste tu contraseña?”</a> para crear una.
            </p>
          </CutCard>
        )}
      </div>

      <Sessions onLogoutAll={async () => { await logout(); router.replace("/login"); }} />

      <div className="mt-10">
        <Button variant="ghost" onClick={async () => { await logout(); router.push("/"); }}>Cerrar sesión</Button>
      </div>
    </Container>
  );
}

function VerifyBanner() {
  const [msg, setMsg] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  return (
    <div className="mt-6 flex flex-col gap-3 rounded-md border border-magenta/40 bg-magenta/10 p-4 sm:flex-row sm:items-center sm:justify-between">
      <p className="text-sm">Confirma tu email para poder comprar y descargar. Revisa tu bandeja de entrada.</p>
      {msg ? <p className={msg.kind === "ok" ? "text-sm text-cyan" : "text-sm text-magenta"}>{msg.text}</p> : (
        <Button variant="ghost" className="shrink-0" onClick={async () => {
          try {
            setMsg({ kind: "ok", text: (await api<Message>("/auth/resend-verification", { method: "POST" })).detail });
          } catch (e) {
            setMsg({ kind: "error", text: e instanceof ApiError ? e.message : "No se pudo enviar." });
          }
        }}>Reenviar enlace</Button>
      )}
    </div>
  );
}

function ChangePassword() {
  const [msg, setMsg] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const [pending, setPending] = useState(false);

  async function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const formEl = e.currentTarget;
    const form = new FormData(formEl);
    if (form.get("new_password") !== form.get("new_password2")) {
      setMsg({ kind: "error", text: "Las contraseñas nuevas no coinciden." });
      return;
    }
    setPending(true);
    setMsg(null);
    try {
      const { access_token } = await api<{ access_token: string }>("/auth/change-password", {
        method: "POST", json: { current_password: form.get("current_password"), new_password: form.get("new_password") },
      });
      setAccessToken(access_token);
      formEl.reset();
      setMsg({ kind: "ok", text: "Contraseña actualizada. Cerramos tus otras sesiones." });
    } catch (err) {
      setMsg({ kind: "error", text: err instanceof ApiError ? err.message : "No se pudo conectar." });
    } finally {
      setPending(false);
    }
  }

  return (
    <CutCard>
      <h2 className="font-display text-lg font-bold uppercase">Cambiar contraseña</h2>
      <form onSubmit={onSubmit} className="mt-5 space-y-4">
        {msg && <FormMessage kind={msg.kind}>{msg.text}</FormMessage>}
        <Field label="Contraseña actual" name="current_password" type="password" autoComplete="current-password" required />
        <Field label="Nueva contraseña" name="new_password" type="password" autoComplete="new-password" minLength={10} required />
        <Field label="Repite la nueva" name="new_password2" type="password" autoComplete="new-password" minLength={10} required />
        <Button type="submit" disabled={pending}>{pending ? "Guardando…" : "Actualizar"}</Button>
      </form>
    </CutCard>
  );
}

function Sessions({ onLogoutAll }: { onLogoutAll: () => Promise<void> }) {
  const [sessions, setSessions] = useState<Session[] | null>(null);
  const load = useCallback(() => api<Session[]>("/auth/sessions").then(setSessions).catch(() => setSessions([])), []);
  useEffect(() => { load(); }, [load]);

  return (
    <section className="mt-6">
      <CutCard>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="font-display text-lg font-bold uppercase">Sesiones activas</h2>
          <Button variant="ghost" onClick={async () => { await api("/auth/logout-all", { method: "POST" }); await onLogoutAll(); }}>
            Cerrar todas
          </Button>
        </div>
        {!sessions ? <p className="mt-5 text-sm text-muted">Cargando…</p> : (
          <ul className="mt-5 divide-y divide-line">
            {sessions.map((s) => (
              <li key={s.id} className="flex flex-wrap items-center justify-between gap-3 py-4 text-sm">
                <div>
                  <p>
                    {s.kind === "desktop" ? s.user_agent : describeAgent(s.user_agent)}
                    {s.kind === "desktop" && <span className="fx-label ml-2 text-cyan">App de escritorio</span>}
                    {s.current && <span className="fx-label ml-2 text-lime">Esta sesión</span>}
                  </p>
                  <p className="text-xs text-dim">{s.ip} · último uso {fmt(s.last_used_at)}</p>
                </div>
                {!s.current && (
                  <button type="button" className="fx-label text-magenta hover:text-white"
                    onClick={async () => { await api(`/auth/sessions/${s.id}`, { method: "DELETE" }); load(); }}>
                    Cerrar
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}
      </CutCard>
    </section>
  );
}
