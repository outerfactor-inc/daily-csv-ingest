import os
import json
import time
import traceback
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from typing import Any, Callable, Dict, List, Optional

from api.inventory.inv_shared.inventory_source import get_latest_inventory_snapshot
from api.inventory.inv_shared.inventory_upsert import upsert_inventory_row
from api.shared.sf_auth import get_salesforce_token
from api.shared.graph_mail_base import get_ms_token, send_mail


def _build_notify_email(
    label: str,
    *,
    matched: bool,
    mode: str,
    parse_summary: Optional[dict],
    write: Optional[dict],
    scanned: Optional[int],
    fatal_error: Optional[str],
) -> str:
    """Plain-text run report, modeled on the sell_through notification format."""
    lines: List[str] = [f"{label} Inventory Ingest", ""]

    # ---- Status line -------------------------------------------------------
    if fatal_error:
        status = "FAILED"
    elif not matched:
        status = "No matching inventory email found"
    elif write and write.get("timed_out"):
        status = "TIMED OUT (partial run)"
    else:
        status = "Completed"

    lines.append("Summary")
    lines.append(f"  Status      : {status}")
    lines.append(f"  Mode        : {mode}")

    if not matched and not fatal_error:
        lines.append(f"  Scanned     : {scanned if scanned is not None else 'N/A'} messages")
        lines.append("")
        lines.append("No data ingested.")
        return "\n".join(lines)

    if parse_summary is not None:
        total = parse_summary.get("total_rows", "N/A")
        kept = parse_summary.get("kept", "N/A")
        skipped = parse_summary.get("skipped", "N/A")
        zero_qty = parse_summary.get("skipped_zero_qty")
        skipped_str = f"{skipped}"
        if zero_qty is not None:
            skipped_str += f" (zero-qty: {zero_qty})"
        lines.append(f"  Total Rows  : {total}")
        lines.append(f"  Kept        : {kept}")
        lines.append(f"  Skipped     : {skipped_str}")

    # ---- Salesforce write stats -------------------------------------------
    if write is not None:
        lines.append("")
        lines.append("Salesforce Writes")
        lines.append(f"  Created   : {write.get('created', 0)}")
        lines.append(f"  Updated   : {write.get('updated', 0)}")
        lines.append(f"  Skipped   : {write.get('skipped', 0)}")
        lines.append(f"  Errors    : {write.get('errors', 0)}")
        lines.append(f"  Processed : {write.get('processed', 0)} of {write.get('total', 0)} rows")

    # ---- Errors ------------------------------------------------------------
    parse_errors = (parse_summary or {}).get("errors_preview") or []
    write_errors = (write or {}).get("error_preview") or []

    if fatal_error:
        lines.append("")
        lines.append("Run failed with an error:")
        lines.append(f"  {fatal_error}")
    elif parse_errors or write_errors:
        lines.append("")
        lines.append("Errors")
        if parse_errors:
            lines.append("  Parsing:")
            for e in parse_errors:
                lines.append(f"    {e}")
        if write_errors:
            lines.append("  Salesforce:")
            for e in write_errors:
                sku = e.get("sku", "?")
                lines.append(f"    SKU {sku}: {e.get('error', 'Unknown error')}")
    elif write and write.get("timed_out"):
        remaining = (write.get("total", 0) or 0) - (write.get("processed", 0) or 0)
        lines.append("")
        lines.append(
            f"No errors so far, but the run did not finish: {remaining} row(s) "
            "were not processed before the time budget. They will be picked up "
            "on the next scheduled run."
        )
    else:
        lines.append("")
        lines.append("No errors. All rows processed successfully.")

    return "\n".join(lines)


def _subject(label: str, *, matched: bool, write: Optional[dict], fatal_error: Optional[str]) -> str:
    if fatal_error:
        tag = "FAILED"
    elif not matched:
        tag = "NO EMAIL"
    elif write and write.get("timed_out"):
        tag = "TIMED OUT"
    elif write and write.get("errors"):
        tag = "ERRORS"
    else:
        tag = "OK"
    return f"{label} Inventory Ingest Report - {tag}"


def _send_notification(subject: str, body: str) -> dict:
    """Email the run report to SELL_THROUGH_EMAIL_NOTIFY from MAILBOX_USER."""
    notify_raw = os.environ.get("SELL_THROUGH_EMAIL_NOTIFY", "")
    from_email = os.environ.get("MAILBOX_USER", "")
    to_emails = [e.strip() for e in notify_raw.split(",") if e.strip()]
    if not (to_emails and from_email):
        return {"sent": False, "reason": "Missing SELL_THROUGH_EMAIL_NOTIFY or MAILBOX_USER"}
    try:
        token = get_ms_token()
        send_mail(token, from_email, to_emails, subject, body)
        return {"sent": True, "to": to_emails}
    except Exception as e:
        return {"sent": False, "error": str(e)}


def make_inventory_handler(
    *,
    get_filters: Callable[[], Dict[str, Any]],
    parser_fn: Callable[[bytes], Dict[str, Any]],
    location_env: str,
    location_default: str,
    distributor_label: str,
    require_secret: bool = True,
):
    """
    Build a Vercel-compatible BaseHTTPRequestHandler subclass for one
    distributor's inventory ingest endpoint.

    Adding a new distributor only requires a ~5-line ingest.py that calls this
    with the distributor's email filters, parser, label, and Salesforce location.

    Query controls:
      limit   : max number of rows to process (0 = all)
      sfTest  : test Salesforce auth only (no writes)
      writeSF : allow writes to Salesforce
      dryRun  : safety flag; blocks writes even if writeSF=1 (default on)
      notify  : force-send the notification email even on a non-write run
      key     : ingest secret (required when require_secret and INGEST_SECRET set)

    A run notification is emailed (to SELL_THROUGH_EMAIL_NOTIFY, from
    MAILBOX_USER) on real ingestion runs (writeSF=1&dryRun=0) or when notify=1.
    A soft time budget (INVENTORY_INGEST_BUDGET_SECONDS, default 270s) stops the
    write loop before Vercel's hard maxDuration so a partial/timeout run can
    still report instead of being killed silently.
    """

    def _write(self, status: int, payload: dict):
        out = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(out)

    class handler(BaseHTTPRequestHandler):
        def do_GET(self):
            # Defaults so the except-path can still decide whether to notify.
            do_write = False
            dry_run = True
            should_notify = False

            try:
                qs = parse_qs(urlparse(self.path).query)
                limit = int(qs.get("limit", ["0"])[0])
                sf_test = qs.get("sfTest", ["0"])[0] == "1"
                do_write = qs.get("writeSF", ["0"])[0] == "1"
                dry_run = qs.get("dryRun", ["1"])[0] == "1"
                force_notify = qs.get("notify", ["0"])[0] == "1"

                is_real_run = do_write and not dry_run
                should_notify = is_real_run or force_notify
                mode = "write" if is_real_run else ("dry_run" if do_write else "preview")

                # Enforce ingest secret when configured.
                if require_secret:
                    secret = os.environ.get("INGEST_SECRET", "")
                    key = qs.get("key", [""])[0]
                    if secret and key != secret:
                        _write(self, 401, {"ok": False, "error": "Unauthorized"})
                        return

                # Fetch latest matching email + parse the attachment.
                snap = get_latest_inventory_snapshot(get_filters(), parser_fn)

                if not snap.get("matched"):
                    if should_notify:
                        body_txt = _build_notify_email(
                            distributor_label,
                            matched=False,
                            mode=mode,
                            parse_summary=None,
                            write=None,
                            scanned=snap.get("scanned"),
                            fatal_error=None,
                        )
                        subj = _subject(distributor_label, matched=False, write=None, fatal_error=None)
                        snap["email_notify"] = _send_notification(subj, body_txt)
                    _write(self, 200, snap)
                    return

                parsed = snap.get("parsed") or {}
                all_rows = parsed.get("rows") or []
                rows = all_rows if limit <= 0 else all_rows[:limit]

                location_name = os.environ.get(location_env, location_default)

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

                row0 = rows[0] if rows else None
                if row0:
                    body["sf_preview"] = {
                        "sku": row0["sku"],
                        "location": location_name,
                        "On_Hand__c": row0["on_hand"],
                        "Available__c": row0["available"],
                        "On_Order__c": row0["on_order"],
                    }

                if sf_test:
                    tok = get_salesforce_token()
                    body["sf"] = {"instance_url": tok.get("instance_url")}

                write_stats: Optional[dict] = None

                if is_real_run:
                    tok = get_salesforce_token()
                    created = updated = skipped = errors = processed = 0
                    error_preview = []

                    # Soft time budget so we can report a partial run instead of
                    # being hard-killed at Vercel's maxDuration.
                    budget = float(os.environ.get("INVENTORY_INGEST_BUDGET_SECONDS", "270"))
                    start = time.monotonic()
                    timed_out = False

                    for row in rows:
                        if time.monotonic() - start > budget:
                            timed_out = True
                            break
                        processed += 1
                        try:
                            r = upsert_inventory_row(
                                instance_url=tok["instance_url"],
                                access_token=tok["access_token"],
                                sku=row["sku"],
                                location_name=location_name,
                                on_hand=row["on_hand"],
                                available=row["available"],
                                on_order=row["on_order"],
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
                                error_preview.append({"sku": row.get("sku"), "error": str(e)})

                    write_stats = {
                        "limit": limit,
                        "created": created,
                        "updated": updated,
                        "skipped": skipped,
                        "errors": errors,
                        "processed": processed,
                        "total": len(rows),
                        "timed_out": timed_out,
                        "error_preview": error_preview,
                    }
                    body["sf_batch"] = write_stats
                else:
                    body["sf_batch"] = {
                        "limit": limit,
                        "note": "No writes performed (set writeSF=1&dryRun=0 to write).",
                    }

                if should_notify:
                    body_txt = _build_notify_email(
                        distributor_label,
                        matched=True,
                        mode=mode,
                        parse_summary=parsed.get("summary"),
                        write=write_stats,
                        scanned=snap.get("scanned"),
                        fatal_error=None,
                    )
                    subj = _subject(distributor_label, matched=True, write=write_stats, fatal_error=None)
                    body["email_notify"] = _send_notification(subj, body_txt)

                _write(self, 200, body)

            except Exception as e:
                err = str(e)
                trace = traceback.format_exc()
                # Best-effort failure notification on real runs.
                if should_notify:
                    try:
                        body_txt = _build_notify_email(
                            distributor_label,
                            matched=True,
                            mode=("write" if (do_write and not dry_run) else "preview"),
                            parse_summary=None,
                            write=None,
                            scanned=None,
                            fatal_error=err,
                        )
                        subj = _subject(distributor_label, matched=True, write=None, fatal_error=err)
                        _send_notification(subj, body_txt)
                    except Exception:
                        pass
                _write(self, 500, {"ok": False, "error": err, "trace": trace})

    return handler
