#!/usr/bin/env python3
# Vendorizado de dj-library-upgrader/upgrader/matching.py (sin cambios).
# No lo edites aquí: cambia el original y vuelve a copiarlo (ver services/README.md).
"""
matching.py — Comprueba que dos archivos son LA MISMA GRABACIÓN comparando sus espectrogramas,
sin importar formato, bitrate o volumen. Distingue remixes, versiones en vivo u otras canciones
con el mismo nombre.

Huella de audio tipo Philips (Haitsma & Kalker, 2002):
  · audio mono a 5512 Hz, cuadros de ~370 ms con salto de ~46 ms (ventana Hann)
  · energía en 33 bandas logarítmicas entre 300 y 2000 Hz
  · 32 bits por cuadro: bit = 1 si la diferencia de energía entre bandas vecinas crece respecto
    al cuadro anterior. Es robusto a la compresión MP3/AAC, al ecualizado suave y al volumen.

Comparación: se alinean las huellas (tolera silencios distintos al inicio, ±MAX_SHIFT_S) y se
mide el porcentaje de bits iguales en el tramo común. Misma grabación: ~85-100 %.
Grabaciones distintas: ~50 %.

Uso suelto:  python3 matching.py original.mp3 candidato.flac
"""
import subprocess
import sys

import numpy as np

RATE = 5512
FRAME = 2048            # ~372 ms
HOP = 256               # ~46 ms
BANDS = 33
FMIN, FMAX = 300.0, 2000.0
MAX_SECONDS = 360       # huella de hasta 6 min
MAX_SHIFT_S = 12.0      # desfase máximo buscado al alinear
MIN_OVERLAP_S = 20.0

SAME_THRESHOLD = 0.80   # ≥ 80 % de bits iguales: misma grabación
DOUBT_THRESHOLD = 0.68  # entre 68 y 80 %: dudoso (master distinto, edit, mucha compresión)


def _decode(path, seconds=MAX_SECONDS):
    cmd = ["ffmpeg", "-v", "error", "-t", str(seconds), "-i", path, "-map", "0:a:0",
           "-ac", "1", "-ar", str(RATE), "-f", "f32le", "-"]
    return np.frombuffer(subprocess.run(cmd, check=True, capture_output=True).stdout, dtype=np.float32)


def fingerprint(path) -> np.ndarray:
    """Matriz booleana (cuadros × 32)."""
    x = _decode(path)
    if len(x) < FRAME * 8:
        return np.zeros((0, BANDS - 1), dtype=bool)
    frames = np.lib.stride_tricks.sliding_window_view(x, FRAME)[::HOP] * np.hanning(FRAME)
    spec = np.abs(np.fft.rfft(frames, axis=1)) ** 2
    freqs = np.fft.rfftfreq(FRAME, 1 / RATE)
    edges = np.geomspace(FMIN, FMAX, BANDS + 1)
    idx = np.searchsorted(freqs, edges)
    energy = np.stack([spec[:, idx[b]:max(idx[b + 1], idx[b] + 1)].sum(axis=1) for b in range(BANDS)], axis=1)
    energy = np.log(energy + 1e-10)
    band_diff = energy[:, :-1] - energy[:, 1:]          # (cuadros, 32)
    return (band_diff[1:] - band_diff[:-1]) > 0          # diferencia temporal → bits


def compare(fp_a: np.ndarray, fp_b: np.ndarray) -> dict:
    """{'similarity' 0-1, 'offset_s', 'overlap_s'} con el mejor alineamiento."""
    hop_s = HOP / RATE
    max_shift = int(MAX_SHIFT_S / hop_s)
    min_overlap = int(MIN_OVERLAP_S / hop_s)
    if min(len(fp_a), len(fp_b)) < min_overlap:
        min_overlap = max(1, min(len(fp_a), len(fp_b)) // 2)
    best = {"similarity": 0.0, "offset_s": 0.0, "overlap_s": 0.0}
    # búsqueda gruesa (cada 4 cuadros) y luego fina alrededor del mejor desfase
    for shifts in (range(-max_shift, max_shift + 1, 4), None):
        if shifts is None:
            center = int(round(best["offset_s"] / hop_s))
            shifts = range(center - 4, center + 5)
        for s in shifts:
            a = fp_a[max(0, s):]
            b = fp_b[max(0, -s):]
            n = min(len(a), len(b))
            if n < min_overlap:
                continue
            sim = 1.0 - np.count_nonzero(a[:n] ^ b[:n]) / a[:n].size
            if sim > best["similarity"]:
                best = {"similarity": float(sim), "offset_s": s * hop_s, "overlap_s": n * hop_s}
    return best


def verdict(similarity: float) -> str:
    if similarity >= SAME_THRESHOLD:
        return "misma"
    if similarity >= DOUBT_THRESHOLD:
        return "dudosa"
    return "distinta"


def same_recording(path_a, path_b, fp_a=None) -> dict:
    """Compara dos archivos. Acepta la huella de A ya calculada (para no repetirla)."""
    fp_a = fingerprint(path_a) if fp_a is None else fp_a
    r = compare(fp_a, fingerprint(path_b))
    r["verdict"] = verdict(r["similarity"])
    r["text"] = f"{r['similarity'] * 100:.0f}% ({r['verdict']})"
    return r


if __name__ == "__main__":
    r = same_recording(sys.argv[1], sys.argv[2])
    print(f"{r['text']}  desfase {r['offset_s']:+.2f} s, tramo comparado {r['overlap_s']:.0f} s")
