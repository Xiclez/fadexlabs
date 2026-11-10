#!/usr/bin/env python3
# Vendorizado de dj-library-upgrader/upgrader/formats.py (sin cambios).
# No lo edites aquí: cambia el original y vuelve a copiarlo (ver services/README.md).
"""
formats.py — Formatos de audio del DJ Library Upgrader: clasificación, preferencia de búsqueda,
regla de conversión, conversión con ffmpeg y copia de tags/carátula para Rekordbox.

Clases de formato:
    sin pérdida: flac, wav, aiff, alac      con pérdida: mp3 (320 CBR), aac (.m4a 256)

Regla de conversión (al entregar):
    · formato pedido = encontrado            → se copia tal cual
    · sin pérdida → sin pérdida              → se convierte (calidad íntegra; Rekordbox/CDJ prefieren AIFF/WAV)
    · sin pérdida → MP3 320 / AAC 256        → se convierte (para ahorrar espacio)
    · con pérdida → sin pérdida              → NUNCA: sería un "falso lossless"; se entrega el original
    · con pérdida → otro con pérdida         → no: recomprimir degrada; se entrega el original
"""
import os
import re
import subprocess

LOSSLESS = ("aiff", "wav", "flac", "alac")
LOSSY = ("mp3", "aac")
CLASSES = LOSSLESS + LOSSY

# --formato acepta estos nombres
TARGETS = {
    "original": "original",
    "aiff": "aiff", "aif": "aiff",
    "wav": "wav",
    "flac": "flac",
    "alac": "alac",
    "mp3": "mp3",
    "m4a": "aac", "aac": "aac",
}

EXT = {"aiff": ".aiff", "wav": ".wav", "flac": ".flac", "alac": ".m4a", "mp3": ".mp3", "aac": ".m4a"}
LABEL = {"aiff": "AIFF", "wav": "WAV", "flac": "FLAC", "alac": "ALAC", "mp3": "MP3", "aac": "AAC"}

AUDIO_EXTS = (".mp3", ".flac", ".wav", ".aif", ".aiff", ".m4a")

MIN_KBPS = {"mp3": 320, "aac": 256}


def target_from_name(name: str) -> str:
    t = TARGETS.get((name or "original").lower().strip())
    if not t:
        raise ValueError(f"Formato desconocido '{name}'. Usa: " + ", ".join(sorted(set(TARGETS))))
    return t


def default_preference(target: str) -> list:
    """Orden de búsqueda por defecto según el formato pedido."""
    if target == "original":
        return ["mp3", "flac"]                                 # comportamiento histórico: MP3 320, FLAC de respaldo
    if target in LOSSLESS:
        rest = [c for c in LOSSLESS if c != target]
        return [target] + rest + ["mp3", "aac"]                # el MP3/AAC solo si no hay nada sin pérdida
    if target == "mp3":
        return ["mp3"] + list(LOSSLESS) + ["aac"]              # lossless se convierte a MP3 320
    return ["aac"] + list(LOSSLESS) + ["mp3"]                  # aac


def parse_preference(text: str | None, target: str) -> list:
    if not text:
        return default_preference(target)
    out = []
    for raw in text.split(","):
        c = TARGETS.get(raw.strip().lower())
        if c and c != "original" and c not in out:
            out.append(c)
    if not out:
        raise ValueError(f"--preferencia vacía o inválida: '{text}'")
    return out


def good_enough(cls: str, target: str) -> bool:
    """¿Un archivo de esta clase permite entregar el formato pedido sin perder calidad?
    Si sí, se deja de probar más búsquedas para esa canción."""
    if target == "original":
        return cls == "mp3"
    if target in LOSSLESS:
        return cls in LOSSLESS
    return cls == target or cls in LOSSLESS


# ---------- clasificación ----------

def classify_remote(f: dict) -> str | None:
    """Clase de un archivo de un resultado de búsqueda de slskd (o None si no es audio útil)."""
    path = f.get("filename", "")
    ext = (f.get("extension") or path.rsplit(".", 1)[-1]).lower().lstrip(".")
    if ext in ("aif", "aiff"):
        return "aiff"
    if ext in ("mp3", "flac", "wav"):
        return ext
    if ext == "m4a":
        # .m4a puede ser ALAC (sin pérdida) o AAC: ALAC trae bit depth o un bitrate muy alto
        br = f.get("bitRate") or 0
        return "alac" if f.get("bitDepth") or br >= 500 else "aac"
    return None


def classify_local(path: str) -> tuple[str | None, dict]:
    """(clase, info) de un archivo en disco. info: bits, rate, kbps, seconds, vbr."""
    from mutagen import File as MFile

    ext = os.path.splitext(path)[1].lower()
    mf = MFile(path)
    if mf is None or mf.info is None:
        return None, {}
    i = mf.info
    info = {
        "bits": getattr(i, "bits_per_sample", None),
        "rate": getattr(i, "sample_rate", None),
        "kbps": round(i.bitrate / 1000) if getattr(i, "bitrate", 0) else None,
        "seconds": getattr(i, "length", None),
        "vbr": "VBR" in str(getattr(i, "bitrate_mode", "")),
    }
    if ext == ".m4a":
        codec = str(getattr(i, "codec", "")).lower()
        return ("alac" if codec.startswith("alac") else "aac"), info
    return {".mp3": "mp3", ".flac": "flac", ".wav": "wav", ".aif": "aiff", ".aiff": "aiff"}.get(ext), info


def describe(cls: str | None, info: dict) -> str:
    if not cls:
        return "?"
    if cls in LOSSLESS:
        bits = f"{info['bits']}bit/" if info.get("bits") else ""
        rate = f"{info['rate'] / 1000:g}kHz" if info.get("rate") else ""
        return f"{LABEL[cls]} {bits}{rate}".strip()
    kbps = f" {info['kbps']}" if info.get("kbps") else ""
    return f"{LABEL[cls]}{kbps}{' VBR' if info.get('vbr') else ''}"


# ---------- regla de conversión ----------

def decide(src: str, target: str) -> tuple[str, str]:
    """('copy' | 'convert' | 'keep', nota) para entregar `src` cuando se pidió `target`."""
    if target == "original" or src == target:
        return "copy", ""
    if src in LOSSLESS:
        return "convert", f"convertido {LABEL[src]} → {LABEL[target]}"
    if target in LOSSLESS:
        return "keep", (f"no había versión sin pérdida: se entrega el {LABEL[src]} original "
                        f"(convertirlo a {LABEL[target]} sería un falso lossless)")
    return "keep", f"se entrega el {LABEL[src]} original (recomprimir a {LABEL[target]} perdería calidad)"


# ---------- conversión ----------

def _bits(info: dict) -> int:
    b = info.get("bits") or 16
    return 24 if b > 16 else 16


def ffmpeg_args(src: str, dst: str, target: str, info: dict) -> list:
    """Solo audio (sin video/carátula ni tags: esos se copian después con mutagen)."""
    bits = _bits(info)
    rate = info.get("rate") or 44100
    codec = {
        "aiff": ["-c:a", f"pcm_s{bits}be"],
        "wav": ["-c:a", f"pcm_s{bits}le"],
        "flac": ["-c:a", "flac", "-sample_fmt", "s16" if bits == 16 else "s32", "-bits_per_raw_sample", str(bits)],
        "alac": ["-c:a", "alac", "-sample_fmt", "s16p" if bits == 16 else "s32p", "-bits_per_raw_sample", str(bits)],
        "mp3": ["-c:a", "libmp3lame", "-b:a", "320k", "-ar", str(min(rate, 48000))],
        "aac": ["-c:a", "aac", "-b:a", "256k", "-ar", str(min(rate, 48000))],
    }[target]
    return ["ffmpeg", "-v", "error", "-y", "-i", src, "-map", "0:a:0", "-vn", "-map_metadata", "-1", *codec, dst]


def convert(src: str, dst: str, target: str, info: dict) -> None:
    tmp = dst + ".part" + EXT[target]
    try:
        subprocess.run(ffmpeg_args(src, tmp, target, info), check=True, capture_output=True, text=True)
        copy_tags(src, tmp, target)
        os.replace(tmp, dst)
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"ffmpeg falló: {(e.stderr or '').strip()[:300]}") from None
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


# ---------- tags y carátula ----------
# Campos comunes que Rekordbox muestra: título, artista, álbum, género, año, BPM, tonalidad, sello, ISRC…

FIELDS = ("title", "artist", "album", "albumartist", "genre", "date", "tracknumber",
          "bpm", "key", "label", "isrc", "comment")

ID3_MAP = {"TIT2": "title", "TPE1": "artist", "TALB": "album", "TPE2": "albumartist", "TCON": "genre",
           "TDRC": "date", "TRCK": "tracknumber", "TBPM": "bpm", "TKEY": "key", "TPUB": "label", "TSRC": "isrc"}

VORBIS_MAP = {"title": "title", "artist": "artist", "album": "album", "albumartist": "albumartist",
              "genre": "genre", "date": "date", "tracknumber": "tracknumber", "bpm": "bpm",
              "initialkey": "key", "key": "key", "label": "label", "organization": "label",
              "publisher": "label", "isrc": "isrc", "comment": "comment", "description": "comment"}

MP4_MAP = {"\xa9nam": "title", "\xa9ART": "artist", "\xa9alb": "album", "aART": "albumartist",
           "\xa9gen": "genre", "\xa9day": "date", "\xa9cmt": "comment"}
MP4_FREE = {"----:com.apple.iTunes:initialkey": "key", "----:com.apple.iTunes:LABEL": "label",
            "----:com.apple.iTunes:ISRC": "isrc"}


def read_tags(path: str) -> tuple[dict, list]:
    """(campos, carátulas) con carátulas como [(mime, bytes)]."""
    from mutagen import File as MFile
    from mutagen.flac import FLAC
    from mutagen.mp4 import MP4, MP4Cover

    mf = MFile(path)
    tags, pics = {}, []
    if mf is None or mf.tags is None:
        return tags, pics
    if isinstance(mf, FLAC):
        for k, v in mf.tags.items():
            f = VORBIS_MAP.get(k.lower())
            if f and v and f not in tags:
                tags[f] = str(v[0])
        pics = [(p.mime or "image/jpeg", p.data) for p in mf.pictures]
    elif isinstance(mf, MP4):
        for k, f in MP4_MAP.items():
            if mf.tags.get(k):
                tags[f] = str(mf.tags[k][0])
        if mf.tags.get("trkn"):
            n, tot = mf.tags["trkn"][0]
            tags["tracknumber"] = f"{n}/{tot}" if tot else str(n)
        if mf.tags.get("tmpo"):
            tags["bpm"] = str(mf.tags["tmpo"][0])
        for k, f in MP4_FREE.items():
            if mf.tags.get(k):
                tags[f] = bytes(mf.tags[k][0]).decode("utf-8", "replace")
        for c in mf.tags.get("covr", []):
            pics.append(("image/png" if c.imageformat == MP4Cover.FORMAT_PNG else "image/jpeg", bytes(c)))
    else:  # ID3: MP3, AIFF, WAV
        for frame_id, f in ID3_MAP.items():
            fr = mf.tags.get(frame_id)
            if fr and fr.text:
                tags[f] = str(fr.text[0])
        for fr in mf.tags.getall("COMM") if hasattr(mf.tags, "getall") else []:
            if fr.text and "comment" not in tags:
                tags["comment"] = str(fr.text[0])
        if hasattr(mf.tags, "getall"):
            pics = [(p.mime or "image/jpeg", p.data) for p in mf.tags.getall("APIC")]
    return tags, pics


def write_tags(path: str, cls: str, tags: dict, pics: list) -> None:
    from mutagen.aiff import AIFF
    from mutagen.flac import FLAC, Picture
    from mutagen.id3 import APIC, COMM, ID3, ID3NoHeaderError, Frames
    from mutagen.mp4 import MP4, MP4Cover, MP4FreeForm
    from mutagen.wave import WAVE

    if cls in ("mp3", "aiff", "wav"):
        if cls == "mp3":
            try:
                id3 = ID3(path)
            except ID3NoHeaderError:
                id3 = ID3()
            holder = None
        else:
            holder = AIFF(path) if cls == "aiff" else WAVE(path)
            if holder.tags is None:
                holder.add_tags()
            id3 = holder.tags
        for frame_id, f in ID3_MAP.items():
            if tags.get(f):
                id3.setall(frame_id, [Frames[frame_id](encoding=3, text=[tags[f]])])
        if tags.get("comment"):
            id3.setall("COMM", [COMM(encoding=3, lang="eng", desc="", text=[tags["comment"]])])
        if pics:
            mime, data = pics[0]
            id3.setall("APIC", [APIC(encoding=3, mime=mime, type=3, desc="Cover", data=data)])
        # ID3 v2.3: es la versión que Rekordbox y los CDJ leen de forma más fiable
        if holder is None:
            id3.save(path, v2_version=3)
        else:
            holder.save(v2_version=3)
    elif cls == "flac":
        fl = FLAC(path)
        inv = {"key": "initialkey", "label": "label", "comment": "comment"}
        for f in FIELDS:
            if tags.get(f):
                fl[inv.get(f, f)] = tags[f]
        for mime, data in pics[:1]:
            p = Picture()
            p.type, p.mime, p.desc, p.data = 3, mime, "Cover", data
            fl.clear_pictures()
            fl.add_picture(p)
        fl.save()
    elif cls in ("alac", "aac"):
        mp = MP4(path)
        if mp.tags is None:
            mp.add_tags()
        for k, f in MP4_MAP.items():
            if tags.get(f):
                mp.tags[k] = [tags[f]]
        if tags.get("tracknumber"):
            m = re.match(r"(\d+)(?:/(\d+))?", tags["tracknumber"])
            if m:
                mp.tags["trkn"] = [(int(m.group(1)), int(m.group(2) or 0))]
        if tags.get("bpm"):
            try:
                mp.tags["tmpo"] = [int(round(float(tags["bpm"])))]
            except ValueError:
                pass
        for k, f in MP4_FREE.items():
            if tags.get(f):
                mp.tags[k] = [MP4FreeForm(tags[f].encode("utf-8"))]
        if pics:
            mime, data = pics[0]
            fmt = MP4Cover.FORMAT_PNG if "png" in mime else MP4Cover.FORMAT_JPEG
            mp.tags["covr"] = [MP4Cover(data, imageformat=fmt)]
        mp.save()


def copy_tags(src: str, dst: str, dst_cls: str) -> None:
    tags, pics = read_tags(src)
    if tags or pics:
        write_tags(dst, dst_cls, tags, pics)
