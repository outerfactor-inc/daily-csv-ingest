import json
from http.server import BaseHTTPRequestHandler

from api.sell_through.three_eye.source import get_latest_csv_snapshot


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            snap = get_latest_csv_snapshot()

            if not snap.get("matched"):
                out = json.dumps(snap, indent=2).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(out)
                return

            # Don't return raw bytes
            csv_bytes = snap.pop("csv_bytes", b"")
            snap["csv_bytes_len"] = len(csv_bytes)

            out = json.dumps(snap, indent=2).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(out)

        except Exception as e:
            err = json.dumps({"ok": False, "error": str(e)}, indent=2).encode("utf-8")
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(err)
