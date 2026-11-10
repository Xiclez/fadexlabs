import type { Metadata } from "next";

import { BetaCounter } from "@/components/beta-counter";
import { ToolAccess } from "@/components/tool-access";
import { Container, CutCard, DisplayTitle, Label } from "@/components/ui";
import { tools } from "@/content/site";

export const metadata: Metadata = {
  title: "Herramientas para DJs",
  description: "Tracklist ID y DJ Library Upgrader: software de FADEX Labs para DJs.",
};

export default function HerramientasPage() {
  return (
    <Container className="py-16">
      <Label>Hecho en el lab</Label>
      <DisplayTitle as="h1" solid="Herramientas" outline="para DJs" className="mt-4 text-5xl sm:text-7xl" />
      <p className="mt-6 max-w-2xl text-lg text-muted">
        Software que nace de la cabina. Están en beta cerrada: solo las primeras cuentas registradas tienen acceso.
      </p>

      <div className="mt-8 max-w-xl"><BetaCounter /></div>

      <div className="mt-12 space-y-8">
        {tools.map((t) => (
          <section key={t.slug} id={t.slug} className="scroll-mt-24">
            <CutCard innerClassName="grid gap-8 p-8 lg:grid-cols-[1.2fr_1fr]">
              <div>
                <p className="fx-label text-lime">{t.status}</p>
                <h2 className="mt-3 font-display text-3xl font-bold uppercase sm:text-4xl">{t.name}</h2>
                <p className="mt-2 text-lg text-cyan">{t.tagline}</p>
                <p className="mt-5 leading-relaxed text-muted">{t.text}</p>
                <div className="mt-8"><ToolAccess slug={t.slug} name={t.name} /></div>
              </div>
              <ul className="grid content-start gap-3">
                {t.points.map((p) => (
                  <li key={p} className="fx-panel border-l-violet px-4 py-3 text-sm">{p}</li>
                ))}
              </ul>
            </CutCard>
          </section>
        ))}
      </div>

      <p className="mt-10 max-w-3xl text-xs text-dim">
        DJ Library Upgrader trabaja sobre fuentes que tienes derecho a usar. FADEX Labs no vende ni distribuye música de terceros.
      </p>
    </Container>
  );
}
