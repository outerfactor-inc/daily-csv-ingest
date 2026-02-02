import json
from http.server import BaseHTTPRequestHandler
from api.sell_through.three_eye.source import get_latest_csv_snapshot

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        snap = get_latest_csv_snapshot()

        # Don't dump raw bytes in response
        if snap.get("matched"):
            snap = dict(snap)
            snap.pop("csv_bytes", None)

        out = json.dumps(snap, indent=2).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(out)
