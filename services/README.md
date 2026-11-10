# Código de las herramientas (vendorizado)

Copias de los scripts que ya funcionaban en local. El worker (`apps/worker`) los ejecuta como
subprocesos, igual que se usan a mano, así que se actualizan copiando de nuevo el original.

| Carpeta | Origen | Qué hace |
|---|---|---|
| `tracklist/` | `Documents/djset` | `comprimir.py` → `acr_scan.py` → `scan.py` (Shazam) → `tracklist.py` |
| `library_upgrade/` | `Documents/dj-library-upgrader/upgrader` (antes `slskd-vpm`) | `biblioteca.py` → `slskd_fetch.py` → `collect.py` |

Único cambio respecto a los originales: `tracklist/acr_scan.py` toma el token solo de la variable de
entorno `ACRCLOUD_TOKEN` (el original también leía `djset/.env`).

No se copiaron: la verificación con Panako (`verify.py`, `deezer_previews.py`), `subir.sh`/`traer.sh`
(el worker llama a rclone directamente) ni el orquestador `upgrader`.
