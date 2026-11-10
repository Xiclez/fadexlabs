#!/usr/bin/env python3
# Vendorizado de dj-library-upgrader/upgrader/authenticity.py (sin cambios).
# No lo edites aquí: cambia el original y vuelve a copiarlo (ver services/README.md).
"""
authenticity.py — Detecta "falsos lossless": archivos FLAC/WAV/AIFF/ALAC que en realidad vienen
de un MP3/AAC, y falsos hi-res (44.1 kHz subidos a 96 kHz).

Los codificadores con pérdida eliminan las frecuencias altas con un corte abrupto ("pared")
cuya frecuencia delata el bitrate de origen. Un archivo sin pérdida real tiene contenido hasta
cerca de la frecuencia de Nyquist o, si el master se filtró, una caída gradual.

Método: se decodifica ~60 s del tema con ffmpeg, se promedia el espectro (FFT con ventana Hann),
se suaviza en bandas de ~100 Hz y se busca la frecuencia más alta con una caída brusca
(> DROP_DB en menos de 500 Hz) por encima de la cual ya casi no hay energía.

Uso suelto:  python3 authenticity.py archivo.flac [más archivos…]
"""
import subprocess
import sys

import numpy as np

FRAME = 8192
DROP_DB = 25.0        # caída mínima para considerarla "pared" de codificador
WINDOW_HZ = 500       # ancho en que debe ocurrir la caída
ANALYZE_S = 60        # segundos analizados
MIN_LEVEL_DB = -75.0  # por debajo de esto el tramo es casi silencio: no concluyente
SILENCE_DB = 50.0     # caída hasta silencio digital: firma de codificador aun con corte en ~20 kHz

VERDICTS = {
    "ok": "sin pérdida real",
    "dudoso": "dudoso: corte en {k:.1f} kHz (puede ser MP3 320 o un master filtrado)",
    "falso": "FALSO LOSSLESS: corte en {k:.1f} kHz (origen probable {src})",
    "hires_falso": "hi-res falso: sin contenido por encima de ~{k:.0f} kHz (subido desde 44.1/48 kHz)",
    "no_concluyente": "no concluyente (tramo casi en silencio)",
}


def _decode(path, rate, start, seconds):
    cmd = ["ffmpeg", "-v", "error", "-ss", f"{start:.1f}", "-t", str(seconds), "-i", path,
           "-map", "0:a:0", "-ac", "1", "-ar", str(rate), "-f", "f32le", "-"]
    raw = subprocess.run(cmd, check=True, capture_output=True).stdout
    return np.frombuffer(raw, dtype=np.float32)


def spectrum(path, rate, duration=None):
    """(frecuencias, nivel en dB) promedio, suavizado en bandas de ~100 Hz."""
    start = max(0.0, (duration or 0) * 0.3 - 10) if duration and duration > ANALYZE_S + 20 else 0.0
    x = _decode(path, rate, start, ANALYZE_S)
    if len(x) < FRAME * 4:
        x = _decode(path, rate, 0, ANALYZE_S)
    n = (len(x) - FRAME) // FRAME
    if n < 4:
        return None, None
    frames = np.lib.stride_tricks.sliding_window_view(x, FRAME)[::FRAME][:n] * np.hanning(FRAME)
    power = np.mean(np.abs(np.fft.rfft(frames, axis=1)) ** 2, axis=0)
    freqs = np.fft.rfftfreq(FRAME, 1 / rate)
    band = max(1, int(round(100 / (rate / FRAME))))
    m = len(power) // band * band
    p = power[:m].reshape(-1, band).mean(axis=1)
    f = freqs[:m].reshape(-1, band).mean(axis=1)
    db = 10 * np.log10(p / (FRAME ** 2) + 1e-20)
    return f, db


def find_cutoff(f, db):
    """(frecuencia de la 'pared' en Hz, profundidad en dB) o (None, 0) si no hay corte abrupto.
    De las caídas que parten del nivel de la música, se elige la más profunda."""
    step = f[1] - f[0]
    w = max(2, int(WINDOW_HZ / step))
    tail = max(4, int(2000 / step))
    ref = db[(f >= 10000) & (f <= 14000)].mean()  # nivel de agudos de la música
    best, best_depth = None, 0.0
    for i in range(int(12000 / step), len(f) - w - 2):
        below = db[max(0, i - w):i].mean()
        above = db[i + 1:i + 1 + w].mean()
        rest = db[i + 1:min(len(db), i + 1 + tail)]
        if below < ref - 30:  # ya estamos en la zona vacía: no es la pared de la música
            continue
        if below - above >= DROP_DB and rest.max() < below - DROP_DB * 0.6:
            depth = below - rest.mean()
            if depth > best_depth:
                best, best_depth = f[i], depth
    return best, best_depth


def source_guess(cutoff_hz):
    k = cutoff_hz / 1000
    if k < 16.5:
        return "MP3 ≤128 kbps"
    if k < 18.5:
        return "MP3 ~160-192 kbps"
    if k < 19.7:
        return "MP3/AAC ~224-256 kbps"
    return "MP3 320 kbps"


def analyze(path, rate=None, duration=None):
    """{'verdict', 'cutoff_khz', 'text'}. Solo tiene sentido para archivos sin pérdida."""
    rate = int(rate or 44100)
    f, db = spectrum(path, rate, duration)
    if f is None or db[(f > 1000) & (f < 8000)].mean() < MIN_LEVEL_DB:
        return {"verdict": "no_concluyente", "cutoff_khz": None, "text": VERDICTS["no_concluyente"]}
    nyq = rate / 2
    if rate >= 88200:
        # Hi-res: subir de 44.1/48 kHz no deja una pared sino un vacío por encima de ~22-24 kHz.
        ref = db[(f >= 10000) & (f <= 14000)].mean()
        ultra = db[(f >= 24000) & (f <= min(40000, nyq - 1000))].mean()
        if ultra < ref - SILENCE_DB:
            return {"verdict": "hires_falso", "cutoff_khz": 22.0, "text": VERDICTS["hires_falso"].format(k=22)}
    cut, depth = find_cutoff(f, db)
    if cut is None:
        verdict = "ok"
    elif cut < 19700:
        verdict = "falso"
    elif cut < 20900:
        # Un master real filtrado en ~20 kHz conserva su piso de ruido (dither) por encima del corte;
        # una caída de más de SILENCE_DB hasta el silencio digital es la firma de un MP3/AAC.
        verdict = "falso" if depth >= SILENCE_DB else "dudoso"
    else:
        verdict = "ok"  # corte cerca de Nyquist: filtro antialiasing normal
    k = cut / 1000 if cut else None
    text = VERDICTS[verdict].format(k=k or 0, src=source_guess(cut) if cut else "")
    return {"verdict": verdict, "cutoff_khz": round(k, 1) if k else None, "text": text}


def is_fake(result):
    """Para decisiones automáticas: solo 'falso' y 'hires_falso' cuentan como falsos."""
    return result.get("verdict") in ("falso", "hires_falso")


if __name__ == "__main__":
    from formats import classify_local
    for p in sys.argv[1:]:
        cls, info = classify_local(p)
        r = analyze(p, info.get("rate"), info.get("seconds"))
        print(f"{r['verdict']:>15}  {p}  ·  {r['text']}")
