# api/sell_through/three_eye/sf_preview.py

import json
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

from .source import get_latest_csv_snapshot
from .csv_parser import parse_sell_through_3e_csv
from .sf_upsert import build_sell_through_fields, build_sell_through_line_fields


def group_by_transaction(rows: list[dict]) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = {}
    for r in rows:
        tn = (r.get("transaction_number") or "").strip()
        if not tn:
            continue
        groups.setdefault(tn, []).append(r)
    return groups


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            qs = parse_qs(urlparse(self.path).query)
            limit_tx = int(qs.get("limitTx", ["1"])[0])

            snap = get_latest_csv_snapshot()
            if not snap.get("matched"):
                out = json.dumps({"ok": True, "matched": False, "snap": snap}, indent=2).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(out)
                return

            parsed = parse_sell_through_3e_csv(snap["csv_bytes"])
            rows = parsed.get("rows") or []
            groups = group_by_transaction(rows)

            tx_keys = list(groups.keys())[:limit_tx]
            previews = []

            for tn in tx_keys:
                tx_rows = groups[tn]
                parent_fields = build_sell_through_fields(tx_rows[0])

                line_fields_preview = []
                for r in tx_rows[:5]:
                    line_fields_preview.append({
                        "transaction_number": tn,
                        "part_number": r.get("part_number"),
                        "line_fields": build_sell_through_line_fields(r),
                    })

                previews.append({
                    "transaction_number": tn,
                    "sell_through_fields": parent_fields,
                    "line_count": len(tx_rows),
                    "line_fields_preview": line_fields_preview,
                })

            body = {
                "ok": True,
                "matched": True,
                "attachment": snap.get("attachment"),
                "csv_bytes_len": snap.get("csv_bytes_len"),
                "summary": parsed.get("summary"),
                "transactions_found": len(groups),
                "preview_transactions": previews,
            }

            out = json.dumps(body, indent=2).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(out)

        except Exception as e:
            import traceback
            out = json.dumps(
                {"ok": False, "error": str(e), "trace": traceback.format_exc()},
                indent=2
            ).encode("utf-8")
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(out)
