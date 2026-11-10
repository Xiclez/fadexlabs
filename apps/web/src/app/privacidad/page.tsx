import type { Metadata } from "next";

import { Container, Label } from "@/components/ui";
import { contact } from "@/content/site";

export const metadata: Metadata = { title: "Aviso de privacidad" };

// BORRADOR: debe revisarlo un abogado antes de publicarse (LFPDPPP, México).
// Faltan: nombre o razón social del responsable y domicilio completo.
export default function PrivacidadPage() {
  return (
    <Container className="max-w-3xl py-16">
      <Label>Borrador · pendiente de revisión legal</Label>
      <h1 className="mt-4 font-display text-4xl font-bold uppercase">Aviso de privacidad</h1>
      <div className="mt-8 space-y-6 leading-relaxed text-muted [&_h2]:font-display [&_h2]:text-lg [&_h2]:font-semibold [&_h2]:uppercase [&_h2]:text-text">
        <p>
          FADEX Labs, con base en {contact.base}, es responsable del tratamiento de tus datos personales
          conforme a la Ley Federal de Protección de Datos Personales en Posesión de los Particulares.
        </p>
        <h2>Datos que recabamos</h2>
        <p>Nombre o nombre artístico, correo electrónico, número de WhatsApp y, si inicias sesión con Google, el
          identificador de tu cuenta de Google. No recabamos datos sensibles.</p>
        <h2>Para qué los usamos</h2>
        <p>Crear y proteger tu cuenta, darte acceso a compras, descargas y herramientas (incluida la beta cerrada),
          darte soporte y enviarte avisos sobre tu cuenta. No vendemos ni compartimos tus datos con terceros para
          publicidad.</p>
        <h2>Tus derechos (ARCO)</h2>
        <p>Puedes acceder, rectificar, cancelar u oponerte al uso de tus datos, o revocar tu consentimiento,
          escribiendo a <a href={`mailto:${contact.email}`} className="text-cyan">{contact.email}</a>.</p>
        <h2>Cambios</h2>
        <p>Cualquier cambio a este aviso se publicará en esta página.</p>
      </div>
    </Container>
  );
}
