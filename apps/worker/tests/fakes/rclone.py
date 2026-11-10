"""rclone simulado: `copy <origen> <remoto:ruta>` copia a FAKE_RCLONE_DIR y `link <remoto:ruta>` imprime un enlace."""
import os
import shutil
import sys

root = os.environ["FAKE_RCLONE_DIR"]
cmd, args = sys.argv[1], [a for a in sys.argv[2:] if not a.startswith("--") and not a.isdigit()]
if os.environ.get("FAKE_RCLONE_FAIL"):
    sys.exit("Failed to copy: googleapi: Error 403: simulado")
if cmd == "copy":
    src, dest = args
    shutil.copytree(src, os.path.join(root, dest.replace(":", "/")), dirs_exist_ok=True)
elif cmd == "link":
    print("https://drive.google.com/drive/folders/" + args[0].rsplit("/", 1)[-1])
else:
    sys.exit(f"comando no simulado: {cmd}")
