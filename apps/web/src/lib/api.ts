// Cliente de la API de FADEX. El access token vive SOLO en memoria (nunca en localStorage);
// la sesión se mantiene con la cookie httpOnly de refresh, que el navegador manda a /api/auth.

let accessToken: string | null = null;
let refreshing: Promise<string | null> | null = null;

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function parseError(res: Response): Promise<ApiError> {
  let message = "Algo salió mal. Intenta de nuevo.";
  try {
    const body = await res.json();
    if (typeof body.detail === "string") message = body.detail;
    else if (Array.isArray(body.detail) && body.detail[0]?.msg) {
      message = String(body.detail[0].msg).replace(/^Value error, /, "");
    }
  } catch { /* respuesta sin JSON */ }
  if (res.status === 429) message = "Demasiados intentos. Espera un momento.";
  return new ApiError(res.status, message);
}

export function setAccessToken(token: string | null) {
  accessToken = token;
}

/** Renueva el access token con la cookie de refresh. Una sola petición aunque la pidan varios. */
export function refreshAccess(): Promise<string | null> {
  refreshing ??= fetch("/api/auth/refresh", {
    method: "POST",
    credentials: "same-origin",
    headers: { "x-fadex-csrf": "1" },
  })
    .then(async (res) => (res.ok ? ((await res.json()).access_token as string) : null))
    .catch(() => null)
    .then((token) => {
      accessToken = token;
      return token;
    })
    .finally(() => {
      refreshing = null;
    });
  return refreshing;
}

/** Respuesta cruda de la API, con Bearer y un reintento tras renovar si el token venció. */
async function request(path: string, init: RequestInit & { json?: unknown } = {}): Promise<Response> {
  const { json, headers, ...rest } = init;
  const doFetch = () =>
    fetch(`/api${path}`, {
      credentials: "same-origin",
      ...rest,
      headers: {
        ...(json !== undefined && { "content-type": "application/json" }),
        ...(accessToken && { authorization: `Bearer ${accessToken}` }),
        "x-fadex-csrf": "1",
        ...headers,
      },
      body: json !== undefined ? JSON.stringify(json) : rest.body,
    });

  let res = await doFetch();
  if (res.status === 401 && accessToken && !path.startsWith("/auth/login")) {
    if (await refreshAccess()) res = await doFetch();
  }
  if (!res.ok) throw await parseError(res);
  return res;
}

/** fetch a la API con JSON. */
export async function api<T>(path: string, init: RequestInit & { json?: unknown } = {}): Promise<T> {
  const res = await request(path, init);
  return (res.status === 204 ? undefined : await res.json()) as T;
}

/** Descarga un archivo protegido (el token va en un header, así que no sirve un enlace directo)
 *  y lo guarda con el nombre indicado. */
export async function downloadFile(path: string, filename: string): Promise<void> {
  const blob = await (await request(path)).blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

// ---------- tipos de la API ----------

export type User = {
  id: string;
  email: string;
  display_name: string;
  role: "user" | "creator" | "admin";
  email_verified: boolean;
  whatsapp: string | null;
  profile_complete: boolean;
  has_password: boolean;
  google_linked: boolean;
  beta: boolean;
  beta_seat: number | null;
  created_at: string;
};

export type BetaStatus = { seats: number; taken: number; available: number };

export type Session = {
  id: string;
  created_at: string;
  last_used_at: string;
  user_agent: string;
  ip: string;
  current: boolean;
};

export type Message = { detail: string };

// ---------- herramientas de la beta ----------

export type ToolName = "tracklist" | "library_upgrade";
export type JobStatus = "uploading" | "queued" | "running" | "done" | "failed" | "expired";

export type ToolLimits = { max_bytes: number; per_day: number; extensions: string[] };
export type ToolsInfo = {
  chunk_size: number;
  result_days: number;
  tracklist: ToolLimits;
  library_upgrade: ToolLimits;
  library_max_files: number;
  formats: string[];
};

export type UploadState = { upload_id: string; chunk_size: number; total_parts: number; received_parts: number };

export type Job = {
  id: string;
  tool: ToolName;
  status: JobStatus;
  input_name: string;
  input_bytes: number;
  options: { formato?: string };
  progress: number;
  message: string;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  expires_at: string | null;
  summary: Record<string, unknown> | null;
  files: string[];
  drive_url: string | null;
};

export type JobPage = { items: Job[]; total: number };
