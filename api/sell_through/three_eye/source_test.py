import json
from http.server import BaseHTTPRequestHandler

from .source import get_latest_csv_snapshot


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            snap = get_latest_csv_snapshot()

            # Never return raw bytes in JSON
            if "csv_bytes" in snap:
                snap["csv_bytes_len"] = len(snap["csv_bytes"])
                del snap["csv_bytes"]

            out = json.dumps(
                {"ok": True, "snap": snap},
                indent=2
            ).encode("utf-8")

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(out)

        except Exception as e:
            out = json.dumps(
                {"ok": False, "error": str(e)},
                indent=2
            ).encode("utf-8")

            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(out)
