import type { Metadata } from "next";

import { ButtonLink, Container, DisplayTitle, Label, PanelCard } from "@/components/ui";
import { storeCategories } from "@/content/site";

export const metadata: Metadata = {
  title: "Tienda",
  description: "Loops visuales, librerías de iluminación, guías PDF y cursos para DJs, VJs y LJs.",
};

export default function TiendaPage() {
  return (
    <Container className="py-16">
      <Label>Próximamente</Label>
      <DisplayTitle as="h1" solid="Tienda" outline="& Marketplace" className="mt-4 text-5xl sm:text-7xl" />
      <p className="mt-6 max-w-2xl text-lg text-muted">
        Recursos para la escena, entregados de forma segura desde tu cuenta: compras una vez y descargas cuando lo necesites.
      </p>
      <div className="mt-12 grid gap-4 sm:grid-cols-2">
        {storeCategories.map((c) => <PanelCard key={c.title} {...c} />)}
      </div>
      <div className="mt-12 flex flex-wrap items-center gap-4">
        <p className="text-muted">Crea tu cuenta y te avisamos en cuanto abra.</p>
        <ButtonLink href="/registro">Crear cuenta</ButtonLink>
      </div>
    </Container>
  );
}
