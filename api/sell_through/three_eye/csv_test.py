import json
from http.server import BaseHTTPRequestHandler

from api.sell_through.three_eye.source import get_latest_csv_snapshot
from api.sell_through.three_eye.csv_parser import parse_sell_through_3e_csv



class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            snap = get_latest_csv_snapshot()
            csv_bytes = snap.get("csv_bytes")

            if not csv_bytes:
                raise Exception("No CSV bytes found")

            parsed = parse_sell_through_3e_csv(csv_bytes)


            out = json.dumps(
                {
                    "ok": True,
                    "summary": parsed["summary"],
                    "preview": parsed["rows"][:3],
                },
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
