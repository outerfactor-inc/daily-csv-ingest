import json
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

from api.sell_through.ab_weekly.csv_parser import parse_ab_weekly_sell_through_csv
from api.sell_through.ab_weekly.source import get_latest_csv_snapshot
from api.sell_through.ab.upsert import (
    build_sell_through_fields,
    build_sell_through_line_fields,
    upsert_transaction_group,
)
from api.shared.sf_auth import get_salesforce_token
from api.shared.graph_mail_base import get_ms_token, send_mail


def group_by_transaction(rows: list[dict]) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = {}
    for r in rows:
        tn = (r.get("transaction_number") or "").strip()
        if not tn:
            continue
        groups.setdefault(tn, []).append(r)
    return groups


def _build_notify_email(summary: dict, results: list, tx_errors: list) -> str:
    lines = []

    lines.append("Summary")
    lines.append(f"  Total Rows : {summary.get('total_rows', 'N/A')}")
    lines.append(f"  Kept       : {summary.get('kept', 'N/A')}")
    lines.append(f"  Skipped    : {summary.get('skipped', 'N/A')}")
    lines.append("")

    failed = []
    for r in results:
        if not r.get("ok", True):
            failed.append({
                "transaction_number": r.get("transaction_number", "Unknown"),
                "error": r.get("error", "Unknown error"),
            })
        for le in r.get("lines", {}).get("error_preview", []):
            failed.append({
                "transaction_number": le.get("transaction", r.get("transaction_number", "Unknown")),
                "error": f"SKU {le.get('sku', '?')}: {le.get('error', 'Unknown error')}",
            })
    for te in tx_errors:
        failed.append({
            "transaction_number": te.get("transaction_number", "Unknown"),
            "error": te.get("error", "Unknown error"),
        })

    if failed:
        lines.append("Skipped / Errored Sell Through Records")
        for f in failed:
            lines.append(f"  Skipped Sell Through: {f['transaction_number']}")
            lines.append(f"  Error: {f['error']}")
            lines.append("")
    else:
        lines.append("No errors. All transactions processed successfully.")

    return "\n".join(lines)


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            qs = parse_qs(urlparse(self.path).query)

            limit_tx_raw = qs.get("limitTx", [None])[0]
            limit_tx = (
                int(limit_tx_raw) if limit_tx_raw not in (None, "", "0") else None
            )
            do_write = qs.get("writeSF", ["0"])[0] == "1"
            dry_run = qs.get("dryRun", ["1"])[0] == "1"
            sf_test = qs.get("sfTest", ["0"])[0] == "1"

            snap = get_latest_csv_snapshot()
            if not snap.get("matched"):
                out = json.dumps(
                    {"ok": True, "matched": False, "snap": snap}, indent=2
                ).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(out)
                return

            attachment_name = (snap.get("attachment") or {}).get("name")
            parsed = parse_ab_weekly_sell_through_csv(
                snap["csv_bytes"], attachment_name=attachment_name
            )
            rows = parsed.get("rows") or []
            groups = group_by_transaction(rows)

            tx_keys = list(groups.keys())
            if limit_tx is not None:
                tx_keys = tx_keys[:limit_tx]

            previews = []
            for tn in tx_keys:
                tx_rows = groups[tn]
                previews.append(
                    {
                        "transaction_number": tn,
                        "sell_through_fields": build_sell_through_fields(tx_rows[0]),
                        "line_count": len(tx_rows),
                        "line_fields_preview": [
                            {
                                "sku": r.get("sku"),
                                "line_fields": build_sell_through_line_fields(r),
                            }
                            for r in tx_rows[:5]
                        ],
                    }
                )

            body = {
                "ok": True,
                "matched": True,
                "attachment": snap.get("attachment"),
                "csv_bytes_len": snap.get("csv_bytes_len"),
                "attachment_name": attachment_name,
                "summary": parsed.get("summary"),
                "transactions_found": len(groups),
                "preview_transactions": previews,
            }

            if sf_test:
                tok = get_salesforce_token()
                body["sf"] = {"instance_url": tok.get("instance_url")}

            if do_write and not dry_run:
                tok = get_salesforce_token()
                instance_url = tok["instance_url"]
                access_token = tok["access_token"]

                results = []
                tx_errors = []
                for tn in tx_keys:
                    try:
                        results.append(
                            upsert_transaction_group(instance_url, access_token, groups[tn])
                        )
                    except Exception as e:
                        tx_errors.append({"transaction_number": tn, "error": str(e)})

                body["sf_write"] = {
                    "limitTx": limit_tx,
                    "written_transactions": len(results),
                    "results_preview": results[:3],
                    "transaction_errors": tx_errors,
                }

                try:
                    import os
                    notify_raw = os.environ.get("SELL_THROUGH_EMAIL_NOTIFY", "")
                    from_email = os.environ.get("MAILBOX_USER", "")
                    to_emails = [e.strip() for e in notify_raw.split(",") if e.strip()]
                    if to_emails and from_email:
                        ms_token = get_ms_token()
                        email_body = _build_notify_email(
                            parsed.get("summary", {}),
                            results,
                            tx_errors,
                        )
                        send_mail(
                            ms_token,
                            from_email,
                            to_emails,
                            subject="AB Weekly Sell Through Ingest Report",
                            body=email_body,
                        )
                        body["email_notify"] = {"sent": True, "to": to_emails}
                    else:
                        body["email_notify"] = {"sent": False, "reason": "Missing SELL_THROUGH_EMAIL_NOTIFY or MAILBOX_USER"}
                except Exception as email_err:
                    body["email_notify"] = {"sent": False, "error": str(email_err)}
            else:
                body["sf_write"] = {
                    "limitTx": limit_tx,
                    "note": "No writes performed (set writeSF=1&dryRun=0 to write).",
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
                indent=2,
            ).encode("utf-8")
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(out)
