# Vendorizado de djset/comprimir.py (sin cambios).
# No lo edites aquí: cambia el original y vuelve a copiarlo (ver services/README.md).
"""Reduce un DJ set a lo mínimo necesario para reconocerlo: MP3 mono de bajo bitrate.

Uso: python comprimir.py set.wav salida.mp3 [--kbps 96]
Imprime la ruta del archivo a usar: la salida comprimida o, si el set ya es un MP3 igual o más
liviano que el objetivo, el original tal cual (recomprimirlo solo empeoraría la calidad).

Shazam y Panako trabajan internamente a 16 kHz mono y ACRCloud reconoce sin problema a 64-96 kbps,
así que 96 kbps mono reduce un WAV de 2 h de ~1.2 GB a ~85 MB sin afectar el reconocimiento.
Se conserva 44.1 kHz para no alterar los timestamps ni la huella de ACRCloud.
"""
import argparse
import json
import os
import subprocess
import sys

MAX_KBPS = 120


def probe(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries",
         "stream=codec_name,channels:format=duration,bit_rate", "-of", "json", path],
        capture_output=True, text=True, check=True).stdout
    d = json.loads(out)
    s, f = d["streams"][0], d["format"]
    return {"codec": s.get("codec_name"), "channels": int(s.get("channels") or 2),
            "duration": float(f.get("duration") or 0), "kbps": int(f.get("bit_rate") or 0) // 1000}


def mb(path):
    return os.path.getsize(path) / 1e6


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("set")
    ap.add_argument("out")
    ap.add_argument("--kbps", type=int, default=96, help=f"bitrate del MP3 mono (máx. {MAX_KBPS})")
    a = ap.parse_args()
    kbps = min(a.kbps, MAX_KBPS)

    info = probe(a.set)
    if info["codec"] == "mp3" and info["kbps"] <= kbps + 8:
        print(f"El set ya es MP3 de {info['kbps']} kbps ({mb(a.set):.0f} MB): se usa tal cual.", file=sys.stderr)
        print(os.path.abspath(a.set))
        return

    if os.path.exists(a.out) and abs(probe(a.out)["duration"] - info["duration"]) < 1:
        print(f"Ya estaba comprimido: {a.out} ({mb(a.out):.0f} MB)", file=sys.stderr)
        print(os.path.abspath(a.out))
        return

    print(f"Comprimiendo {os.path.basename(a.set)} ({mb(a.set):.0f} MB, {info['codec']} "
          f"{info['kbps']} kbps) a MP3 mono {kbps} kbps…", file=sys.stderr, flush=True)
    tmp = a.out + ".part.mp3"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", a.set, "-map", "0:a:0", "-vn", "-map_metadata", "-1",
                    "-ac", "1", "-ar", "44100", "-c:a", "libmp3lame", "-b:a", f"{kbps}k", tmp], check=True)
    out_info = probe(tmp)
    if abs(out_info["duration"] - info["duration"]) > 1:  # los timestamps dependen de esto
        os.remove(tmp)
        sys.exit(f"La duración cambió al comprimir ({info['duration']:.0f}s → {out_info['duration']:.0f}s)")
    os.replace(tmp, a.out)
    print(f"✓ {mb(a.set):.0f} MB → {mb(a.out):.0f} MB ({100 - mb(a.out) / mb(a.set) * 100:.0f}% menos)",
          file=sys.stderr)
    print(os.path.abspath(a.out))


if __name__ == "__main__":
    main()
