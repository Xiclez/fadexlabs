"use client";

import { ButtonLink } from "@/components/ui";
import { useAuth } from "@/lib/auth";

const HREF: Record<string, string> = {
  "tracklist-id": "/herramientas/tracklist",
  "dj-library-upgrader": "/herramientas/library-upgrader",
};

/** Botón de cada herramienta en /herramientas: quien tiene lugar entra directo; el resto ve cómo apartarlo. */
export function ToolAccess({ slug, name }: { slug: string; name: string }) {
  const { user, status } = useAuth();
  const allowed = status === "authenticated" && user && (user.beta || user.role === "admin");
  if (allowed && HREF[slug]) {
    return (
      <div className="flex flex-wrap items-center gap-3">
        <ButtonLink href={HREF[slug]}>Abrir {name}</ButtonLink>
        <ButtonLink href="/herramientas/trabajos" variant="ghost">Mis trabajos</ButtonLink>
      </div>
    );
  }
  if (status === "authenticated") return <ButtonLink href="/cuenta" variant="ghost">Ver el estado de mi lugar</ButtonLink>;
  return <ButtonLink href="/registro">Crea tu cuenta y aparta tu lugar</ButtonLink>;
}
