"""Oberflaeche im Browser testen:  python tools/devserver.py --fake   ->  http://127.0.0.1:8765/?dev"""
import json
import sys
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from raidpilot.api import Api  # noqa: E402


class Handler(SimpleHTTPRequestHandler):
    api = None

    def do_POST(self):
        name = self.path.removeprefix("/api/")
        if name.startswith("_") or not callable(getattr(self.api, name, None)):
            return self.send_error(404)
        length = int(self.headers.get("Content-Length", 0))
        result = getattr(self.api, name)(*json.loads(self.rfile.read(length) or "[]"))
        body = json.dumps(result).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def main():
    adb = None
    if "--fake" in sys.argv:
        from tests.fakegame import FakeGame

        adb = FakeGame()
        # Echte Wartezeiten, damit man dem Ablauf zusehen kann
        adb.sleep = lambda seconds: time.sleep(seconds)
    Handler.api = Api(adb=adb, check_updates=False)
    server = ThreadingHTTPServer(("127.0.0.1", 8765), partial(Handler, directory=str(ROOT / "raidpilot" / "ui")))
    print("http://127.0.0.1:8765/?dev")
    server.serve_forever()


if __name__ == "__main__":
    main()
