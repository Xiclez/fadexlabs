import type { Metadata } from "next";
import Link from "next/link";

import { ButtonLink, Container, DisplayTitle, Label, Pill, PlanCard } from "@/components/ui";
import { contact, serviceGroups } from "@/content/site";

export const metadata: Metadata = {
  title: "Servicios",
  description: "Grabación de DJ sets, fotografía y video, press kits, marketing digital, community management, e-commerce, impresiones y software.",
};

export default function ServiciosPage() {
  return (
    <Container className="py-16">
      <Label>Catálogo de servicios</Label>
      <DisplayTitle as="h1" solid="Servicios" outline="FADEX Labs" className="mt-4 text-5xl sm:text-7xl" />
      <p className="mt-6 max-w-2xl text-lg text-muted">
        Referencias de inversión en MXN. La cotización final depende de locación, duración, logística, entregables y requerimientos técnicos.
      </p>

      <nav aria-label="Categorías" className="mt-10 flex flex-wrap gap-2">
        {serviceGroups.map((g) => (
          <Link key={g.id} href={`#${g.id}`}
            className="fx-label rounded-full border border-line px-4 py-2 text-muted hover:border-violet hover:text-white">
            {g.title} {g.outline}
          </Link>
        ))}
      </nav>

      {serviceGroups.map((g) => (
        <section key={g.id} id={g.id} className="scroll-mt-24 border-t border-line pt-14 mt-16">
          <div className="mb-8 grid gap-6 lg:grid-cols-[1fr_1fr] lg:items-end">
            <div>
              <Label className="text-magenta">{g.label}</Label>
              <DisplayTitle solid={g.title} outline={g.outline} className="mt-3 text-4xl sm:text-5xl" />
            </div>
            <div className="text-muted">
              <p className="text-lg text-text">{g.tagline}</p>
              {g.intro && <p className="mt-3 text-sm leading-relaxed">{g.intro}</p>}
            </div>
          </div>

          <div className={`grid gap-5 sm:grid-cols-2 ${g.plans.length >= 4 ? "lg:grid-cols-4" : "lg:grid-cols-3"}`}>
            {g.plans.map((p, i) => <PlanCard key={p.name} plan={p} index={i} />)}
          </div>

          {g.extras && (
            <div className="mt-8">
              <p className="fx-label mb-3 text-violet">Servicios adicionales</p>
              <div className="flex flex-wrap gap-2">{g.extras.map((e) => <Pill key={e}>{e}</Pill>)}</div>
            </div>
          )}
          {g.notes && (
            <ul className="mt-6 space-y-1 text-xs text-dim">
              {g.notes.map((n) => <li key={n}>· {n}</li>)}
            </ul>
          )}
        </section>
      ))}

      <section className="mt-20 border-t border-line pt-12">
        <p className="text-sm text-dim">
          No incluye renta de equipo, viáticos, traslados, permisos, talento externo ni costos de venue. Eventos completos,
          multicámara, VJ, mapping, iluminación y operación técnica se cotizan por proyecto.
        </p>
        <div className="mt-6 flex flex-wrap gap-3">
          <ButtonLink href={contact.whatsappUrl} target="_blank" rel="noopener noreferrer">Cotiza por WhatsApp</ButtonLink>
          <ButtonLink href={`mailto:${contact.email}`} variant="ghost">{contact.email}</ButtonLink>
        </div>
      </section>
    </Container>
  );
}
