"""Tracklist ID: comprimir → ACRCloud y Shazam EN PARALELO → tracklist.txt / tracklist.csv.

Cada motor corre por su cuenta: si uno se satura, falla o se pasa de tiempo, el trabajo sigue con lo
que haya dado el otro. Al final cada coincidencia lleva una puntuación de confianza (0-100).
Sin la verificación con Panako de djset/tracklist.ps1 (fuera de la beta).
"""
import asyncio
import csv
import json
import os
import shlex
import shutil
from pathlib import Path

from app.core.config import get_settings
from app.models import ToolJob
from app.services import tools as svc
from worker import jobs, proc
from worker.jobs import JobError

TOOL = "tracklist"


def _cmd(override: str, name: str) -> list[str]:
    """El script vendorizado o, en pruebas, el comando alternativo configurado."""
    return shlex.split(override) if override else proc.script(TOOL, name)


SATURATED = 3  # código de salida de scan.py cuando Shazam rechaza peticiones


def confidence(source: str, score: str) -> int | None:
    """Puntuación 0-100 de una coincidencia.
    ACRCloud ya da un score 0-100. Shazam no: se puntúa por cuántos fragmentos seguidos coincidieron
    (2 → 70, 3 → 85, 4 o más → 95). Si los dos motores coinciden en el mismo tema, +15."""
    if not source:
        return None  # tramo ID - ID
    try:
        n = float(score)
    except (TypeError, ValueError):
        n = 0
    if source.startswith("acrcloud"):
        return int(min(100, n + (15 if "shazam" in source else 0)))
    return int(min(95, 40 + 15 * n))


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

    # 1. Comprimir: mismo reconocimiento con una fracción del tamaño (WAV de 2 h: ~1.2 GB → ~85 MB)
    await jobs.progress(job.id, 5, "Comprimiendo el set")
    scan_set = work / f"{job.id}_scan.mp3"
    r = await proc.run([*proc.script(TOOL, "comprimir.py"), str(src), str(scan_set), "--kbps", str(s.tracklist_kbps)],
                       log=log, timeout=3600)
    if not r.ok:
        raise JobError("No pudimos procesar el audio del set.", r.tail())
    if not scan_set.exists():  # ya era un MP3 liviano: comprimir.py indica usar el original tal cual
        scan_set = src

    seconds = ((job.result or {}).get("input") or {}).get("seconds")
    fragments = max(1, int(((seconds or 0) - 12) // 20) + 1)   # los que consultará scan.py (12 s cada 20 s)
    acr_json, shazam_jsonl = work / "acr_raw.json", work / "raw.jsonl"
    use_acr = bool(os.environ.get("ACRCLOUD_TOKEN") or s.acr_scan_cmd)
    use_shazam = s.shazam_fallback_max_seconds > 0 and (s.shazam_max_seconds > 0 or not use_acr)
    state = {"acr": "en curso" if use_acr else "", "shazam": "en curso" if use_shazam else ""}
    loop = asyncio.get_running_loop()
    started = loop.time()

    async def publish():
        """El avance es el promedio de los motores activos, para que nunca se vea detenido por uno solo."""
        parts, fracs = [], []
        if use_acr:
            parts.append(f"ACRCloud: {state['acr']}")
            fracs.append(1.0 if state["acr"] != "en curso" else min(0.9, (loop.time() - started) / 600))
        if use_shazam:
            scanned, _ = _shazam_stats(shazam_jsonl)
            running = state["shazam"] == "en curso"
            parts.append(f"Shazam: {scanned} de {fragments} fragmentos" if running else f"Shazam: {state['shazam']}")
            fracs.append(min(1.0, scanned / fragments) if running else 1.0)
        frac = sum(fracs) / len(fracs) if fracs else 1.0
        await jobs.progress(job.id, 15 + round(70 * frac), "Reconociendo · " + " · ".join(parts))

    # 2. Los dos motores a la vez. Ninguno espera al otro ni lo detiene.
    async def acr() -> proc.Result:
        r = await proc.run([*_cmd(s.acr_scan_cmd, "acr_scan.py"), str(scan_set), str(acr_json)],
                           log=work / "acr.log", timeout=s.acr_max_seconds, on_tick=publish)
        state["acr"] = "listo" if r.ok and acr_json.exists() else "no disponible"
        await publish()
        return r

    async def shazam() -> proc.Result:
        r = await proc.run([*_cmd(s.shazam_scan_cmd, "scan.py"), str(scan_set), str(shazam_jsonl),
                            "--max-fail-streak", str(s.shazam_fail_streak)],
                           log=work / "shazam.log", timeout=s.shazam_fallback_max_seconds, on_tick=publish)
        state["shazam"] = ("listo" if r.ok else "saturado" if r.code == SATURATED else
                           "cortado por tiempo" if r.timed_out else "no disponible")
        return r

    await publish()
    shazam_task = asyncio.create_task(shazam()) if use_shazam else None
    acr_result = shazam_result = None
    shazam_cut = False
    try:
        if use_acr:
            acr_result = await acr()
        if shazam_task:
            acr_ok = state["acr"] == "listo"
            # Con ACRCloud como base, Shazam solo complementa: se le da un tope más corto.
            wait = max(0.0, s.shazam_max_seconds - (loop.time() - started)) if acr_ok else None
            done, _ = await asyncio.wait({shazam_task}, timeout=wait)
            if not done:
                shazam_cut = True
                shazam_task.cancel()
                state["shazam"] = "cortado por tiempo"
            try:
                shazam_result = await shazam_task
            except asyncio.CancelledError:
                if not shazam_cut:
                    raise
    finally:
        if shazam_task and not shazam_task.done():  # el worker se apaga: no dejar el escaneo huérfano
            shazam_task.cancel()
            await asyncio.gather(shazam_task, return_exceptions=True)

    # 3. Qué dio cada motor
    sources, notes, args = [], [], []
    if state["acr"] == "listo":
        sources.append("acrcloud")
        args += ["--acr", str(acr_json)]
    elif use_acr:
        notes.append("ACRCloud no estuvo disponible: el tracklist se armó con Shazam.")
    else:
        notes.append("ACRCloud no está configurado: el tracklist se armó con Shazam.")
    scanned, hits = _shazam_stats(shazam_jsonl)
    if hits:
        sources.append("shazam")
        args += ["--shazam", str(shazam_jsonl)]
    if use_shazam and state["shazam"] != "listo":
        covered = f"alcanzó a revisar {min(100, round(100 * scanned / fragments))}% del set"
        notes.append({
            "saturado": f"Shazam rechazó peticiones por saturación y se detuvo ({covered}).",
            "cortado por tiempo": f"Shazam se cortó por tiempo ({covered}).",
        }.get(state["shazam"], "Shazam no estuvo disponible."))
    if not sources:
        detail = "\n".join(x.tail(800) for x in (acr_result, shazam_result) if x) or "sin motores configurados"
        if use_shazam and state["shazam"] == "listo" and not use_acr:
            raise JobError("No reconocimos ningún tema en este set.", detail)
        raise JobError("Los servicios de reconocimiento no respondieron. Intenta de nuevo más tarde.", detail)

    # 4. Combinar, exportar y puntuar cada coincidencia
    await jobs.progress(job.id, 90, "Armando el tracklist")
    r = await proc.run([*proc.script(TOOL, "tracklist.py"), str(work / "tracklist"), *args], log=log, timeout=600)
    if not r.ok or not (work / "tracklist.csv").exists():
        raise JobError("No pudimos armar el tracklist con lo reconocido.", r.tail())
    for name in ("tracklist.txt", "tracklist.csv"):
        shutil.copyfile(work / name, results / name)

    summary = _summary(results / "tracklist.csv", sources, notes, seconds)
    found, ids = summary["tracks"], summary["unidentified"]
    message = f"{found} temas identificados" if found != 1 else "1 tema identificado"
    if ids:
        message += f", {ids} tramo{'s' if ids != 1 else ''} sin identificar"
    return {"summary": summary, "files": ["tracklist.txt", "tracklist.csv"], "message": message}
