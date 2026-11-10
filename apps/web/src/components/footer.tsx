import Link from "next/link";

import { Container, FlaskMark } from "@/components/ui";
import { contact } from "@/content/site";

export function Footer() {
  return (
    <footer className="mt-24 border-t border-line">
      <Container className="grid gap-10 py-12 md:grid-cols-[1.4fr_1fr_1fr]">
        <div>
          <div className="flex items-center gap-3">
            <FlaskMark className="h-10 w-10" />
            <div>
              <p className="font-display text-lg font-bold tracking-wide">FADEX LABS</p>
              <p className="fx-label text-cyan">Audiovisual systems / creative technology</p>
            </div>
          </div>
          <p className="mt-5 max-w-sm text-sm text-muted">
            Donde el audio, la imagen y la tecnología se encuentran. Producción audiovisual · DJ / VJ · DMX · LED · Mapping · Software.
          </p>
        </div>

        <div>
          <p className="fx-label mb-4 text-dim">Explorar</p>
          <ul className="space-y-2 text-sm">
            {[["/servicios", "Servicios"], ["/portafolio", "Portafolio"], ["/herramientas", "Herramientas para DJs"], ["/tienda", "Tienda"]].map(([href, label]) => (
              <li key={href}><Link href={href} className="text-muted hover:text-white">{label}</Link></li>
            ))}
          </ul>
        </div>

        <div>
          <p className="fx-label mb-4 text-dim">Contacto</p>
          <ul className="space-y-2 text-sm">
            <li><a href={`mailto:${contact.email}`} className="text-muted hover:text-white">{contact.email}</a></li>
            <li><a href={contact.whatsappUrl} target="_blank" rel="noopener noreferrer" className="text-muted hover:text-white">WhatsApp {contact.whatsapp}</a></li>
            <li><a href={contact.instagramUrl} target="_blank" rel="noopener noreferrer" className="text-muted hover:text-white">Instagram {contact.instagram}</a></li>
            <li className="text-dim">{contact.base}</li>
          </ul>
        </div>
      </Container>
      <div className="border-t border-line/60">
        <Container className="flex flex-col justify-between gap-2 py-5 sm:flex-row">
          <p className="fx-label text-dim">Tu marca, en movimiento.</p>
          <p className="fx-label text-dim">FADEX Labs · Chihuahua, México · 2026</p>
        </Container>
      </div>
    </footer>
  );
}
