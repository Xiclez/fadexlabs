"""Tracklist ID: comprimir → ACRCloud y AudD EN PARALELO (Shazam solo de reserva) → tracklist.txt / tracklist.csv.

Cada motor principal corre por su cuenta: si uno falla o se pasa de tiempo, el trabajo sigue con lo que
haya dado el otro. Shazam (sin API oficial, bloquea por IP a los VPS) solo corre si ninguno terminó.
Al final cada coincidencia lleva una puntuación de confianza (0-100).
Sin la verificación con Panako de djset/tracklist.ps1 (fuera de la beta).
"""
import asyncio
import csv
import json
import logging
import os
import shlex
import shutil
from pathlib import Path

from app.core.config import get_settings
from app.models import ToolJob
from app.services import tools as svc
from worker import jobs, proc
from worker import tracklist_visual as visual
from worker.jobs import JobError

TOOL = "tracklist"
logger = logging.getLogger("fadex.worker.tracklist")


def _cmd(override: str, name: str) -> list[str]:
    """El script vendorizado o, en pruebas, el comando alternativo configurado."""
    return shlex.split(override) if override else proc.script(TOOL, name)


SATURATED = 3  # código de salida de scan.py cuando Shazam rechaza peticiones


def confidence(source: str, score: str) -> int | None:
    """Puntuación 0-100 de una coincidencia.
    ACRCloud ya da un score 0-100. AudD y Shazam se puntúan por cuántos fragmentos seguidos coincidieron
    (2 → 70, 3 → 85, 4 o más → 95). Si otro motor confirma el mismo tema: +15 sobre ACRCloud, +10 si no."""
    if not source:
        return None  # tramo ID - ID
    try:
        n = float(score)
    except (TypeError, ValueError):
        n = 0
    confirmed = "+" in source
    if source.startswith("acrcloud"):
        return int(min(100, n + (15 if confirmed else 0)))
    return int(min(100, min(95, 40 + 15 * n) + (10 if confirmed else 0)))


def level(conf: int) -> str:
    return "alta" if conf >= 85 else "media" if conf >= 60 else "baja"


def _score_csv(path: Path) -> dict:
    """Agrega las columnas `confianza` y `nivel` al CSV y devuelve cuántas hay de cada nivel."""
    with open(path, encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.reader(fh))
    header, data = rows[0], rows[1:]
    src, sc = header.index("source"), header.index("score_or_hits")
    counts = {"alta": 0, "media": 0, "baja": 0}
    out = [header + ["confianza", "nivel"]]
    for r in data:
        conf = confidence(r[src], r[sc])
        if conf is None:
            out.append(r + ["", ""])
        else:
            counts[level(conf)] += 1
            out.append(r + [conf, level(conf)])
    with open(path, "w", encoding="utf-8-sig", newline="") as fh:
        csv.writer(fh).writerows(out)
    return counts


def _summary(csv_path: Path, sources: list[str], notes: list[str], seconds: float | None) -> dict:
    confidence_counts = _score_csv(csv_path)
    with open(csv_path, encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    ids = sum(r["artist"] == "ID" and r["title"] == "ID" for r in rows)
    return {"tracks": len(rows) - ids, "unidentified": ids, "sources": sources, "notes": notes,
            "duration_seconds": seconds, "confidence": confidence_counts}


def _audd_stats(path: Path) -> tuple[int, int]:
    """(partes del set ya consultadas, partes en total) de audd_raw.json."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return int(data.get("pieces_done") or 0), int(data.get("pieces") or 0)
    except (OSError, ValueError):
        return 0, 0


def _shazam_stats(path: Path) -> tuple[int, int]:
    """(fragmentos consultados, fragmentos con coincidencia) de raw.jsonl."""
    scanned = hits = 0
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    scanned += 1
                    hits += bool((json.loads(line).get("response") or {}).get("track"))
    except (OSError, json.JSONDecodeError):
        pass
    return scanned, hits


async def run(job: ToolJob) -> dict:
    s = get_settings()
    src = svc.input_path(job)
    work, results = svc.job_dir(job.id) / "work", svc.results_dir(job.id)
    work.mkdir(parents=True, exist_ok=True)
    results.mkdir(parents=True, exist_ok=True)
    log = work / "worker.log"
    if not src.exists():
        raise JobError("No encontramos el archivo subido. Vuelve a subirlo.", f"falta {src}")

    async def stop() -> bool:  # el usuario pulsó "Detener": se arma el tracklist con lo reconocido hasta ahí
        return await jobs.stop_requested(job.id)

    def stopped_early(why: str) -> dict:
        return {"summary": {"tracks": 0, "unidentified": 0, "sources": [], "notes": [why], "stopped": True,
                            "duration_seconds": None, "confidence": None}, "files": [],
                "message": "Detenido · " + why}

    # 1. Comprimir: mismo reconocimiento con una fracción del tamaño (WAV de 2 h: ~1.2 GB → ~85 MB)
    await jobs.progress(job.id, 5, "Comprimiendo el set")
    scan_set = work / f"{job.id}_scan.mp3"
    r = await proc.run([*proc.script(TOOL, "comprimir.py"), str(src), str(scan_set), "--kbps", str(s.tracklist_kbps)],
                       log=log, timeout=3600, should_stop=stop)
    if r.stopped:
        return stopped_early("Lo detuviste antes de reconocer los temas.")
    if not r.ok:
        raise JobError("No pudimos procesar el audio del set.", r.tail())
    if not scan_set.exists():  # ya era un MP3 liviano: comprimir.py indica usar el original tal cual
        scan_set = src

    seconds = ((job.result or {}).get("input") or {}).get("seconds")
    # forma de onda en paralelo con el reconocimiento (antes de que se borre el audio)
    peaks_task = asyncio.create_task(asyncio.to_thread(visual.peaks, scan_set, seconds))
    fragments = max(1, int(((seconds or 0) - 12) // 20) + 1)   # los que consultará scan.py (12 s cada 20 s)
    acr_json, audd_json, shazam_jsonl = work / "acr_raw.json", work / "audd_raw.json", work / "raw.jsonl"
    use_acr = bool(os.environ.get("ACRCLOUD_TOKEN") or s.acr_scan_cmd)
    use_audd = bool(os.environ.get("AUDD_API_TOKEN") or s.audd_scan_cmd)
    state = {"acr": "en curso" if use_acr else "", "audd": "en curso" if use_audd else "", "shazam": ""}
    loop = asyncio.get_running_loop()
    started = loop.time()

    async def publish():
        """El avance es el promedio de los motores activos, para que nunca se vea detenido por uno solo."""
        parts, fracs = [], []
        if use_acr:
            parts.append(f"ACRCloud: {state['acr']}")
            fracs.append(1.0 if state["acr"] != "en curso" else min(0.9, (loop.time() - started) / 600))
        if use_audd:
            done, total = _audd_stats(audd_json)
            running = state["audd"] == "en curso"
            parts.append(f"AudD: {done} de {total or '?'} partes" if running else f"AudD: {state['audd']}")
            fracs.append(min(1.0, done / total) if running and total else 0.0 if running else 1.0)
        if state["shazam"]:
            scanned, _ = _shazam_stats(shazam_jsonl)
            running = state["shazam"] == "en curso"
            parts.append(f"Shazam (reserva): {scanned} de {fragments} fragmentos" if running
                         else f"Shazam: {state['shazam']}")
            fracs.append(min(1.0, scanned / fragments) if running else 1.0)
        frac = sum(fracs) / len(fracs) if fracs else 1.0
        await jobs.progress(job.id, 15 + round(70 * frac), "Reconociendo · " + " · ".join(parts))

    # 2. Motores principales a la vez (ACRCloud y AudD): ninguno espera al otro ni lo detiene.
    async def acr() -> proc.Result:
        r = await proc.run([*_cmd(s.acr_scan_cmd, "acr_scan.py"), str(scan_set), str(acr_json)],
                           log=work / "acr.log", timeout=s.acr_max_seconds, on_tick=publish, should_stop=stop)
        state["acr"] = "listo" if r.ok and acr_json.exists() else "detenido" if r.stopped else "no disponible"
        await publish()
        return r

    async def audd() -> proc.Result:
        r = await proc.run([*_cmd(s.audd_scan_cmd, "audd_scan.py"), str(scan_set), str(audd_json),
                            "--every", "1", "--skip", str(s.audd_skip), "--piece", str(s.audd_piece_seconds)],
                           log=work / "audd.log", timeout=s.audd_max_seconds, on_tick=publish, should_stop=stop)
        done, total = _audd_stats(audd_json)
        state["audd"] = ("listo" if r.ok and done and done == total else "detenido" if r.stopped else
                         "parcial" if done else "no disponible")
        await publish()
        return r

    # 3. Shazam solo de reserva: si ningún motor principal terminó. En un VPS Shazam suele bloquear por IP.
    async def shazam() -> proc.Result:
        state["shazam"] = "en curso"
        r = await proc.run([*_cmd(s.shazam_scan_cmd, "scan.py"), str(scan_set), str(shazam_jsonl),
                            "--max-fail-streak", str(s.shazam_fail_streak),
                            "--cooldown", str(s.shazam_cooldown_seconds), "--max-cooldowns", str(s.shazam_max_cooldowns)],
                           log=work / "shazam.log", timeout=s.shazam_max_seconds, on_tick=publish, should_stop=stop)
        state["shazam"] = ("listo" if r.ok else "detenido" if r.stopped else "saturado" if r.code == SATURATED else
                           "cortado por tiempo" if r.timed_out else "no disponible")
        return r

    await publish()
    primaries = [("ACRCloud", "acr", acr)] * use_acr + [("AudD", "audd", audd)] * use_audd
    outcome = await asyncio.gather(*(run() for _, _, run in primaries))
    results_by = {key: res for (_, key, _), res in zip(primaries, outcome)}
    stopped = "detenido" in (state["acr"], state["audd"])
    shazam_result = None
    if s.shazam_max_seconds > 0 and not stopped and "listo" not in (state["acr"], state["audd"]):
        shazam_result = await shazam()
        stopped = state["shazam"] == "detenido"
    results_by["shazam"] = shazam_result

    # 4. Qué dio cada motor. work/ se borra al terminar: el motivo de un fallo queda en el log del worker.
    for name, key in (("ACRCloud", "acr"), ("AudD", "audd"), ("Shazam", "shazam")):
        res = results_by.get(key)
        if res and state[key] not in ("listo", "detenido"):
            logger.warning("trabajo %s: %s %s (código %s):\n%s", job.id, name, state[key], res.code, res.tail(800))
    sources, notes, args = [], [], []
    if stopped:
        notes.append("Lo detuviste: el tracklist se armó con lo reconocido hasta ese momento.")
    audd_done, audd_total = _audd_stats(audd_json)
    audd_pct = min(100, round(100 * audd_done / audd_total)) if audd_total else 0
    if state["acr"] == "listo":
        sources.append("acrcloud")
        args += ["--acr", str(acr_json)]
    elif state["acr"] == "detenido":
        notes.append("ACRCloud no alcanzó a terminar antes de que lo detuvieras.")
    elif use_acr:
        notes.append("ACRCloud no estuvo disponible.")
    if state["audd"] in ("listo", "parcial", "detenido") and audd_done:
        sources.append("audd")
        args += ["--audd", str(audd_json)]
    if state["audd"] == "parcial":
        notes.append(f"AudD se interrumpió (alcanzó a revisar {audd_pct}% del set).")
    elif state["audd"] == "detenido":
        notes.append(f"AudD alcanzó a revisar {audd_pct}% del set antes de que lo detuvieras.")
    elif use_audd and state["audd"] != "listo":
        notes.append("AudD no estuvo disponible.")
    scanned, hits = _shazam_stats(shazam_jsonl)
    if state["shazam"]:
        notes.append("Se usó Shazam como reserva." if use_acr or use_audd else
                     "ACRCloud y AudD no están configurados: el tracklist se armó con Shazam.")
        if hits:
            sources.append("shazam")
            args += ["--shazam", str(shazam_jsonl)]
        if state["shazam"] != "listo":
            covered = f"alcanzó a revisar {min(100, round(100 * scanned / fragments))}% del set"
            notes.append({
                "saturado": f"Shazam rechazó peticiones por saturación y se detuvo ({covered}).",
                "cortado por tiempo": f"Shazam se cortó por tiempo ({covered}).",
                "detenido": f"Shazam {covered} antes de que lo detuvieras.",
            }.get(state["shazam"], "Shazam no estuvo disponible."))
    # qué parte del set se revisó: todo si un motor principal terminó; si no, lo más que alcanzó alguno
    coverage = 100 if "listo" in (state["acr"], state["audd"]) else max(
        audd_pct, min(100, round(100 * scanned / fragments)) if state["shazam"] else 0)
    if not sources and stopped:
        peaks_task.cancel()
        return stopped_early("Lo detuviste antes de que se reconociera algún tema.")
    if not sources:
        detail = "\n".join(x.tail(800) for x in results_by.values() if x) or "sin motores configurados"
        if "listo" in state.values():
            raise JobError("No reconocimos ningún tema en este set.", detail)
        raise JobError("Los servicios de reconocimiento no respondieron. Intenta de nuevo más tarde.", detail)

    # 5. Combinar, exportar y puntuar cada coincidencia
    await jobs.progress(job.id, 90, "Armando el tracklist")
    r = await proc.run([*proc.script(TOOL, "tracklist.py"), str(work / "tracklist"), *args], log=log, timeout=600)
    if not r.ok or not (work / "tracklist.csv").exists():
        raise JobError("No pudimos armar el tracklist con lo reconocido.", r.tail())
    for name in ("tracklist.txt", "tracklist.csv"):
        shutil.copyfile(work / name, results / name)

    summary = _summary(results / "tracklist.csv", sources, notes, seconds)
    summary["stopped"] = stopped
    summary["coverage"] = coverage
    found, ids = summary["tracks"], summary["unidentified"]
    message = f"{found} temas identificados" if found != 1 else "1 tema identificado"
    if ids:
        message += f", {ids} tramo{'s' if ids != 1 else ''} sin identificar"
    if stopped:
        message = "Detenido · " + message
    elif coverage < s.tracklist_min_coverage:
        # no se presenta como completo un set que los motores apenas revisaron
        summary["incomplete"] = True
        message = f"Incompleto · solo pudimos revisar el {coverage}% del set ({message}). Intenta de nuevo más tarde."

    # 6. Vista con forma de onda y enlaces (si falla, el tracklist se entrega igual)
    has_visual = False
    try:
        wave = await peaks_task
        tracks = visual.enrich(results / "tracklist.csv", acr_json if "acrcloud" in sources else None,
                               shazam_jsonl if "shazam" in sources else None, seconds,
                               audd_json if "audd" in sources else None)
        duration = seconds or (tracks[-1]["end"] if tracks else None)
        with open(results / "visual.json", "w", encoding="utf-8") as fh:
            json.dump({"duration": duration, "peaks": wave, "tracks": tracks}, fh, ensure_ascii=False)
        has_visual = True
    except Exception:  # noqa: BLE001
        logging.getLogger("fadex.worker.tracklist").exception("no se pudo armar la vista de %s", job.id)
    return {"summary": summary, "files": ["tracklist.txt", "tracklist.csv"], "message": message,
            "visual": has_visual}
