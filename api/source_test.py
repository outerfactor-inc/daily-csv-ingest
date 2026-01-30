import json
from http.server import BaseHTTPRequestHandler
from .inventory_source import get_latest_inventory_snapshot


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        r = get_latest_inventory_snapshot()

        # keep output small
        if r.get("parsed") and r["parsed"].get("rows"):
            r["parsed"]["rows_preview"] = r["parsed"]["rows"][:3]
            del r["parsed"]["rows"]

        out = json.dumps(r, indent=2).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(out)
