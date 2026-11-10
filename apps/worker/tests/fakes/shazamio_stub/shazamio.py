"""shazamio de mentira para probar services/tracklist/scan.py sin red: reconoce los primeros
STUB_SHAZAM_OK fragmentos y después rechaza todo, como cuando Shazam limita por IP."""
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
        if _calls > int(os.environ.get("STUB_SHAZAM_OK", "3")):
            raise RuntimeError("429 Too Many Requests")
        return {"matches": [{"id": "1"}], "track": {"title": "Tema", "subtitle": "Artista"}}
