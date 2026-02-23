import json
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

from api.sell_through.ab.source import get_latest_csv_snapshot
from api.sell_through.ab.csv_parser import parse_ab_sell_through_csv  # <-- adjust if your parser lives elsewhere


# These are the minimum keys sf_upsert.py expects to exist in each row
REQUIRED_KEYS = [
    "transaction_number",
    "part_number",
    "quantity",
    "unit_cost",
    "extended_cost",
]

# Optional but used for parent mapping (nice to confirm)
PARENT_KEYS = [
    "ship_date",
    "purchase_order",
    "bill_to_customer_name",
    "billing_city",
    "billing_state_province",
    "shipping_address",
    "ship_to_name",
    "shipping_city",
    "shipping_state_province",
    "shipping_zip",
    "3eye_customer",
    "3eye_customer_id",
    "end_user",
    "end_user_id",
]


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            qs = parse_qs(urlparse(self.path).query)
            preview = int(qs.get("preview", ["3"])[0])  # how many rows to show

            snap = get_latest_csv_snapshot()
            if not snap.get("matched"):
                out = json.dumps({"ok": True, "matched": False, "snap": snap}, indent=2).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(out)
                return

            csv_bytes = snap["csv_bytes"]
            parsed = parse_ab_sell_through_csv(csv_bytes)  # your parser already normalizes headers

            rows = parsed.get("rows") or []
            row0 = rows[0] if rows else {}

            missing_required = [k for k in REQUIRED_KEYS if k not in row0]
            missing_parent = [k for k in PARENT_KEYS if k not in row0]

            body = {
                "ok": True,
                "matched": True,
                "attachment": snap.get("attachment"),
                "csv_bytes_len": snap.get("csv_bytes_len"),
                "summary": parsed.get("summary"),
                "row_count": len(rows),
                "required_keys_missing": missing_required,
                "parent_keys_missing": missing_parent,
                "row0_keys": sorted(list(row0.keys())) if row0 else [],
                "preview_rows": rows[:preview],
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
