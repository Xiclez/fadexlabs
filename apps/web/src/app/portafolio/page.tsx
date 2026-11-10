import type { Metadata } from "next";

import { ButtonLink, Container, CutCard, DisplayTitle, Label, Pill } from "@/components/ui";
import { contact, projects } from "@/content/site";

export const metadata: Metadata = {
  title: "Portafolio",
  description: "Sesiones audiovisuales, aftermovies, press kits, visuales y DMX en vivo.",
};

const tints = ["from-magenta/40", "from-violet/40", "from-cyan/35", "from-lime/25", "from-magenta/30", "from-cyan/30"];

export default function PortafolioPage() {
  return (
    <Container className="py-16">
      <Label>Experiencia y formatos trabajados</Label>
      <DisplayTitle as="h1" solid="Portafolio" outline="Lab work" className="mt-4 text-5xl sm:text-7xl" />
      <p className="mt-6 max-w-2xl text-lg text-muted">
        Proyectos y formatos en los que hemos trabajado: sesiones, aftermovies, sitios de artista y operación en vivo.
      </p>

      <div className="mt-12 grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
        {projects.map((p, i) => (
          <CutCard key={p.title} innerClassName="flex h-full flex-col p-0">
            {/* Espacio para la portada del proyecto (imagen o video) */}
            <div className={`relative aspect-video bg-linear-to-br ${tints[i % tints.length]} to-transparent`}>
              <span className="fx-label absolute bottom-3 left-4 text-white/80">{p.kind}</span>
              <span className="absolute right-4 top-3 font-display text-2xl font-bold text-white/25">{String(i + 1).padStart(2, "0")}</span>
            </div>
            <div className="flex flex-1 flex-col p-6">
              <h2 className="font-display text-lg font-bold uppercase">{p.title}</h2>
              <p className="mt-3 text-sm text-muted">{p.text}</p>
              <div className="mt-auto flex flex-wrap gap-2 pt-5">{p.tags.map((t) => <Pill key={t}>{t}</Pill>)}</div>
            </div>
          </CutCard>
        ))}
      </div>

      <div className="mt-16 flex flex-wrap items-center gap-4">
        <p className="text-muted">¿Quieres ver tu proyecto aquí?</p>
        <ButtonLink href={contact.whatsappUrl} target="_blank" rel="noopener noreferrer">Solicita tu demo</ButtonLink>
      </div>
    </Container>
  );
}
