"""shazamio de mentira para probar services/tracklist/scan.py sin red: reconoce los primeros
STUB_SHAZAM_OK fragmentos y después rechaza todo, como cuando Shazam limita por IP. Con
STUB_SHAZAM_BLOCKED=N rechaza solo las N consultas siguientes y luego vuelve a reconocer (el bloqueo pasa)."""
import os

_calls = 0


class HTTPClient:
    def __init__(self, **kw):
        pass


class Shazam:
    def __init__(self, **kw):
        pass

    async def recognize(self, path):
        global _calls
        _calls += 1
        ok, blocked = int(os.environ.get("STUB_SHAZAM_OK", "3")), os.environ.get("STUB_SHAZAM_BLOCKED")
        if _calls > ok and (blocked is None or _calls <= ok + int(blocked)):
            raise RuntimeError("429 Too Many Requests")
        return {"matches": [{"id": "1"}], "track": {"title": "Tema", "subtitle": "Artista"}}
