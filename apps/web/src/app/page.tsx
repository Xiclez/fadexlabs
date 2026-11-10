import Link from "next/link";

import { ButtonLink, Container, CutCard, DisplayTitle, Label, LogoTile, PanelCard, SectionHeader } from "@/components/ui";
import { contact, method, pillars, serviceGroups, storeCategories, tools } from "@/content/site";

const featured = ["dj-sets", "press-kit", "foto-video", "marketing", "community", "ecommerce"];

export default function Home() {
  return (
    <>
      {/* ---------- Hero ---------- */}
      <section className="relative overflow-hidden">
        <div className="pointer-events-none absolute -top-40 left-1/2 h-[520px] w-[900px] -translate-x-1/2 rounded-full bg-violet/20 blur-[120px]" aria-hidden />
        <Container className="relative grid items-center gap-12 py-16 sm:py-24 lg:grid-cols-[1.25fr_1fr]">
          <div>
            <Label>Independent audiovisual & technology studio</Label>
            <DisplayTitle as="h1" solid="FADEX" outline="LABS" className="mt-5 text-6xl sm:text-8xl" />
            <p className="mt-6 max-w-xl text-xl text-muted sm:text-2xl">
              Diseñamos experiencias. Construimos sistemas. Producimos contenido.
            </p>
            <p className="fx-label mt-6 text-dim">Estrategia / Contenido / Show / Tecnología</p>
            <div className="mt-9 flex flex-wrap gap-3">
              <ButtonLink href="/servicios">Ver servicios</ButtonLink>
              <ButtonLink href={contact.whatsappUrl} variant="ghost" target="_blank" rel="noopener noreferrer">
                Cotiza por WhatsApp
              </ButtonLink>
            </div>
          </div>
          <div className="flex justify-center lg:justify-end">
            <LogoTile size={320} />
          </div>
        </Container>
        <Container>
          <dl className="grid border border-line bg-panel/80 text-sm sm:grid-cols-3">
            {[["Base operativa", contact.base], ["Áreas", "Live / Studio / Digital"], ["Contacto", contact.email]].map(([k, v]) => (
              <div key={k} className="border-line px-5 py-4 [&:not(:last-child)]:border-b sm:[&:not(:last-child)]:border-b-0 sm:[&:not(:last-child)]:border-r">
                <dt className="fx-label text-dim">{k}</dt>
                <dd className="mt-1 text-text">{v}</dd>
              </div>
            ))}
          </dl>
        </Container>
      </section>

      {/* ---------- Qué es ---------- */}
      <Container className="py-24">
        <SectionHeader label="01 / Identidad" solid="Un laboratorio" outline="audiovisual"
          text="No trabajamos únicamente como proveedor de equipo o como productora de video. Diseñamos el sistema completo: concepto, captura, señal, procesamiento, sincronía, puesta en escena y entrega final." />
        <div className="grid gap-4 sm:grid-cols-2">
          {pillars.map((p) => <PanelCard key={p.title} {...p} />)}
        </div>
      </Container>

      {/* ---------- Servicios destacados ---------- */}
      <section className="border-y border-line bg-panel/40 py-24">
        <Container>
          <SectionHeader label="02 / Servicios" solid="Qué" outline="hacemos"
            text="Para artistas, promotores, venues, marcas, colectivos y proyectos culturales." />
          <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
            {serviceGroups.filter((g) => featured.includes(g.id)).map((g) => {
              const from = g.plans.find((p) => p.price.includes("$"));
              return (
                <Link key={g.id} href={`/servicios#${g.id}`} className="group">
                  <CutCard className="h-full transition group-hover:fx-glow" innerClassName="flex h-full flex-col">
                    <p className="fx-label text-violet">{g.label}</p>
                    <h3 className="mt-3 font-display text-xl font-bold uppercase">
                      {g.title} <span className="fx-gradient-text">{g.outline}</span>
                    </h3>
                    <p className="mt-3 text-sm text-muted">{g.tagline}</p>
                    <p className="mt-auto flex items-center justify-between pt-6">
                      <span className="fx-label text-dim">
                        {from ? <>Desde <span className="text-cyan">{from.price.replace("Desde ", "")} {from.unit}</span></> : "Cotización a medida"}
                      </span>
                      <span aria-hidden className="text-cyan transition group-hover:translate-x-1">→</span>
                    </p>
                  </CutCard>
                </Link>
              );
            })}
          </div>
          <div className="mt-10"><ButtonLink href="/servicios" variant="ghost">Catálogo completo</ButtonLink></div>
        </Container>
      </section>

      {/* ---------- Herramientas ---------- */}
      <Container className="py-24">
        <SectionHeader label="Hecho en el lab" solid="Herramientas" outline="para DJs"
          text="Software propio que nace de la cabina: identificar tus sets y cuidar tu librería." />
        <div className="grid gap-5 md:grid-cols-2">
          {tools.map((t) => (
            <CutCard key={t.slug} innerClassName="flex h-full flex-col">
              <div className="flex items-center justify-between">
                <p className="fx-label text-lime">{t.status}</p>
                <p className="fx-label text-dim">FADEX / tools</p>
              </div>
              <h3 className="mt-4 font-display text-2xl font-bold uppercase">{t.name}</h3>
              <p className="mt-1 text-cyan">{t.tagline}</p>
              <p className="mt-4 text-sm leading-relaxed text-muted">{t.text}</p>
              <ul className="mt-5 grid gap-2 text-sm sm:grid-cols-2">
                {t.points.map((p) => (
                  <li key={p} className="flex gap-2"><span className="text-magenta">▸</span>{p}</li>
                ))}
              </ul>
              <Link href={`/herramientas#${t.slug}`} className="fx-label mt-auto pt-6 text-cyan hover:text-white">Más info →</Link>
            </CutCard>
          ))}
        </div>
      </Container>

      {/* ---------- Tienda ---------- */}
      <section className="border-y border-line bg-panel/40 py-24">
        <Container>
          <SectionHeader label="Tienda · próximamente" solid="Recursos" outline="para la escena"
            text="Contenido descargable para DJs, VJs y LJs, entregado de forma segura desde tu cuenta." />
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {storeCategories.map((c) => <PanelCard key={c.title} {...c} />)}
          </div>
        </Container>
      </section>

      {/* ---------- Método ---------- */}
      <Container className="py-24">
        <SectionHeader label="04 / Método de producción" solid="Del concepto" outline="a la entrega"
          text="Planeación creativa y validación técnica para reducir la improvisación durante el evento o rodaje." />
        <ol className="grid gap-px overflow-hidden border border-line bg-line sm:grid-cols-2 lg:grid-cols-3">
          {method.map((m) => (
            <li key={m.n} className="bg-ink p-6">
              <p className="font-display text-3xl font-bold text-violet/70">{m.n}</p>
              <p className="fx-label mt-3 text-cyan">{m.stage}</p>
              <p className="mt-2 text-sm text-muted">{m.text}</p>
            </li>
          ))}
        </ol>
      </Container>

      {/* ---------- CTA ---------- */}
      <Container>
        <CutCard className="fx-glow" innerClassName="flex flex-col items-start gap-6 p-8 sm:p-12 md:flex-row md:items-center md:justify-between">
          <div>
            <Label>09 / Colaboraciones</Label>
            <h2 className="mt-3 font-display text-3xl font-bold uppercase sm:text-4xl">
              Diseñemos el <span className="fx-gradient-text">siguiente sistema</span>
            </h2>
            <p className="mt-3 max-w-xl text-muted">Desde una tarea puntual hasta la producción técnica y creativa de un proyecto completo.</p>
          </div>
          <div className="flex flex-wrap gap-3">
            <ButtonLink href={contact.whatsappUrl} target="_blank" rel="noopener noreferrer">Mándanos mensaje</ButtonLink>
            <ButtonLink href={`mailto:${contact.email}`} variant="ghost">{contact.email}</ButtonLink>
          </div>
        </CutCard>
      </Container>
    </>
  );
}
