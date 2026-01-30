import os
import json
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

from .inventory_source import get_latest_inventory_snapshot
from .sf_auth import get_salesforce_token
from .inventory_upsert import upsert_inventory_row


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            qs = parse_qs(urlparse(self.path).query)
            limit = int(qs.get("limit", ["1"])[0])
            sf_test = qs.get("sfTest", ["0"])[0] == "1"
            do_write = qs.get("writeSF", ["0"])[0] == "1"
            dry_run = qs.get("dryRun", ["1"])[0] == "1"

            snap = get_latest_inventory_snapshot()

            # If no matching email/csv
            if not snap.get("matched"):
                out = json.dumps(snap, indent=2).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(out)
                return

            parsed = snap["parsed"] or {}
            rows = (parsed.get("rows") or [])[:limit]

            body = {
                "ok": True,
                "matched": True,
                "scanned": snap.get("scanned"),
                "filters": snap.get("filters"),
                "pickedMessage": snap.get("pickedMessage"),
                "attachment": snap.get("attachment"),
                "csv": {
                    "bytes": snap.get("csv_bytes_len"),
                    "summary": parsed.get("summary"),
                    "preview_rows": rows[:1],
                },
            }

            location_name = os.environ.get("THREE_EYE_LOCATION", "3EyeWarehouse")

            row0 = rows[0] if rows else None
            if row0:
                body["sf_preview"] = {
                    "sku": row0["part_number"],
                    "location": location_name,
                    "On_Hand__c": row0["qty_on_hand"],
                    "Available__c": row0["qty_available"],
                    "Committed__c": row0["qty_committed"],
                }

            # SF auth test (no write)
            if sf_test:
                tok = get_salesforce_token()
                body["sf"] = {"instance_url": tok.get("instance_url")}

            # Write (explicitly gated)
            if do_write and not dry_run:
                tok = get_salesforce_token()
                created = updated = skipped = errors = 0
                error_preview = []

                for row in rows:
                    try:
                        r = upsert_inventory_row(
                            instance_url=tok["instance_url"],
                            access_token=tok["access_token"],
                            sku=row["part_number"],
                            location_name=location_name,
                            qty_on_hand=row["qty_on_hand"],
                            qty_available=row["qty_available"],
                            qty_committed=row["qty_committed"],
                        )
                        if r.get("action") == "created":
                            created += 1
                        elif r.get("action") == "updated":
                            updated += 1
                        else:
                            skipped += 1
                    except Exception as e:
                        errors += 1
                        if len(error_preview) < 5:
                            error_preview.append({"sku": row.get("part_number"), "error": str(e)})

                body["sf_batch"] = {
                    "limit": limit,
                    "created": created,
                    "updated": updated,
                    "skipped": skipped,
                    "errors": errors,
                    "error_preview": error_preview,
                }
            else:
                body["sf_batch"] = {
                    "limit": limit,
                    "note": "No writes performed (set writeSF=1&dryRun=0 to write).",
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
