#!/usr/bin/env python3
# Vendorizado de dj-library-upgrader/upgrader/slskd_fetch.py, con cambios para la plataforma (ver
# services/README.md): tiempo límite por canción, salto a otro candidato cuando la descarga no arranca
# y revisión de descargas durante la búsqueda.
# No lo edites aquí: cambia el original y vuelve a copiarlo (ver services/README.md).
"""
slskd_fetch.py — Busca en Soulseek (vía la API de slskd) las canciones de
tracks.json, elige el mejor archivo según el formato pedido y lo encola en tu instancia.

Formatos (--formato): original (MP3 320 y FLAC de respaldo, sin convertir), aiff, wav, flac,
alac, mp3, m4a (AAC 256). Se busca primero el formato pedido y, si no existe, el mejor
disponible según --preferencia (por defecto: sin pérdida → ALAC → MP3 320). La conversión
se hace al entregar (collect.py), nunca de con pérdida a sin pérdida.

Configuración (variables de entorno):
    SLSKD_URL       p. ej. http://localhost:5030   (por defecto)
    SLSKD_API_KEY   la clave definida en slskd.yml → web.authentication.api_keys

Comandos:
    search   busca las pendientes y encola la mejor opción  (--dry-run para solo mirar)
    sync     revisa las descargas en slskd; si una falla, prueba el siguiente candidato
    run      search + sync en bucle hasta que no quede nada en curso
    report   resumen + no_encontradas.txt para la siguiente vuelta
    reset    vuelve a "pending" las que quedaron como not_found / failed

El progreso se guarda en state.json: puedes cortar con Ctrl+C y retomar.
"""
import argparse
import json
import os
import re
import sys
import time
import unicodedata
import uuid
from urllib.parse import quote

try:
    import requests
except ImportError:
    sys.exit("Falta 'requests':  pip install requests")

import formats as F
from collect import find_local, index_downloads

STATE_FILE = "state.json"
FORMAT_FILE = "formato.json"   # formato pedido para esta lista; lo lee collect.py al entregar
MAX_CANDIDATES = 6   # del formato preferido
MAX_FALLBACK = 4     # de cada formato de respaldo
FAIL_STATES = ("Errored", "Rejected", "TimedOut", "Cancelled", "Failed", "Aborted")


# ───────────────────────── utilidades de texto ─────────────────────────

def fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.replace("'", "").replace("’", "")
    s = re.sub(r"[^a-z0-9]+", " ", s.lower())
    return re.sub(r"\s+", " ", s).strip()


def words(s: str) -> list:
    return fold(s).split()


def has_phrase(hay: str, phrase: str) -> bool:
    p = fold(phrase)
    return bool(p) and re.search(rf"(?:^| ){re.escape(p)}(?: |$)", hay) is not None


STOP = {"the", "a", "an", "of", "and", "y", "el", "la", "de"}


# ───────────────────────── cliente slskd ─────────────────────────

class Slskd:
    def __init__(self, url, api_key, timeout=30):
        self.base = url.rstrip("/") + "/api/v0"
        self.s = requests.Session()
        if api_key:
            self.s.headers["X-API-Key"] = api_key
        self.timeout = timeout

    def _req(self, method, path, **kw):
        r = self.s.request(method, self.base + path, timeout=self.timeout, **kw)
        if r.status_code == 401:
            sys.exit("slskd respondió 401: revisa SLSKD_API_KEY.")
        r.raise_for_status()
        return r.json() if r.content and "json" in r.headers.get("content-type", "") else None

    def search(self, text, search_timeout_ms=15000, max_wait_s=40):
        sid = str(uuid.uuid4())
        self._req("POST", "/searches", json={
            "id": sid,
            "searchText": text,
            "searchTimeout": search_timeout_ms,
            "responseLimit": 200,
            "fileLimit": 20000,
            "filterResponses": True,
            "minimumResponseFileCount": 1,
        })
        t0 = time.time()
        try:
            while time.time() - t0 < max_wait_s:
                time.sleep(1.5)
                st = self._req("GET", f"/searches/{sid}") or {}
                if st.get("isComplete") or str(st.get("state", "")).startswith("Completed"):
                    break
            return self._req("GET", f"/searches/{sid}/responses") or []
        finally:
            try:
                self._req("DELETE", f"/searches/{sid}")
            except Exception:
                pass

    def enqueue(self, username, filename, size):
        self._req("POST", f"/transfers/downloads/{quote(username, safe='')}",
                  json=[{"filename": filename, "size": size}])

    def server_state(self):
        return self._req("GET", "/server") or {}

    def wait_ready(self, max_wait=180):
        """Espera a que slskd responda y esté conectado/logueado en Soulseek."""
        t0, last = time.time(), None
        while time.time() - t0 < max_wait:
            try:
                st = self.server_state()
                state = str(st.get("state", ""))
                if st.get("isLoggedIn") or "LoggedIn" in state:
                    return True
                msg = f"slskd responde, estado Soulseek: {state or 'desconocido'}"
            except requests.RequestException as e:
                msg = f"esperando a slskd ({e.__class__.__name__})"
            if msg != last:
                print("…", msg)
                last = msg
            time.sleep(5)
        print("! slskd no quedó conectado a Soulseek. Revisa usuario/contraseña en slskd.yml "
              "y los logs:  docker compose logs slskd")
        return False

    def downloads(self):
        return self._req("GET", "/transfers/downloads") or []

    def cancel(self, username, transfer_id):
        """Cancela y quita una descarga de la cola de slskd (p. ej. un usuario que nunca la sirve)."""
        self._req("DELETE", f"/transfers/downloads/{quote(username, safe='')}/{transfer_id}", params={"remove": "true"})


# ───────────────────────── evaluación de resultados ─────────────────────────

def effective_bitrate(f):
    br = f.get("bitRate")
    if br:
        return br
    size, length = f.get("size"), f.get("length")
    if size and length:
        return size * 8 / length / 1000
    return None


def score_file(track, resp, f, opts):
    """Devuelve (puntaje, motivo) o (None, motivo_de_descarte)."""
    path = f.get("filename", "")
    base = re.split(r"[\\/]", path)[-1]
    cls = F.classify_remote(f)
    if cls is None or cls not in opts.preference:
        return None, "formato no aceptado"
    if cls == "mp3":
        if f.get("isVariableBitRate"):
            return None, "vbr"
        br = effective_bitrate(f)
        if br is None or br < opts.min_bitrate - 4:
            return None, f"bitrate {br}"
    elif cls == "aac":
        br = effective_bitrate(f)
        if br is None or br < F.MIN_KBPS["aac"] - 4:
            return None, f"bitrate {br}"
    elif (f.get("sampleRate") or 44100) < 44100 or (f.get("bitDepth") or 16) < 16:
        return None, "sin pérdida de baja resolución"  # por debajo de calidad CD

    length = f.get("length")
    # con la librería real conocemos la duración exacta: descarta extended/radio edit/otras versiones
    # sin descargarlas (la comparación de espectrogramas confirma después)
    want = track.get("duration")
    if want and length and abs(length - want) > opts.dur_tol:
        return None, f"duración distinta ({length:.0f}s vs {want:.0f}s)"
    if length and length < 100 and not want:  # con duración conocida, una pista corta es legítima
        return None, "preview/corto"

    fb = fold(re.sub(r"\.(mp3|flac|wav|aiff?|m4a)$", "", base, flags=re.I))
    fp = fold(path)

    # título: todas las palabras significativas deben estar en el nombre del archivo
    tw = [w for w in words(track["title"]) if w not in STOP] or words(track["title"])
    missing = [w for w in tw if not has_phrase(fb, w)]
    if len(missing) > (1 if len(tw) >= 4 else 0):
        return None, f"título no coincide ({missing})"
    score = 50 - 10 * len(missing)

    # el título debe aparecer como frase seguida, no con las palabras sueltas
    # ("Beat On Time" ≠ "axis_of_time-jump_on_the_beat")
    sq = lambda x: re.sub(r"[^a-z0-9]", "", fold(x))
    if sq(track["title"]) and sq(track["title"]) not in sq(fb):
        if not track["artists"]:
            return None, "título no aparece como frase"
        score -= 30

    pw = track.get("partial_word")
    if pw and re.search(rf"(?:^| ){re.escape(fold(pw))}", fb):
        score += 5

    # artista: al menos uno de los artistas debe aparecer en la ruta completa
    if track["artists"]:
        hits = [a for a in track["artists"] if has_phrase(fp, a)]
        if not hits:
            return None, "artista no aparece"
        score += 5 * min(len(hits), 3)

    hint, remixer = track.get("mix_hint"), track.get("remixer")
    title_f = fold(track["title"])

    def present(word):
        return has_phrase(fb, word) and not has_phrase(title_f, word)

    if hint == "remix" and remixer:
        rw = [w for w in words(remixer) if len(w) > 1]
        if rw and not all(has_phrase(fb, w) for w in rw):
            return None, "remixer no coincide"
        score += 25
    elif present("remix") or present("rmx") or present("bootleg") or present("rework"):
        score -= 30  # no pediste remix y este lo es

    for bad in ("acapella", "a cappella", "instrumental", "karaoke", "live", "intro", "clean", "tool"):
        if present(bad) and bad not in fold(track.get("mix") or ""):
            score -= 40

    if hint in ("extended", "original", None):
        if present("extended"):
            score += 15 if hint == "extended" else 5
        if present("original mix"):
            score += 10 if hint in ("extended", "original") else 5
        if present("radio edit") or present("radio") or present("edit"):
            score -= 25 if hint == "extended" else 10
        if hint == "extended" and length and length < 210:
            score -= 20
    elif hint == "radio" and present("radio"):
        score += 10
    elif hint and present(hint):
        score += 10

    # palabras de sobra en el nombre (otra canción, otro artista…)
    expected = set(words(track["title"])) | set(w for a in track["artists"] for w in words(a))
    expected |= set(words(track.get("mix") or "")) | {"mix", "extended", "original", "feat", "ft", "remix"}
    extra = [w for w in fb.split() if w not in expected and not w.isdigit()]
    score -= min(len(extra), 10)

    # calidad del usuario
    if resp.get("hasFreeUploadSlot"):
        score += 10
    score -= min(resp.get("queueLength", 0) or 0, 50) / 5
    score += min((resp.get("uploadSpeed", 0) or 0) / 1_000_000 * 4, 10)

    return score, "ok"


def reason_key(why):
    if why.startswith("bitrate"):
        return f"bitrate menor a {MIN_BR[0]} kbps"
    return {"formato no aceptado": "formato no aceptado (fuera de --preferencia)",
            "vbr": "MP3 VBR (no 320 fijo)",
            "preview/corto": "preview de menos de 100 s"}.get(why, why.split(" (")[0])


MIN_BR = [320]


def rank(track, responses, opts, explain=None):
    MIN_BR[0] = opts.min_bitrate
    cands = []
    for resp in responses:
        for f in resp.get("files", []) or []:
            sc, why = score_file(track, resp, f, opts)
            if explain is not None:
                if sc is None:
                    explain["reasons"][reason_key(why)] += 1
                    # guardar ejemplos relevantes: que al menos contengan el título
                    base = re.split(r"[\\/]", f.get("filename", ""))[-1]
                    tw = [w for w in words(track["title"]) if w not in STOP]
                    if tw and all(has_phrase(fold(base), w) for w in tw) and len(explain["samples"]) < 8:
                        br = effective_bitrate(f)
                        explain["samples"].append(f"{base}  [{int(br) if br else '?'} kbps] → {why}")
                elif sc < opts.min_score:
                    explain["reasons"][f"puntaje menor a {opts.min_score}"] += 1
            if sc is not None and sc >= opts.min_score:
                cands.append({
                    "format": F.classify_remote(f),
                    "score": round(sc, 1),
                    "username": resp.get("username"),
                    "filename": f.get("filename"),
                    "size": f.get("size"),
                    "bitrate": effective_bitrate(f),
                    "length": f.get("length"),
                })
    return order_candidates(cands, opts)


def order_candidates(cands, opts):
    """Ordena por formato preferido y luego por puntaje; limita cuántos guarda por formato."""
    cands = sorted(cands, key=lambda c: c["score"], reverse=True)

    def top(items, n):
        # una sola opción por usuario para tener alternativas reales si alguien falla
        seen, out = set(), []
        for c in items:
            if c["username"] not in seen:
                seen.add(c["username"])
                out.append(c)
            if len(out) >= n:
                break
        return out

    out = []
    for i, cls in enumerate(opts.preference):
        out += top([c for c in cands if c["format"] == cls], MAX_CANDIDATES if i == 0 else MAX_FALLBACK)
    return out


def fmt_label(c):
    cls = c.get("format") or "mp3"
    if cls in F.LOSSY:
        return f"{F.LABEL[cls]} {int(c.get('bitrate') or 0)}"
    return F.LABEL[cls]


# ───────────────────────── estado ─────────────────────────

def load_state(tracks_path):
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, encoding="utf-8") as fh:
            state = json.load(fh)
    else:
        state = {}
    with open(tracks_path, encoding="utf-8") as fh:
        tracks = json.load(fh)
    for t in tracks:
        if t["key"] not in state:
            state[t["key"]] = {"track": t, "status": "pending", "candidates": [], "tried": [], "current": None}
        else:
            state[t["key"]]["track"] = t  # por si se re-normalizó
    # entradas de una limpieza anterior de la lista que ya no existen en tracks.json:
    # se descartan, salvo las ya descargadas o en curso (esas archivos son reales)
    current = {t["key"] for t in tracks}
    stale = [k for k in state if k not in current]
    dropped = 0
    for k in stale:
        if state[k]["status"] in ("downloaded", "queued"):
            state[k]["stale"] = True
        else:
            del state[k]
            dropped += 1
    if dropped:
        print(f"(se descartaron {dropped} entradas de una versión anterior de la lista)", file=sys.stderr)
    return state


def save_state(state):
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(state, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, STATE_FILE)


def label(t):
    a = ", ".join(t["artists"])
    s = f"{a} - {t['title']}" if a else t["title"]
    return s + (f" ({t['mix']})" if t.get("mix") else "")


def enqueue_next(cli, entry, dry):
    tried = {(c["username"], c["filename"]) for c in entry["tried"]}
    for c in entry["candidates"]:
        if (c["username"], c["filename"]) in tried:
            continue
        if not dry:
            try:
                cli.enqueue(c["username"], c["filename"], c["size"])
            except requests.HTTPError as e:
                entry["tried"].append({**c, "error": str(e)})
                continue
        entry["tried"].append(c)
        entry["current"] = c
        entry["status"] = "queued" if not dry else "dry_run"
        now = time.time()
        entry.setdefault("started_at", now)  # el tiempo límite de la canción cuenta desde su primer intento
        entry.update(cand_at=now, prog_bytes=0, prog_at=now)
        return True
    entry["current"] = None
    entry["status"] = "failed" if entry["tried"] else "not_found"
    return False


def give_up_waiting(cli, e, transfer, why, quiet):
    """La descarga actual no arranca (o se estancó): se cancela en slskd y se prueba otro candidato.
    Si ya no hay candidatos o se agotó el tiempo de la canción, queda 'timeout' (pendiente en el informe)."""
    c = e["current"]
    if transfer and transfer.get("id"):
        try:
            cli.cancel(c["username"], transfer["id"])
        except Exception:  # si no se pudo cancelar, igual se sigue con otro candidato
            pass
    e.setdefault("waited", []).append({"username": c["username"], "filename": c["filename"], "why": why})
    out_of_time = time.time() - e.get("started_at", time.time()) >= SONG_TIMEOUT[0]
    if not out_of_time and enqueue_next(cli, e, False):
        if not quiet:
            print(f"  … {label(e['track'])}: {why} → probando otro candidato")
        return
    keep = [r for r in e.get("rejected", []) if r.get("keepable")]
    if keep:  # ya se había bajado algo aceptable con reservas (dudoso o falso lossless): mejor eso que nada
        e["current"] = max(keep, key=lambda r: (r.get("match") or {}).get("similarity", 0))
        e["status"] = "downloaded"
        return
    e["current"], e["status"] = None, "timeout"
    if not quiet:
        print(f"  ⏱ {label(e['track'])}: sin fuente disponible a tiempo → queda pendiente")


SONG_TIMEOUT = [600.0]


# ───────────────────────── comandos ─────────────────────────

def cmd_search(cli, state, opts):
    todo = [e for e in state.values() if e["status"] == "pending"]
    if not opts.include_ambiguous:
        skipped = [e for e in todo if e["track"]["ambiguous"]]
        for e in skipped:
            e["status"] = "skipped_ambiguous"
        todo = [e for e in todo if not e["track"]["ambiguous"]]
    if opts.only:
        todo = [e for e in state.values() if e["track"]["index"] in set(opts.only)
                and e["status"] in ("pending", "skipped_ambiguous", "not_found", "dry_run")]
    if opts.limit:
        todo = todo[: opts.limit]
    print(f"Buscando {len(todo)} canciones…\n")

    last_sync = time.time()
    for i, e in enumerate(todo, 1):
        # Mientras se busca el resto, las descargas ya encoladas se revisan cada --watch segundos:
        # así una fuente que no responde se cambia por otra sin esperar a que termine toda la búsqueda.
        if not opts.dry_run and time.time() - last_sync >= opts.watch:
            cmd_sync(cli, state, opts, quiet=True)
            last_sync = time.time()
        t = e["track"]
        print(f"[{i}/{len(todo)}] {label(t)}")
        found = []  # candidatos de todas las consultas
        for q in t["queries"]:
            try:
                responses = cli.search(q, opts.search_timeout * 1000)
            except requests.RequestException as ex:
                print(f"    ! error en búsqueda '{q}': {ex}")
                time.sleep(opts.delay)
                continue
            from collections import Counter
            nfiles = sum(len(r.get("files") or []) for r in responses)
            ex = {"reasons": Counter(), "samples": []}
            cands = rank(t, responses, opts, ex)
            seen = {(c["username"], c["filename"]) for c in found}
            found += [c for c in cands if (c["username"], c["filename"]) not in seen]
            by_fmt = Counter(F.LABEL[c["format"]] for c in cands)
            summary = ", ".join(f"{n} {k}" for k, n in by_fmt.items()) or "0"
            print(f"    q='{q}'  →  {len(responses)} usuarios, {nfiles} archivos, candidatos: {summary}")
            if (not cands and nfiles) or opts.explain:
                top = ", ".join(f"{k}: {v}" for k, v in ex["reasons"].most_common(4))
                if top:
                    print(f"      descartados → {top}")
                for smp in ex["samples"][: (8 if opts.explain else 3)]:
                    print(f"        · {smp}")
            if opts.explain and cands:
                for c in cands:
                    name = re.split(r"[\\/]", c["filename"])[-1]
                    print(f"        ✓ {c['score']:>6}  [{fmt_label(c)}]  {name}  [{c['username']}]")
            time.sleep(opts.delay)
            # ya hay algo que permite entregar el formato pedido sin perder calidad
            if any(F.good_enough(c["format"], opts.target) for c in cands):
                break
        # orden final: formato preferido primero; los demás quedan de respaldo si fallan las descargas
        e["candidates"] = order_candidates(found, opts)
        cands = e["candidates"]
        e["searched_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        if cands:
            enqueue_next(cli, e, opts.dry_run)
            c = e["current"]
            if c:
                name = re.split(r"[\\/]", c["filename"])[-1]
                print(f"    ✓ {'(simulado) ' if opts.dry_run else ''}{name}  "
                      f"[{c['username']}, {fmt_label(c)}, score {c['score']}]")
        else:
            e["status"] = "not_found"
            print("    ✗ sin resultados válidos")
        save_state(state)


def check_download(path, e, c):
    """Verificaciones de un archivo recién bajado. Devuelve (rechazo, ¿conservable si no hay más?)
    o (None, None) si se acepta. Guarda los análisis en el candidato para el informe."""
    import authenticity as A
    import matching as M

    _, info = F.classify_local(path)
    if c.get("format") in F.LOSSLESS:
        try:
            auth = A.analyze(path, info.get("rate"), info.get("seconds"))
        except Exception as ex:  # análisis fallido: no bloquea la descarga
            auth = {"verdict": "no_concluyente", "text": f"no se pudo analizar ({ex.__class__.__name__})"}
        c["authenticity"] = auth
        if A.is_fake(auth):
            return auth["text"], True  # un falso lossless es mejor que nada si no hay otro
    src = e["track"].get("source_path")
    if src and os.path.exists(src):
        try:
            m = M.same_recording(src, path)
        except Exception as ex:
            m = {"verdict": "error", "similarity": 0, "text": f"no se pudo comparar ({ex.__class__.__name__})"}
        c["match"] = m
        if m["verdict"] == "distinta":
            return f"no es la misma grabación ({m['text']})", False  # nunca se entrega otra canción
        if m["verdict"] == "dudosa":
            return f"coincidencia dudosa ({m['text']})", True
    return None, None


def verify_download(cli, e, local, quiet):
    """Si el archivo bajado no pasa las verificaciones, prueba el siguiente candidato. Si no queda
    ninguno, conserva el mejor rechazo 'conservable' (marcado en el informe) o marca la pista como
    fallida. Devuelve True si la descarga queda aceptada."""
    c = e["current"]
    path = find_local(c["filename"], *local)
    if not path:
        return True  # aún no está en disco; collect.py lo volverá a revisar al entregar
    why, keepable = check_download(path, e, c)
    if why is None:
        auth = c.get("authenticity", {})
        if auth.get("verdict") == "dudoso" and not quiet:
            print(f"  ? {label(e['track'])}: {auth['text']}")
        return True
    e.setdefault("rejected", []).append({**c, "why": why, "keepable": keepable})
    if not quiet:
        print(f"  ✗ {label(e['track'])}: {why} → probando siguiente candidato")
    if enqueue_next(cli, e, False):
        return False
    keep = [r for r in e["rejected"] if r["keepable"]]
    if keep:
        best = max(keep, key=lambda r: (r.get("match") or {}).get("similarity", 0))
        e["current"], e["status"] = best, "downloaded"
        if not quiet:
            print(f"      sin más candidatos: se conserva el mejor disponible ({best['why']}), marcado")
        return True
    if not quiet:
        print("      sin más candidatos: ninguno era la misma grabación")
    return False


def cmd_sync(cli, state, opts, quiet=False):
    try:
        users = cli.downloads()
    except requests.RequestException as ex:
        print(f"! no pude leer las descargas: {ex}")
        return 0
    transfers = {}
    for u in users:
        for d in u.get("directories", []) or []:
            for f in d.get("files", []) or []:
                transfers[(u.get("username"), f.get("filename"))] = f
    SONG_TIMEOUT[0] = opts.song_timeout
    now = time.time()

    in_flight = changed = 0
    local = None  # índice de archivos descargados; se arma solo si hay algo que verificar
    for e in state.values():
        if e["status"] != "queued" or not e["current"]:
            continue
        c = e["current"]
        tr = transfers.get((c["username"], c["filename"]))
        st = (tr or {}).get("state", "")
        if "Succeeded" in st:
            changed += 1
            # sin pérdida → detectar falsos;  con librería real → confirmar que es la misma grabación
            if opts.verificar and (c.get("format") in F.LOSSLESS or e["track"].get("source_path")):
                if local is None:
                    local = index_downloads(opts.downloads)
                if not verify_download(cli, e, local, quiet):
                    if e["status"] == "queued":
                        in_flight += 1
                    continue
            e["status"] = "downloaded"
            if not quiet:
                print(f"  ✓ {label(e['track'])}")
        elif any(x in st for x in FAIL_STATES):
            changed += 1
            if not quiet:
                print(f"  ✗ {label(e['track'])}  ({st}) → probando siguiente candidato")
            if not enqueue_next(cli, e, False) and not quiet:
                print("      sin más candidatos")
            if e["status"] == "queued":
                in_flight += 1
        else:
            # En cola del otro usuario, sin aparecer todavía o bajando. Solo se espera si de verdad avanza.
            got = (tr or {}).get("bytesTransferred") or 0
            if got > e.get("prog_bytes", 0):
                e["prog_bytes"], e["prog_at"] = got, now
            moving = "InProgress" in st and now - e.get("prog_at", now) < opts.stall
            waited = now - e.get("cand_at", now)
            song = now - e.get("started_at", now)
            if not moving and (waited >= opts.candidate_wait or song >= opts.song_timeout):
                changed += 1
                why = "descarga estancada" if "InProgress" in st else "la fuente no respondió"
                give_up_waiting(cli, e, tr, why, quiet)
            if e["status"] == "queued":
                in_flight += 1
    save_state(state)
    if not quiet and (changed or not getattr(opts, "_watching", False)
                      or time.time() - getattr(opts, "_last_beat", 0) > 600):
        opts._last_beat = time.time()
        print(f"[{time.strftime('%H:%M')}] En curso: {in_flight}   cambios: {changed}")
    return in_flight


def cmd_run(cli, state, opts):
    cmd_search(cli, state, opts)
    if opts.dry_run:
        return
    print("\nVigilando descargas (Ctrl+C para salir; se puede retomar con 'sync')…")
    opts._watching = True
    while True:
        n = cmd_sync(cli, state, opts, quiet=False)
        if n == 0:
            break
        time.sleep(opts.watch)
    cmd_report(state, opts)


def cmd_report(state, opts):
    from collections import Counter
    c = Counter(e["status"] for e in state.values())
    fmts = Counter(F.LABEL[(e.get("current") or {}).get("format") or "mp3"] for e in state.values()
                   if e["status"] in ("downloaded", "queued"))
    print(f"\nResumen (formato pedido: {opts.target}):")
    for k in ("downloaded", "queued", "dry_run", "pending", "timeout", "not_found", "failed", "skipped_ambiguous"):
        if c.get(k):
            print(f"  {k:18} {c[k]}")
    if fmts:
        print("  (descargadas/en curso por formato: " + ", ".join(f"{k} {v}" for k, v in fmts.most_common()) + ")")
    missing = [e for e in state.values() if e["status"] in ("not_found", "failed", "skipped_ambiguous", "timeout")]
    missing.sort(key=lambda e: e["track"]["index"])
    accepted = " / ".join(F.LABEL[x] for x in opts.preference)
    with open(opts.report_file, "w", encoding="utf-8") as fh:
        fh.write(f"NO ENCONTRADAS (en ningún formato aceptado: {accepted}) — {time.strftime('%Y-%m-%d %H:%M')}\n")
        fh.write(f"PENDIENTES: {len(missing)}\n\n")
        for i, e in enumerate(missing, 1):
            t = e["track"]
            why = {"not_found": "sin resultados", "failed": "fallaron todos los candidatos",
                   "skipped_ambiguous": "ambigua, revisar a mano",
                   "timeout": "pendiente: ninguna fuente disponible a tiempo (intenta más tarde o con otro formato)"
                   }[e["status"]]
            kb = f" | actual: {t['current_kbps']} kbps" if t.get("current_kbps") else ""
            fh.write(f"{i:03d}. {t['original']}{kb} | motivo: {why}\n")
    print(f"\n→ {opts.report_file} ({len(missing)} canciones)")


GROUPS = {
    "descargadas": ("downloaded",),
    "en_curso":    ("queued",),
    "sin_buscar":  ("pending", "dry_run"),
    "faltantes":   ("not_found", "failed", "skipped_ambiguous", "timeout"),
}
GROUP_TITLES = {
    "descargadas": "DESCARGADAS",
    "en_curso":    "EN CURSO (en cola o bajando en slskd)",
    "sin_buscar":  "SIN BUSCAR TODAVÍA",
    "faltantes":   "FALTANTES (no encontradas / fallidas / ambiguas)",
}


def cmd_list(state, opts):
    """Lista canción por canción, agrupada por estado. Solo lee state.json."""
    want = opts.filter or "todo"
    if want not in GROUPS and want != "todo":
        sys.exit(f"Filtro desconocido '{want}'. Usa: todo, " + ", ".join(GROUPS))
    entries = sorted(state.values(), key=lambda e: e["track"]["index"])
    counts = {g: sum(e["status"] in st for e in entries) for g, st in GROUPS.items()}
    print("  ".join(f"{g}: {n}" for g, n in counts.items()) + f"   (total {len(entries)})")
    why = {"not_found": "no encontrada", "failed": "fallaron todos los candidatos",
           "skipped_ambiguous": "ambigua (revisar a mano)"}
    for g, sts in GROUPS.items():
        if want not in ("todo", g):
            continue
        rows = [e for e in entries if e["status"] in sts]
        if not rows:
            continue
        print(f"\n── {GROUP_TITLES[g]}: {len(rows)} ──")
        for e in rows:
            t, c = e["track"], e.get("current") or {}
            line = f"{t['index']:>4}. {label(t)}"
            if g in ("descargadas", "en_curso") and c:
                name = re.split(r"[\\/]", c.get("filename", ""))[-1]
                line += f"\n        [{fmt_label(c)}] {name}"
                if g == "en_curso":
                    line += f"  (usuario {c.get('username')}, intento {len(e.get('tried', []))})"
            elif g == "faltantes":
                line += f"   → {why.get(e['status'], e['status'])}"
            print(line)


def cmd_reset(state, opts):
    n = 0
    for e in state.values():
        if e["status"] in ("not_found", "failed", "skipped_ambiguous", "dry_run", "timeout"):
            e.update(status="pending", candidates=[], tried=[], current=None)
            for k in ("started_at", "cand_at", "prog_bytes", "prog_at"):
                e.pop(k, None)
            n += 1
    save_state(state)
    print(f"{n} canciones vueltas a 'pending'.")


def load_format(opts):
    """Resuelve opts.target / opts.preference. Si se pasa --formato o --preferencia se guardan
    en formato.json, para que reintentar/entregar usen lo mismo sin repetirlo."""
    saved = {}
    if os.path.exists(FORMAT_FILE):
        with open(FORMAT_FILE, encoding="utf-8") as fh:
            saved = json.load(fh)
    target = F.target_from_name(opts.formato or saved.get("formato") or "original")
    pref_text = opts.preferencia or (saved.get("preferencia") if not opts.formato else None)
    preference = F.parse_preference(pref_text, target)
    if not opts.flac:
        preference = [p for p in preference if p != "flac"]
    opts.target, opts.preference = target, preference
    if opts.formato or opts.preferencia:
        with open(FORMAT_FILE, "w", encoding="utf-8") as fh:
            json.dump({"formato": target, "preferencia": ",".join(preference)}, fh)
        print(f"Formato pedido: {target}   preferencia de búsqueda: {' > '.join(preference)}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["search", "sync", "run", "report", "reset", "list"])
    ap.add_argument("filter", nargs="?", help="para 'list': todo | descargadas | en_curso | sin_buscar | faltantes")
    ap.add_argument("--tracks", default="tracks.json")
    ap.add_argument("--dry-run", action="store_true", help="buscar y elegir, pero no encolar nada")
    ap.add_argument("--explain", action="store_true", help="mostrar motivos de descarte y todos los candidatos")
    ap.add_argument("--only", type=int, nargs="+", help="procesar solo estos números de la lista original")
    ap.add_argument("--limit", type=int, help="procesar solo N canciones (para probar)")
    ap.add_argument("--include-ambiguous", action="store_true", help="buscar también las sin artista/título corto")
    ap.add_argument("--formato", help="original (por defecto) | aiff | wav | flac | alac | mp3 | m4a. "
                                      "Se recuerda por lista en formato.json")
    ap.add_argument("--preferencia", help="orden de búsqueda, p. ej. 'aiff,wav,flac,alac,mp3' "
                                          "(por defecto depende de --formato)")
    ap.add_argument("--min-bitrate", type=int, default=320)
    ap.add_argument("--no-flac", dest="flac", action="store_false",
                    help="no aceptar FLAC (lo quita de la preferencia)")
    ap.add_argument("--no-verificar", dest="verificar", action="store_false",
                    help="no analizar el espectro de los archivos sin pérdida (detección de falsos lossless)")
    ap.add_argument("--dur-tol", type=float, default=4.0,
                    help="segundos de diferencia de duración aceptados al buscar desde una librería real")
    ap.add_argument("--downloads", default=os.environ.get("DESCARGAS", "/descargas"),
                    help="carpeta de descargas de slskd (para verificar los archivos)")
    ap.add_argument("--min-score", type=float, default=20)
    ap.add_argument("--search-timeout", type=int, default=15, help="segundos por búsqueda en slskd")
    ap.add_argument("--delay", type=float, default=3, help="pausa entre búsquedas (no saturar la red)")
    ap.add_argument("--watch", type=int, default=15, help="segundos entre revisiones de las descargas")
    ap.add_argument("--song-timeout", type=float, default=600,
                    help="segundos máximos por canción desde su primer intento; si no hay una descarga "
                         "avanzando, queda pendiente en el informe")
    ap.add_argument("--candidate-wait", type=float, default=120,
                    help="segundos que se espera a que arranque la descarga de un candidato antes de probar otro")
    ap.add_argument("--stall", type=float, default=120,
                    help="segundos sin recibir datos para considerar estancada una descarga en curso")
    ap.add_argument("--report-file", default="no_encontradas.txt")
    opts = ap.parse_args()
    try:
        load_format(opts)
    except ValueError as ex:
        sys.exit(str(ex))

    state = load_state(opts.tracks)
    if opts.command == "report":
        return cmd_report(state, opts)
    if opts.command == "reset":
        return cmd_reset(state, opts)
    if opts.command == "list":
        return cmd_list(state, opts)

    url = os.environ.get("SLSKD_URL", "http://localhost:5030")
    key = os.environ.get("SLSKD_API_KEY")
    if not key:
        print("Aviso: SLSKD_API_KEY no está definida.", file=sys.stderr)
    cli = Slskd(url, key)
    if not cli.wait_ready():
        sys.exit(1)
    try:
        {"search": cmd_search, "sync": cmd_sync, "run": cmd_run}[opts.command](cli, state, opts)
    except KeyboardInterrupt:
        save_state(state)
        print("\nInterrumpido. Progreso guardado en state.json.")


if __name__ == "__main__":
    main()
