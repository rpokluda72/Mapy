#!/usr/bin/env python3
"""
Local server for Mapy site.
Serves static files and handles the delete API used by the UI.

Usage:
    python server.py          # serves on http://localhost:8000
    python server.py 9000     # custom port
"""
import json
import subprocess
import sys
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

BASE = Path(__file__).parent
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
DATA_FILE    = BASE / "mapy_data.json"
FOLDERS_FILE = BASE / "folders.json"


class Handler(SimpleHTTPRequestHandler):
    protocol_version = "HTTP/1.0"  # disables keep-alive so Ctrl+C exits immediately

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(BASE), **kwargs)

    def end_headers(self):
        ext = self.path.split('?')[0].rsplit('.', 1)[-1]
        if ext in ('json', 'html', 'js', 'png'):
            self.send_header('Cache-Control', 'no-store')
        super().end_headers()

    def log_message(self, fmt, *args):
        # Suppress noisy GET logs; keep errors
        if args and str(args[1]) not in ("200", "304"):
            super().log_message(fmt, *args)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length))
        except Exception as exc:
            self._json_response(400, {"error": f"Bad JSON: {exc}"})
            return

        if self.path == "/api/hide":
            try:
                self._handle_hide(body)
                self._json_response(200, {"ok": True})
            except Exception as exc:
                self._json_response(500, {"error": str(exc)})
        elif self.path == "/api/folders":
            try:
                self._handle_folders(body)
                self._json_response(200, {"ok": True})
            except Exception as exc:
                self._json_response(500, {"error": str(exc)})
        else:
            self.send_response(404)
            self.end_headers()

    def _handle_hide(self, body: dict) -> None:
        with open(DATA_FILE, encoding="utf-8") as f:
            data = json.load(f)

        fi = body["folder_index"]
        hidden = bool(body["hidden"])

        if body["type"] == "folder":
            target = data["folders"][fi]
            target["hidden"] = hidden
            action = "Hidden" if hidden else "Restored"
            print(f"{action} folder: {target['name']}")
        elif body["type"] == "map":
            mi = body["map_index"]
            target = data["folders"][fi]["maps"][mi]
            target["hidden"] = hidden
            action = "Hidden" if hidden else "Restored"
            print(f"{action} map: {target['name']}")
        else:
            raise ValueError(f"Unknown type: {body['type']}")

        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        # Regenerate index.html + data.js
        subprocess.run([sys.executable, str(BASE / "generate_site.py")], check=True)

    def _handle_folders(self, body: dict) -> None:
        with open(FOLDERS_FILE, "w", encoding="utf-8") as f:
            json.dump(body, f, ensure_ascii=False, indent=2)
        n = len(body.get("folders", []))
        print(f"Saved folders.json ({n} folders)")

        # Sync folder and map order into mapy_data.json
        if DATA_FILE.exists():
            with open(DATA_FILE, encoding="utf-8") as f:
                data = json.load(f)
            new_folders = body.get("folders", [])
            data_by_name = {fo["name"]: fo for fo in data.get("folders", [])}
            reordered = []
            for nfo in new_folders:
                dfo = data_by_name.get(nfo["name"])
                if dfo is None:
                    continue
                # sync map order within folder
                new_maps = nfo.get("maps", [])
                maps_by_name = {m["name"]: m for m in dfo.get("maps", [])}
                synced = [maps_by_name[nm["name"]] for nm in new_maps if nm["name"] in maps_by_name]
                extras = [m for m in dfo["maps"] if m["name"] not in {nm["name"] for nm in new_maps}]
                dfo["maps"] = synced + extras
                reordered.append(dfo)
            # keep any data folders absent from folders.json
            known = {nfo["name"] for nfo in new_folders}
            reordered += [fo for fo in data["folders"] if fo["name"] not in known]
            data["folders"] = reordered
            with open(DATA_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            print(f"Synced mapy_data.json order")

    def _json_response(self, code: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    httpd = HTTPServer(("localhost", PORT), Handler)
    print(f"Serving at http://localhost:{PORT}  (Ctrl+C to stop)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
