import type { Metadata } from "next";
import { Suspense } from "react";

import { JobDetail } from "@/components/job-views";
import { Container } from "@/components/ui";

export const metadata: Metadata = { title: "Trabajo", robots: { index: false } };

// Con cacheComponents el id de la ruta es un dato de ejecución: se lee dentro de <Suspense>
// para que el resto de la página siga siendo estática.
export default function TrabajoPage({ params }: PageProps<"/herramientas/trabajos/[id]">) {
  return (
    <Suspense fallback={<Container className="py-24"><p className="text-muted">Cargando…</p></Container>}>
      {params.then(({ id }) => <JobDetail id={id} />)}
    </Suspense>
  );
}
