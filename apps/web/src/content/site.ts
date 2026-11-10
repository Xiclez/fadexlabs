// Contenido de FADEX Labs, transcrito del dossier técnico 2026 y los catálogos.
// Precios de referencia en MXN: el dossier pide confirmarlos antes de publicarlos como vigentes.

export const contact = {
  email: "contact@fadexlabs.com",
  whatsapp: "614 115 1657",
  whatsappUrl: "https://wa.me/526141151657",
  instagram: "@fadex.labs",
  instagramUrl: "https://instagram.com/fadex.labs",
  base: "Chihuahua, México",
};

export type Accent = "magenta" | "violet" | "cyan" | "lime";

export const accentBorder: Record<Accent, string> = {
  magenta: "border-l-magenta",
  violet: "border-l-violet",
  cyan: "border-l-cyan",
  lime: "border-l-lime",
};

export const pillars: { title: string; text: string; accent: Accent }[] = [
  { title: "Creative Production", accent: "magenta",
    text: "Conceptualización, dirección visual, fotografía, video, edición, aftermovies, reels y piezas promocionales." },
  { title: "Live Audiovisual", accent: "cyan",
    text: "DJ sets, VJ, visuales en tiempo real, mapping, integración de cámaras, iluminación y operación de show." },
  { title: "Technical Lab", accent: "violet",
    text: "Integración de hardware y software, protocolos de señal, automatización, streaming, redes y prototipos." },
  { title: "Digital Systems", accent: "lime",
    text: "Landing pages, EPK, herramientas web, chatbots, automatización y soluciones digitales para proyectos creativos." },
];

export const method = [
  { n: "01", stage: "Brief", text: "Objetivo, audiencia, formato, referencias, locación, presupuesto y entregables." },
  { n: "02", stage: "Diseño", text: "Concepto visual, shot list, layout de pantallas, rider, diagrama de señal y plan operativo." },
  { n: "03", stage: "Preproducción", text: "Pruebas de cámara, audio, codecs, conexiones, alimentación, red, DMX y compatibilidad." },
  { n: "04", stage: "Ejecución", text: "Captura, dirección, operación de cámara, DJ/VJ, iluminación y supervisión técnica." },
  { n: "05", stage: "Postproducción", text: "Edición, color, mezcla, sincronía, versiones vertical/horizontal y exportación." },
  { n: "06", stage: "Entrega", text: "Organización de archivos, masters, formatos para redes, respaldo y cierre de proyecto." },
];

// ---------- Catálogo de servicios ----------

export type Plan = {
  name: string;
  subtitle?: string;
  price: string;      // ya formateado: "$500"
  unit?: string;      // "MXN / hora"
  features: string[];
  idealFor?: string;
  highlight?: boolean;
};

export type ServiceGroup = {
  id: string;
  label: string;      // etiqueta mono
  title: string;
  outline: string;    // segunda línea en contorno
  tagline: string;
  intro?: string;
  plans: Plan[];
  extras?: string[];
  notes?: string[];
};

export const serviceGroups: ServiceGroup[] = [
  {
    id: "dj-sets",
    label: "Producción audiovisual para DJ sets",
    title: "DJ Set",
    outline: "Recording",
    tagline: "Transformamos tu set en contenido que trasciende.",
    intro: "Todos los paquetes incluyen grabación de audio por interfaz desde REC OUT o MASTER 2 (mejor calidad, sin ocupar un puerto USB en equipos all-in-one), edición y entrega digital lista para publicar.",
    plans: [
      { name: "Paquete 1", subtitle: "Basic Setup", price: "$500", unit: "MXN / hora",
        features: ["1 cámara fija booth 1080p", "1 cámara dinámica dance floor 1080p"],
        idealFor: "DJs emergentes, promocionales simples y contenido para redes (IG, TikTok, Reels)." },
      { name: "Paquete 2", subtitle: "Multicam Experience", price: "$1,000", unit: "MXN / hora", highlight: true,
        features: ["1 cámara fija booth 4K", "1 cámara dinámica dance floor 1080p", "2 cámaras 1080p en ubicaciones estratégicas"],
        idealFor: "DJ sets profesionales, clubs y eventos medianos. Contenido cinematográfico para YouTube." },
      { name: "Paquete 3", subtitle: "Cinematic Performance", price: "$1,500", unit: "MXN / hora",
        features: ["1 cámara fija booth 4K", "1 cámara POV DJ 4K", "1 cámara dinámica dance floor 4K",
          "3 cámaras 1080p en ubicaciones estratégicas", "Tomas aéreas con dron 1080p"],
        idealFor: "Eventos grandes, producciones premium, aftermovies y sets de alto impacto visual." },
    ],
    extras: ["Fotografía del evento", "Reels verticales", "Tomas extra con dron", "Cobertura backstage",
      "Visuales para VJ", "Edición express", "Miniaturas para YouTube"],
    notes: ["Precios sujetos a ubicación y duración del evento.", "Eventos fuera de la ciudad pueden generar costo adicional.",
      "El uso de dron depende de condiciones climáticas y restricciones del lugar.", "Se requiere anticipo para apartar fecha."],
  },
  {
    id: "foto-video",
    label: "Catálogo",
    title: "Fotografía",
    outline: "y Video",
    tagline: "Ideas visuales que se hacen realidad.",
    plans: [
      { name: "Sesión en locación", price: "$1,000", unit: "MXN / hora",
        features: ["Sin límite de fotografías", "Fotografías procesadas y editadas"] },
      { name: "Sesión en estudio", price: "$2,000", unit: "MXN / hora",
        features: ["Sin límite de fotografías", "Fotografías procesadas y editadas"] },
      { name: "Sesión en cualquier lugar", price: "$1,000", unit: "MXN / hora",
        features: ["Tú eliges el lugar, nosotros nos adaptamos", "Fotografías procesadas y editadas"] },
      { name: "Video con cámara", price: "$1,500", unit: "MXN / hora", highlight: true,
        features: ["Máx. 1 hora de grabación", "Video editado", "Incluye tomas aéreas con dron (sujeto a clima e iluminación)"] },
      { name: "Tomas 360°", subtitle: "Servicio adicional", price: "+$500", unit: "MXN / hora",
        features: ["Complemento a una producción de video"] },
    ],
    notes: ["Grabación de eventos, conciertos y festivales se cotiza por separado."],
  },
  {
    id: "press-kit",
    label: "Press kits para artistas",
    title: "Press Kit",
    outline: "para DJs",
    tagline: "Tu música ya tiene personalidad. Que tu presencia digital también.",
    intro: "Linktree no está mal… hasta que el promoter pasa de largo. Un sitio propio con tus mixes, fotos, rider y media kit.",
    plans: [
      { name: "Paquete 1", price: "Cotizar", features: ["Sitio profesional", "Mixes + enlaces", "Galería de fotos"] },
      { name: "Paquete 2", price: "Cotizar", highlight: true,
        features: ["Todo lo del paquete 1", "Diseño personalizado", "Splash screen", "Galería por evento",
          "Media kit bilingüe", "Technical rider"] },
      { name: "Paquete 3", price: "Cotizar",
        features: ["Todo lo del paquete 2", "Reproductor integrado", "Experiencia 3D", "Dossier ejecutivo", "Playground visual"] },
    ],
    notes: ["Solicita tu demo sin compromiso."],
  },
  {
    id: "marketing",
    label: "Crea · Conecta · Convierte",
    title: "Marketing",
    outline: "Digital",
    tagline: "Contenido individual o en paquete.",
    plans: [
      { name: "Reel", subtitle: "~30 seg", price: "$300", unit: "MXN", features: ["Video vertical editado"] },
      { name: "Formato largo", subtitle: "+2 min", price: "Desde $500", unit: "MXN", features: ["Precio según duración"] },
      { name: "Post", subtitle: "Orgánico / IA", price: "$150", unit: "MXN", features: ["Pieza gráfica para feed"] },
      { name: "Carrusel", price: "$200", unit: "MXN", features: ["Serie de imágenes"] },
      { name: "Starter", price: "$500", unit: "MXN", features: ["2 reels + 2 posts"] },
      { name: "Growth", price: "$700", unit: "MXN", highlight: true, features: ["3 reels + 4 posts"] },
      { name: "Full", price: "$1,000", unit: "MXN", features: ["4 reels + 8 posts"] },
    ],
  },
  {
    id: "community",
    label: "Gestión · Comunidad · Crecimiento",
    title: "Community",
    outline: "Management",
    tagline: "Tu marca también es una comunidad.",
    intro: "Incluye business & data analytics y gestión de Meta Ads, Google Ads y TikTok Ads.",
    plans: [
      { name: "Plan 01", price: "$2,000", unit: "MXN / mes", features: ["1 post diario", "2 reels por semana"] },
      { name: "Plan 02", price: "$4,000", unit: "MXN / mes", highlight: true, features: ["2 posts diarios", "3 reels por semana"] },
      { name: "Plan 03", price: "$8,000", unit: "MXN / mes", features: ["3 posts diarios", "5 reels por semana"] },
    ],
    notes: ["Presupuesto de anuncios no incluido."],
  },
  {
    id: "ecommerce",
    label: "E-commerce automation",
    title: "Ecommerce",
    outline: "Integration",
    tagline: "Automatiza e integra tu tienda online con un sistema de ventas completo, optimizado para escalar.",
    plans: [
      { name: "Automated Ecommerce", subtitle: "Ads + sales funnel", price: "$9,000", unit: "MXN / mes", highlight: true,
        features: ["Shopify, WooCommerce o PrestaShop", "Traffic → Funnel → Store → Sale → Data"] },
    ],
  },
  {
    id: "impresiones",
    label: "Tu marca · Tu evento · Tu estilo",
    title: "Impresiones",
    outline: "para DJs",
    tagline: "¡Lleva tu música más lejos!",
    plans: [
      { name: "Stickers", price: "Cotizar", features: ["Personalizados de alta calidad"] },
      { name: "Lonas", price: "Cotizar", features: ["Con estructura, resistentes y llamativas"] },
      { name: "Tarjetas", price: "Cotizar", features: ["Tu imagen siempre presente"] },
      { name: "Pulseras", price: "Cotizar", features: ["Ideales para tus shows y eventos"] },
    ],
    extras: ["Flyers", "Posters", "Banners", "Calcomanías", "Vinil", "Stands"],
  },
  {
    id: "software",
    label: "DXZ Software",
    title: "Software",
    outline: "& Web",
    tagline: "Landing pages, EPK, formularios y experiencias digitales con estética audiovisual.",
    plans: [
      { name: "Landing page", price: "$1,000", unit: "MXN", features: ["Desarrollo inicial de página de aterrizaje"] },
      { name: "Soporte / hosting", price: "$350", unit: "MXN / mes", features: ["Soporte y alojamiento, sujeto a alcance"] },
    ],
  },
];

// ---------- Herramientas para DJs (productos propios) ----------

export const tools = [
  {
    slug: "tracklist-id",
    name: "Tracklist ID",
    tagline: "Tu set, identificado tema por tema.",
    text: "Sube un DJ set de 2+ horas y recibe el tracklist con timestamps. Combina varios motores de reconocimiento, descarta los mixes de otros DJs que aparecen como resultado y marca lo que no se pudo identificar.",
    points: ["Timestamps H:MM:SS por track", "Varios motores de reconocimiento", "Exporta TXT y CSV", "Marca los tramos ID - ID"],
    status: "Beta cerrada",
  },
  {
    slug: "dj-library-upgrader",
    name: "DJ Library Upgrader",
    tagline: "Tu librería, en la calidad que tu cabina merece.",
    text: "Herramienta para mejorar la calidad de tu propia librería a partir de fuentes que tienes derecho a usar: sube tu librería en un .zip, elige formato (AIFF, WAV, FLAC, ALAC/M4A o MP3 320) y recíbela por Google Drive con tags y carátula para Rekordbox y un informe por pista.",
    points: ["Salida AIFF / WAV / FLAC / M4A / MP3", "Solo la misma grabación: se compara con tu original", "Sin falso lossless: nunca convierte MP3 → FLAC", "Entrega por Google Drive + informe por pista"],
    status: "Beta cerrada",
  },
];

// ---------- Tienda (fase siguiente) ----------

export const storeCategories = [
  { title: "Loops visuales", text: "Packs de loops para VJ y pantallas LED, listos para Resolume.", accent: "magenta" as Accent },
  { title: "Librerías de iluminación", text: "Escenas, chases y perfiles DMX para tus fixtures.", accent: "cyan" as Accent },
  { title: "Guías PDF", text: "Ruteo de señal, captura de sets, DMX, mapping y más.", accent: "violet" as Accent },
  { title: "Cursos", text: "Formación para DJ, VJ y LJ, de la cabina a la operación de show.", accent: "lime" as Accent },
];

// ---------- Portafolio ----------

export const projects = [
  { title: "FADEX Home Sesh × SAHE", kind: "Sesión audiovisual", tags: ["Psytrance", "YouTube", "Live content"],
    text: "Formato propio de sesiones audiovisuales con audio directo de cabina, imagen y edición. Estrenado con SAHE." },
  { title: "Sick Minds", kind: "Paquete integral", tags: ["Sets", "Dron", "Aftermovie", "Merch"],
    text: "Producción de contenido con sets, clips de dron, reels, aftermovie, álbum y piezas de merch." },
  { title: "Aftermovies de evento", kind: "Postproducción", tags: ["Branding", "Créditos", "Patrocinadores"],
    text: "Identidad de marca, composición de créditos, integración de patrocinadores y piezas de evento." },
  { title: "Press kits para DJs", kind: "Digital", tags: ["DAXIKLEZ", "Rey Calaca", "De La Reiver"],
    text: "Sitios de artista con mixes, galerías, rider técnico y media kit bilingüe." },
  { title: "Visuales y DMX en vivo", kind: "Live audiovisual", tags: ["Resolume", "FreeStyler", "LED"],
    text: "Composición en Resolume, programación de escenas DMX y contenido mapeado a pantallas LED." },
  { title: "Artistas y venues", kind: "Contenido", tags: ["Fotografía", "Flyers", "Cobertura"],
    text: "Fotografía, flyers, cobertura de fechas, sesiones y material promocional." },
];
