"use client";

import { ToolGate } from "@/components/tool-gate";
import { ToolUpload } from "@/components/tool-upload";
import { Container, DisplayTitle, Label } from "@/components/ui";

const FORMATS = [
  { value: "aiff", label: "AIFF", hint: "sin pérdida · el que mejor leen Rekordbox y los CDJ" },
  { value: "wav", label: "WAV", hint: "sin pérdida" },
  { value: "flac", label: "FLAC", hint: "sin pérdida · ocupa menos" },
  { value: "alac", label: "ALAC (.m4a)", hint: "sin pérdida · ecosistema Apple" },
  { value: "mp3", label: "MP3 320", hint: "con pérdida · máxima compatibilidad" },
  { value: "m4a", label: "AAC 256 (.m4a)", hint: "con pérdida" },
  { value: "original", label: "Lo encontrado", hint: "MP3 320 o FLAC, sin convertir" },
];

function Steps({ items }: { items: string[] }) {
  return (
    <ol className="grid content-start gap-3">
      {items.map((text, i) => (
        <li key={text} className="fx-panel flex gap-4 border-l-violet px-4 py-3 text-sm">
          <span className="fx-label pt-0.5 text-violet">{String(i + 1).padStart(2, "0")}</span>
          <span>{text}</span>
        </li>
      ))}
    </ol>
  );
}

export function TracklistTool() {
  return (
    <ToolGate>
      <Container className="py-16">
        <Label>Tracklist ID · beta cerrada</Label>
        <DisplayTitle as="h1" solid="Tu set," outline="tema por tema" className="mt-4 text-4xl sm:text-6xl" />
        <p className="mt-6 max-w-2xl text-lg text-muted">
          Sube la grabación de tu set y recibe el tracklist con timestamps, listo para pegar en YouTube, SoundCloud o 1001Tracklists.
        </p>
        <div className="mt-10 grid gap-8 lg:grid-cols-[1.3fr_1fr]">
          <ToolUpload tool="tracklist" fileLabel="Grabación del set" submitLabel="Subir y generar tracklist"
            fileHint="WAV, MP3, FLAC, AIFF o M4A; sets de 2 horas o más." />
          <Steps items={[
            "Subes el set. Va por partes: si se corta el internet, continúa donde se quedó.",
            "Lo reconocemos con varios motores a la vez; si uno se satura, el trabajo sigue con los demás. Cada coincidencia lleva su puntuación de confianza y lo no identificado queda como ID - ID.",
            "Te avisamos por email. Un set de 2 horas tarda entre 10 y 40 minutos.",
            "Descargas el tracklist en TXT y CSV. Tu audio se borra al terminar.",
          ]} />
        </div>
      </Container>
    </ToolGate>
  );
}

export function LibraryUpgraderTool() {
  return (
    <ToolGate>
      <Container className="py-16">
        <Label>DJ Library Upgrader · beta cerrada</Label>
        <DisplayTitle as="h1" solid="Tu librería," outline="en mejor calidad" className="mt-4 text-4xl sm:text-6xl" />
        <p className="mt-6 max-w-2xl text-lg text-muted">
          Sube tu librería en un .zip y recíbela en el formato que elijas: cada pista se compara con tu original
          y solo se entrega si es exactamente la misma grabación.
        </p>
        <div className="mt-10 grid gap-8 lg:grid-cols-[1.3fr_1fr]">
          <ToolUpload tool="library_upgrade" fileLabel="Tu librería (.zip)" submitLabel="Subir y mejorar mi librería"
            fileHint="Un .zip con tus pistas (MP3, FLAC, WAV, AIFF o M4A); puede traer subcarpetas."
            extra={(form) => ({ formato: form.get("formato"), accept_rights: form.get("accept_rights") === "on" })}>
            <fieldset>
              <legend className="fx-label text-muted">Formato de entrega</legend>
              <div className="mt-3 grid gap-2 sm:grid-cols-2">
                {FORMATS.map((f, i) => (
                  <label key={f.value} className="flex cursor-pointer items-start gap-3 rounded-md border border-line px-4 py-3 text-sm has-checked:border-violet has-checked:bg-violet/10">
                    <input type="radio" name="formato" value={f.value} defaultChecked={i === 0} className="mt-1 accent-violet" />
                    <span><span className="font-semibold">{f.label}</span><span className="block text-xs text-dim">{f.hint}</span></span>
                  </label>
                ))}
              </div>
            </fieldset>
            <label className="flex items-start gap-3 text-sm text-muted">
              <input type="checkbox" name="accept_rights" required className="mt-1 h-4 w-4 accent-violet" />
              <span>
                Confirmo que tengo derecho a usar la música de esta librería (por ejemplo, pistas que compré) y que
                uso la herramienta para recuperarla en mejor calidad.
              </span>
            </label>
          </ToolUpload>
          <Steps items={[
            "Subes el .zip. Solo se busca lo que se puede mejorar: lo que ya está sin pérdida no se toca.",
            "Buscamos cada pista y comparamos el audio con tu original: remixes, versiones en vivo u otra canción con el mismo nombre se descartan.",
            "Detectamos los falsos lossless (FLAC o WAV hechos desde un MP3) y nunca convertimos MP3 a un formato sin pérdida.",
            "Recibes un enlace de Google Drive con tu librería: mismos nombres y carpetas, tags y carátula para Rekordbox, más un informe por pista.",
            "Si ninguna fuente de una pista está disponible en 10 minutos, queda pendiente en el informe para reintentarla después o con otro formato. Te avisamos por email al terminar.",
          ]} />
        </div>
      </Container>
    </ToolGate>
  );
}
