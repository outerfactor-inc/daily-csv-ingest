import json
from http.server import BaseHTTPRequestHandler

from .email_filter import find_latest_sell_through_email
from ...shared.graph_mail_base import get_ms_token


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            token = get_ms_token()
            snap = find_latest_sell_through_email(token)

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
