# Código de las herramientas (vendorizado)

Copias de los scripts que ya funcionaban en local. El worker (`apps/worker`) los ejecuta como
subprocesos, igual que se usan a mano, así que se actualizan copiando de nuevo el original.

| Carpeta | Origen | Qué hace |
|---|---|---|
| `tracklist/` | `Documents/djset` | `comprimir.py` → `acr_scan.py` → `scan.py` (Shazam) → `tracklist.py` |
| `library_upgrade/` | `Documents/dj-library-upgrader/upgrader` (antes `slskd-vpm`) | `biblioteca.py` → `slskd_fetch.py` → `collect.py` |

Cambios respecto a los originales (al volver a copiar un original hay que reaplicarlos):

- `tracklist/acr_scan.py`: el token llega solo por la variable de entorno `ACRCLOUD_TOKEN` (el original
  también leía `djset/.env`).
- `tracklist/scan.py`: reintentos cortos por fragmento (`--attempts`, `--backoff`, `--query-timeout`) y
  corte por saturación: tras `--max-fail-streak` fragmentos rechazados seguidos termina con código 3 en vez
  de esperar hasta 10 minutos por fragmento.
- `library_upgrade/slskd_fetch.py`: tiempos por canción. Si la descarga de un candidato no arranca en
  `--candidate-wait` s (o se estanca `--stall` s) se cancela en slskd y se prueba otro; si pasan
  `--song-timeout` s sin una descarga avanzando, la pista queda en estado `timeout` («pendiente» en
  `no_encontradas.txt`). Además las descargas se revisan durante la búsqueda, no solo al final.

No se copiaron: la verificación con Panako (`verify.py`, `deezer_previews.py`), `subir.sh`/`traer.sh`
(el worker llama a rclone directamente) ni el orquestador `upgrader`.
