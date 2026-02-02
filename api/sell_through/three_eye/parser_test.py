import json
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

from .source import get_latest_csv_snapshot
from .csv_parser import parse_sell_through_csv_3e


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            qs = parse_qs(urlparse(self.path).query)
            limit = int(qs.get("limit", ["3"])[0])

            snap = get_latest_csv_snapshot()
            if not snap.get("matched"):
                out = json.dumps(snap, indent=2).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(out)
                return

            csv_bytes = snap["csv_bytes"]
            parsed = parse_sell_through_csv_3e(csv_bytes)

            body = {
                "ok": True,
                "matched": True,
                "pickedMessage": snap.get("pickedMessage"),
                "attachment": snap.get("attachment"),
                "bytes": len(csv_bytes),
                "summary": parsed.get("summary"),
                "preview_rows": (parsed.get("rows") or [])[:limit],
            }

            out = json.dumps(body, indent=2).encode("utf-8")
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
