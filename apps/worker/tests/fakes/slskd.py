"""slskd simulado (API v0) para las pruebas del DJ Library Upgrader: búsquedas con resultados fijos
y "descargas" que copian un archivo local a la carpeta de descargas, como haría slskd."""
import json
import re
import shutil
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote


class FakeSlskd:
    def __init__(self, downloads: Path, logged_in: bool = True):
        self.downloads, self.logged_in = downloads, logged_in
        self.catalog: list[dict] = []        # {"match": palabra, "username", "file": {...}, "source": Path}
        self.searches: dict[str, str] = {}
        self.transfers: list[dict] = []
        self.cancelled: list[str] = []
        self.api_key = "clave-de-prueba"
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, body, code=200):
                data = json.dumps(body).encode()
                self.send_response(code)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _route(self, method):
                if self.headers.get("X-API-Key") != fake.api_key:
                    return self._send({"error": "unauthorized"}, 401)
                n = int(self.headers.get("content-length") or 0)
                body = json.loads(self.rfile.read(n)) if n else None
                path = self.path.split("?")[0].removeprefix("/api/v0")
                self._send(*fake.handle(method, path, body))

            do_GET = lambda self: self._route("GET")        # noqa: E731
            do_POST = lambda self: self._route("POST")      # noqa: E731
            do_DELETE = lambda self: self._route("DELETE")  # noqa: E731

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()

    def offer(self, match: str, username: str, remote: str, source: Path, length: float, stuck=False, **attrs):
        """Un usuario comparte `source` como `remote`; aparece en las búsquedas que contengan `match`.
        Con stuck=True la descarga se queda en cola para siempre (usuario desconectado)."""
        self.catalog.append({"match": match.lower(), "username": username, "source": source, "stuck": stuck, "file": {
            "filename": remote, "size": source.stat().st_size, "length": length, **attrs}})

    def handle(self, method, path, body):
        if path == "/server":
            return ({"state": "Connected, LoggedIn" if self.logged_in else "Disconnected", "isLoggedIn": self.logged_in},)
        if method == "POST" and path == "/searches":
            self.searches[body["id"]] = body["searchText"].lower()
            return ({"id": body["id"]},)
        m = re.fullmatch(r"/searches/([^/]+)(/responses)?", path)
        if m:
            if method == "DELETE":
                return ({},)
            if not m.group(2):
                return ({"isComplete": True, "state": "Completed, TimedOut"},)
            text, by_user = self.searches.get(m.group(1), ""), {}
            for c in self.catalog:
                if c["match"] in text:
                    by_user.setdefault(c["username"], []).append(c["file"])
            return ([{"username": u, "files": fs, "hasFreeUploadSlot": True, "queueLength": 0,
                      "uploadSpeed": 2_000_000} for u, fs in by_user.items()],)
        m = re.fullmatch(r"/transfers/downloads/([^/]+)(?:/([^/]+))?", path)
        if m and method == "POST":
            user = unquote(m.group(1))
            for req in body:
                c = next(c for c in self.catalog if c["username"] == user and c["file"]["filename"] == req["filename"])
                parts = re.split(r"[\\/]", req["filename"])
                dest = self.downloads / parts[-2] / parts[-1]   # slskd guarda en <carpeta remota>/<archivo>
                if not c["stuck"]:
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(c["source"], dest)
                self.transfers.append({"username": user, "filename": req["filename"], "id": f"t{len(self.transfers)}",
                                       "state": "Queued, Remotely" if c["stuck"] else "Completed, Succeeded"})
            return ({},)
        if m and method == "DELETE":
            self.cancelled.append(m.group(2))
            return ({},)
        if path == "/transfers/downloads":
            users = {}
            for t in self.transfers:
                users.setdefault(t["username"], []).append({k: t[k] for k in ("filename", "id", "state")})
            return ([{"username": u, "directories": [{"files": fs}]} for u, fs in users.items()],)
        return ({"error": f"{method} {path} no simulado"}, 404)
