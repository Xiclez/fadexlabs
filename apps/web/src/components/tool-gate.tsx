"use client";

import { useRouter } from "next/navigation";
import { type ReactNode, useEffect } from "react";

import { BetaCounter } from "@/components/beta-counter";
import { ButtonLink, Container, Label } from "@/components/ui";
import { useAuth } from "@/lib/auth";

/** Solo deja pasar a quien tiene lugar en la beta (o es admin) y ya confirmó su email.
 *  Sin sesión manda a /login; sin lugar explica la beta cerrada. */
export function ToolGate({ children }: { children: ReactNode }) {
  const { user, status } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (status === "anonymous") router.replace("/login");
    if (status === "authenticated" && user && !user.profile_complete) router.replace("/completar-perfil");
  }, [status, user, router]);

  if (status !== "authenticated" || !user || !user.profile_complete) {
    return <Container className="py-24"><p className="text-muted" role="status">Cargando…</p></Container>;
  }
  if (!user.email_verified) {
    return (
      <Container className="max-w-2xl py-20">
        <Label>Falta un paso</Label>
        <h1 className="mt-4 font-display text-3xl font-bold uppercase">Confirma tu email</h1>
        <p className="mt-4 text-muted">
          Te enviamos un enlace de confirmación. Ábrelo para usar las herramientas; puedes reenviarlo desde tu cuenta.
        </p>
        <div className="mt-8"><ButtonLink href="/cuenta">Ir a mi cuenta</ButtonLink></div>
      </Container>
    );
  }
  if (!(user.beta || user.role === "admin")) {
    return (
      <Container className="max-w-2xl py-20">
        <Label>Beta cerrada</Label>
        <h1 className="mt-4 font-display text-3xl font-bold uppercase">Aún no tienes lugar</h1>
        <p className="mt-4 text-muted">
          Las herramientas para DJs están en beta cerrada: por ahora solo las usan las primeras cuentas que
          confirmaron su email y su WhatsApp. Te avisaremos por WhatsApp cuando abramos más lugares.
        </p>
        <div className="mt-8"><BetaCounter /></div>
        <div className="mt-8"><ButtonLink href="/herramientas" variant="ghost">Ver las herramientas</ButtonLink></div>
      </Container>
    );
  }
  return <>{children}</>;
}
