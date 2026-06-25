"""
Local HTTP server for Chip Radar TW dashboard.

- Maps /data/ requests to local_data/
- Provides /api/decrypt endpoint for devices where crypto.subtle is unavailable
- Injects a fallback script into index.html so remote devices work over plain HTTP
- index.html on disk is never modified

Usage: pythonw scripts/local_server.py  (background)
       python  scripts/local_server.py  (foreground, debugging)
"""
import json
import os
import sys
from http.server import HTTPServer, SimpleHTTPRequestHandler
from socketserver import ThreadingMixIn
from pathlib import Path

PORT = int(os.environ.get("CHIP_RADAR_PORT", "8080"))
PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOCAL_DATA = PROJECT_ROOT / "local_data"
PID_FILE = PROJECT_ROOT / "scripts" / ".server.pid"

sys.path.insert(0, str(PROJECT_ROOT / "src" / "pipelines"))
from crawler_output import decrypt_data

FALLBACK_SCRIPT = """
<script>
(function(){
  if (window.isSecureContext) return;
  var _ready = new Promise(function(r){ document.addEventListener('DOMContentLoaded', r); });
  _ready.then(function(){
    if (typeof decryptToken !== 'function') return;
    window.decryptToken = function(token, password, iterations) {
      return fetch('/api/decrypt', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({token: token, password: password, iterations: iterations || 100000})
      }).then(function(r) {
        if (!r.ok) throw new Error('decrypt-failed');
        return r.text();
      });
    };
  });
})();
</script>
"""


class ChipRadarHandler(SimpleHTTPRequestHandler):

    def translate_path(self, path):
        path = path.split("?")[0].split("#")[0]
        if path.startswith("/data/"):
            return str(LOCAL_DATA / path[6:])
        if path == "/data":
            return str(LOCAL_DATA)
        return super().translate_path(path)

    def do_GET(self):
        clean = self.path.split("?")[0].split("#")[0]
        if clean == "/" or clean == "/index.html":
            self._serve_index()
            return
        super().do_GET()

    def do_POST(self):
        if self.path.startswith("/api/decrypt"):
            self._handle_decrypt()
            return
        self.send_error(404)

    def _serve_index(self):
        index_path = PROJECT_ROOT / "index.html"
        if not index_path.exists():
            self.send_error(404, "index.html not found")
            return
        html = index_path.read_bytes()
        injected = html.replace(b"</head>", FALLBACK_SCRIPT.encode() + b"</head>", 1)
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(injected)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(injected)

    def _handle_decrypt(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length))
            token = body["token"]
            password = body["password"]
            iterations = body.get("iterations", 100000)
            plain = decrypt_data(token, password, iterations=iterations)
            data = plain.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except Exception:
            self.send_response(401)
            self.send_header("Content-Length", "0")
            self.end_headers()

    def log_message(self, format, *args):
        pass


class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


def main():
    os.chdir(str(PROJECT_ROOT))
    LOCAL_DATA.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(str(os.getpid()))

    try:
        server = ThreadingHTTPServer(("0.0.0.0", PORT), ChipRadarHandler)
        print(f"Chip Radar local server on http://localhost:{PORT}")
        print(f"  /data/ -> {LOCAL_DATA}")
        print(f"  /api/decrypt -> server-side fallback")
        print(f"  PID: {os.getpid()}")
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if PID_FILE.exists():
            PID_FILE.unlink()


if __name__ == "__main__":
    main()
